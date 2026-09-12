"""Stage 5: development-only ``astra_campaign_*`` interfaces.

Plain Python functions over a campaigns root directory (default
``workspace/campaigns``, always ignored by Git).  They compose the layers
built in the previous stages — store, policy, portfolio, executor, decision,
resume — into the five verbs the architecture review reserved for
development use:

- ``astra_campaign_start``      create (and optionally activate) a campaign,
                                seed branches from an initial portfolio, and
                                select the first active branch;
- ``astra_campaign_status``     strictly read-only resume report;
- ``astra_campaign_step``       one episode -> decision -> ledger step;
- ``astra_campaign_stop``       pause or cancel;
- ``astra_campaign_reactivate`` PAUSED -> ACTIVE after human review;
- ``astra_campaign_list``       enumerate campaigns under the root.

**These interfaces must not be registered in the production MCP before
acceptance** (`ASTRA2_ACCEPTANCE.md`).  This module never imports
``mcp_server`` and a regression test pins both facts.  Every function opens
its own store and releases the single-writer lock before returning, so
sequential calls from different sessions never deadlock.  No model calls
happen here; ``astra_campaign_step`` only reaches models through the real
cycle when no ``cycle_runner`` is injected.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from core.campaign_decision import (
    CampaignDecisionError,
    StepReport,
    campaign_step,
    select_initial_branch,
)
from core.campaign_models import (
    Actor,
    BranchStatus,
    BudgetVector,
    Campaign,
    CampaignStatus,
    EvidenceKind,
    CampaignModelError,
    new_record_id,
    utc_now_iso,
    validate_record_id,
)
from core.campaign_policy import evaluate_branch_admissibility
from core.campaign_portfolio import (
    Portfolio,
    PortfolioError,
    portfolio_to_records,
)
from core.campaign_resume import resume_campaign
from core.campaign_store import CampaignStore
from core.campaign_executor import EpisodeRunReport

# Re-exported so existing callers/tests keep importing them from here; the
# implementation now lives in one shared, hardened place (see HANDOFF.md §12).
from core.git_head import (  # noqa: F401
    git_dir as _git_dir,
    read_head_commit as _read_head_commit,
    resolve_head_commit as _resolve_head_commit,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGNS_ROOT = ROOT / "workspace" / "campaigns"


class CampaignApiError(RuntimeError):
    """A development interface refused an invalid request."""


def _resolve_source_commit(explicit: str | None) -> str:
    """HEAD commit for provenance, resolved without a hang-prone subprocess.

    Delegates to the shared, hardened resolver (explicit -> env -> direct
    ref-file read -> hardened last-resort git); raises only when every source
    fails.
    """
    commit = _resolve_head_commit(
        ROOT, explicit=explicit, env_var="ASTRA_SOURCE_COMMIT"
    )
    if commit:
        return commit
    raise CampaignApiError(
        "Cannot resolve source_commit: pass it explicitly or set "
        "ASTRA_SOURCE_COMMIT"
    )


def _open_store(
    campaign_id: str, root: Path | str | None, source_commit: str | None
) -> CampaignStore:
    return CampaignStore(
        Path(root) if root is not None else DEFAULT_CAMPAIGNS_ROOT,
        campaign_id,
        source_commit=_resolve_source_commit(source_commit),
    )


def _seed_portfolio_branches(
    store: CampaignStore,
    campaign: Campaign,
    portfolio: Portfolio,
    *,
    id_factory: Callable[[str], str],
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    """Record every candidate as claim + PROPOSED branch, then gate it."""
    records = portfolio_to_records(
        portfolio,
        campaign,
        source_commit=store.source_commit,
        created_at=now_iso(),
        id_factory=id_factory,
    )
    admissible: list[str] = []
    rejected: list[str] = []
    for claim, branch in records:
        occurred_at = now_iso()
        store.append_event(
            event_type="CLAIM_RECORDED",
            payload={"claim": claim.to_dict()},
            actor=Actor.SYSTEM,
            occurred_at=occurred_at,
        )
        store.append_event(
            event_type="BRANCH_CREATED",
            payload={"branch": branch.to_dict()},
            actor=Actor.SYSTEM,
            occurred_at=occurred_at,
        )
        state = store.replay().state
        gates = evaluate_branch_admissibility(
            state, state.branches[branch.branch_id]
        )
        store.append_event(
            event_type="BRANCH_STATUS_CHANGED",
            payload={
                "branch_id": branch.branch_id,
                "status": (
                    BranchStatus.ADMISSIBLE.value
                    if gates.passed
                    else BranchStatus.REJECTED.value
                ),
                "reason": f"initial portfolio gates: {gates.to_dict()}"[:2000],
            },
            actor=Actor.SYSTEM,
            occurred_at=occurred_at,
        )
        (admissible if gates.passed else rejected).append(branch.branch_id)
    return {"admissible": admissible, "rejected": rejected}


def astra_campaign_start(
    *,
    objective: str,
    success_definition: str,
    deliverables: list[str],
    allowed_evidence_classes: list[str],
    budget: Mapping[str, int],
    frozen_resources: Mapping[str, str] | None = None,
    initial_portfolio: Mapping[str, Any] | None = None,
    campaign_id: str | None = None,
    activate: bool = True,
    root: Path | str | None = None,
    source_commit: str | None = None,
    id_factory: Callable[[str], str] = new_record_id,
    now_iso: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    """Create a campaign; optionally seed and select its first branch."""
    campaign_id = campaign_id or id_factory("campaign")
    validate_record_id(campaign_id, "campaign")
    store = _open_store(campaign_id, root, source_commit)
    try:
        try:
            campaign = Campaign(
                campaign_id=campaign_id,
                created_at=now_iso(),
                source_commit=store.source_commit,
                objective=objective,
                success_definition=success_definition,
                deliverables=tuple(deliverables),
                frozen_resources=dict(frozen_resources or {}),
                allowed_evidence_classes=tuple(
                    EvidenceKind(item) for item in allowed_evidence_classes
                ),
                budget=BudgetVector.from_dict(budget),
            )
        except (CampaignModelError, ValueError) as exc:
            raise CampaignApiError(f"Invalid campaign definition: {exc}") from exc
        store.append_event(
            event_type="CAMPAIGN_CREATED",
            payload={"campaign": campaign.to_dict()},
            actor=Actor.HUMAN,
            occurred_at=campaign.created_at,
        )
        seeding: dict[str, Any] = {"admissible": [], "rejected": []}
        if activate:
            store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": CampaignStatus.ACTIVE.value},
                actor=Actor.HUMAN,
                occurred_at=now_iso(),
            )
        if initial_portfolio is not None:
            try:
                portfolio = Portfolio.from_dict(initial_portfolio)
            except PortfolioError as exc:
                raise CampaignApiError(
                    f"Invalid initial portfolio: {exc}"
                ) from exc
            try:
                seeding = _seed_portfolio_branches(
                    store,
                    campaign,
                    portfolio,
                    id_factory=id_factory,
                    now_iso=now_iso,
                )
            except PortfolioError as exc:
                raise CampaignApiError(
                    f"Initial portfolio not convertible: {exc}"
                ) from exc
            if activate and seeding["admissible"]:
                select_initial_branch(
                    store, id_factory=id_factory, now_iso=now_iso
                )
        store.write_checkpoint()
        report = resume_campaign(store, rebuild_checkpoint=False)
        return {"campaign_id": campaign_id, "seeding": seeding,
                **report.to_dict()}
    finally:
        store.close()


def astra_campaign_status(
    campaign_id: str,
    *,
    root: Path | str | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Strictly read-only status; never takes the writer lock."""
    store = _open_store(campaign_id, root, source_commit)
    try:
        return resume_campaign(store, rebuild_checkpoint=False).to_dict()
    finally:
        store.close()


def _step_report_to_dict(report: StepReport) -> dict[str, Any]:
    episode: EpisodeRunReport = report.episode
    return {
        "episode_id": episode.episode_id,
        "operation_status": episode.axes.operation_status.value,
        "claim_status": episode.axes.claim_status.value,
        "evidence_outcome": (
            episode.axes.evidence_outcome.value
            if episode.axes.evidence_outcome
            else None
        ),
        "goal_coverage": episode.axes.goal_coverage.value,
        "tested_claim_ids": list(episode.tested_claim_ids),
        "evidence_id": episode.evidence_id,
        "promoted_branch_ids": list(episode.promoted_branch_ids),
        "rejected_branch_ids": list(episode.rejected_branch_ids),
        "budget_exhausted": episode.budget_exhausted,
        "episode_notes": list(episode.notes),
        "decision_rule": report.plan.rule,
        "decisions": [
            {
                "decision_id": decision.decision_id,
                "action": decision.action.value,
                "subject_branch_id": decision.subject_branch_id,
                "reasons": list(decision.reasons),
            }
            for decision in report.plan.decisions
        ],
        "plan_notes": list(report.plan.notes),
        "events_appended": report.events_appended,
    }


async def astra_campaign_step(
    campaign_id: str,
    *,
    root: Path | str | None = None,
    source_commit: str | None = None,
    cycle_runner: Callable[[dict], Any] | None = None,
    model_recommendation: Mapping[str, Any] | None = None,
    evidence_metadata: Mapping[str, Any] | None = None,
    cycle_timeout_seconds: int | None = None,
    id_factory: Callable[[str], str] = new_record_id,
    now_iso: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    """Run one campaign step; auto-selects the first branch when needed."""
    store = _open_store(campaign_id, root, source_commit)
    try:
        report = resume_campaign(store)
        if report.next_action == "select_initial_branch":
            select_initial_branch(store, id_factory=id_factory, now_iso=now_iso)
            report = resume_campaign(store, rebuild_checkpoint=False)
        if report.next_action != "campaign_step":
            raise CampaignApiError(
                f"Campaign {campaign_id} cannot step now; next action is "
                f"{report.next_action!r}"
            )
        try:
            step = await campaign_step(
                store,
                cycle_runner=cycle_runner,
                model_recommendation=model_recommendation,
                evidence_metadata=evidence_metadata,
                cycle_timeout_seconds=cycle_timeout_seconds,
                id_factory=id_factory,
                now_iso=now_iso,
            )
        except CampaignDecisionError as exc:
            raise CampaignApiError(str(exc)) from exc
        status = resume_campaign(store, rebuild_checkpoint=False).to_dict()
        return {"step": _step_report_to_dict(step), "status": status}
    finally:
        store.close()


def astra_campaign_stop(
    campaign_id: str,
    *,
    mode: str = "pause",
    reason: str | None = None,
    root: Path | str | None = None,
    source_commit: str | None = None,
    now_iso: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    """Pause (resumable) or cancel (terminal) a campaign."""
    statuses = {
        "pause": CampaignStatus.PAUSED.value,
        "cancel": CampaignStatus.CANCELLED.value,
    }
    if mode not in statuses:
        raise CampaignApiError(
            f"Unknown stop mode {mode!r}; use 'pause' or 'cancel'"
        )
    store = _open_store(campaign_id, root, source_commit)
    try:
        payload: dict[str, Any] = {"status": statuses[mode]}
        if reason:
            payload["reason"] = str(reason)[:2000]
        try:
            store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload=payload,
                actor=Actor.HUMAN,
                occurred_at=now_iso(),
            )
        except Exception as exc:
            raise CampaignApiError(f"Cannot stop campaign: {exc}") from exc
        store.write_checkpoint()
        return resume_campaign(store, rebuild_checkpoint=False).to_dict()
    finally:
        store.close()


def astra_campaign_reactivate(
    campaign_id: str,
    *,
    root: Path | str | None = None,
    source_commit: str | None = None,
    now_iso: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    """PAUSED -> ACTIVE after an explicit human review."""
    store = _open_store(campaign_id, root, source_commit)
    try:
        try:
            store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": CampaignStatus.ACTIVE.value},
                actor=Actor.HUMAN,
                occurred_at=now_iso(),
            )
        except Exception as exc:
            raise CampaignApiError(f"Cannot reactivate campaign: {exc}") from exc
        store.write_checkpoint()
        return resume_campaign(store, rebuild_checkpoint=False).to_dict()
    finally:
        store.close()


def astra_campaign_list(
    *,
    root: Path | str | None = None,
    source_commit: str | None = None,
) -> list[dict[str, Any]]:
    """Enumerate campaigns under the root, read-only, tolerating damage."""
    base = Path(root) if root is not None else DEFAULT_CAMPAIGNS_ROOT
    if not base.exists():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / "events.jsonl").exists():
            continue
        try:
            validate_record_id(child.name, "campaign")
        except CampaignModelError:
            continue
        try:
            entries.append(
                astra_campaign_status(
                    child.name, root=base, source_commit=source_commit
                )
            )
        except Exception as exc:
            entries.append(
                {
                    "campaign_id": child.name,
                    "health": "ERROR",
                    "next_action": "inspect_manually",
                    "notes": [f"status failed: {exc}"],
                }
            )
    return entries
