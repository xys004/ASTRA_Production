"""Stage 3: deterministic decision policy and progressive widening.

After every recorded episode this module decides — with an ordered,
first-match-wins rule table derived exclusively from the replayed ledger —
whether the campaign continues its active branch, promotes an alternative,
suspends, closes, or requests human review.  Every choice is persisted as a
Decision record with the exact budget snapshot, the deterministic policy
result, and any model recommendation stored separately: a model
recommendation can never override a failed hard gate.

Rule table (first match wins):

- R1  goal-complete      : every mandatory deliverable resolved
                           -> CLOSE, campaign COMPLETED.
- R2  campaign-exhausted : remaining budget covers no candidate's evidence
                           plan -> CLOSE, campaign EXHAUSTED.
- R3  refutation         : the episode scientifically refuted a branch claim
                           -> branch REFUTED, PROMOTE best admissible
                           alternative (progressive widening after negative
                           evidence) or REQUEST_HUMAN_REVIEW + PAUSED.
- R4  branch-exhausted   : the branch consumed its own cycle budget
                           -> branch EXHAUSTED, promote or human review.
- R5  uninformative      : >= MAX_UNINFORMATIVE_STREAK consecutive episodes
                           with claim status NOT_TESTED/INCONCLUSIVE
                           -> SUSPEND, promote or human review.  A single
                           uninformative episode only retries (CONTINUE).
- R6  affordability      : the active branch's plan no longer fits the
                           remaining budget but an alternative's does
                           -> SUSPEND active, PROMOTE the alternative.
- R7  default            : CONTINUE the active branch.

Alternative selection is lexicographic over the visible priority vector
(higher information gain, higher methodological independence, higher goal
advancement, lower estimated cost, lower instability risk, branch id as the
final tiebreak), re-running the six hard admissibility gates and the R4
forbidden-family rule at promotion time.  Widening therefore only happens
after negative/inconclusive evidence or budget pressure — never for free.

Pure domain logic: no model calls, no network, no MCP, no ASTRUM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from core.campaign_executor import (
    EpisodeRunReport,
    run_episode,
)
from core.campaign_models import (
    Actor,
    Branch,
    BranchStatus,
    BudgetSnapshot,
    BudgetVector,
    CampaignStatus,
    ClaimStatus,
    Decision,
    DecisionAction,
    EvidenceOutcome,
    OperationStatus,
    new_record_id,
    utc_now_iso,
)
from core.campaign_policy import (
    CampaignState,
    evaluate_branch_admissibility,
)
from core.campaign_store import CampaignStore

MAX_UNINFORMATIVE_STREAK = 2

_UNINFORMATIVE_CLAIM_STATUSES = frozenset(
    {ClaimStatus.NOT_TESTED, ClaimStatus.INCONCLUSIVE}
)


class CampaignDecisionError(RuntimeError):
    """The decision policy refused to run on an invalid state."""


@dataclass(frozen=True)
class PlannedTransition:
    """One status change the plan will apply, in order."""

    kind: str  # "branch" | "campaign"
    target_id: str | None
    new_status: str
    reason: str
    decision_id: str | None = None


@dataclass(frozen=True)
class DecisionPlan:
    rule: str
    decisions: tuple[Decision, ...]
    transitions: tuple[PlannedTransition, ...]
    notes: tuple[str, ...] = ()


def branch_spent(state: CampaignState, branch_id: str) -> BudgetVector:
    """Per-branch spend derived from its recorded episodes."""
    total = BudgetVector()
    for episode in state.episodes.values():
        if episode.branch_id == branch_id:
            total = total.add(episode.budget)
    return total


def uninformative_streak(state: CampaignState, branch_id: str) -> int:
    """Trailing run of NOT_TESTED/INCONCLUSIVE episodes on one branch.

    An episode that told us nothing about the DIRECTION is skipped entirely
    rather than counted. Observed live on 2026-08-16, first episode of the
    travelling-wave campaign: a duplicated launch lost the model-account lock
    and recorded an episode with no phases, no models and no timings, which then
    helped promote a second branch. Widening on that is the operation-into-
    branch collapse the five axes exist to prevent - the campaign learned
    nothing about the direction, only that two processes raced.

    The discriminator keys on whether the episode produced EVIDENCE, not on
    whether it spent wall-clock. That is the line the five axes already draw:
    ``map_cycle_outcome`` gives an API_ERROR no evidence outcome at all (a tool
    broke - informative about nothing), a CODE_ERROR an OPERATIONAL_ERROR
    outcome (a validator was authored and crashed - informative that the
    direction is hard to test), and a reviewer refusal an INCONCLUSIVE outcome
    (the gate declined - informative about the direction). So a FAILED episode
    that recorded no evidence is infrastructure, and it is skipped; one that
    recorded evidence, or that completed, is real and it counts.

    This matters because the old ``not episode.timings`` proxy miscounted a
    provider outage. Observed live 2026-08-18, campaign cmp_6804eb1d1eb8422e:
    an API 500 killed the translator after 935 s of conjecture-plus-translate,
    so ``timings`` was non-empty and the outage counted toward the streak; a
    single genuine reviewer refusal on the next episode then tripped the
    two-episode pause one episode early. Skipped episodes neither extend nor
    reset the run, because they are not evidence in either direction.
    """
    streak = 0
    for episode in reversed(list(state.episodes.values())):
        if episode.branch_id != branch_id:
            continue
        infrastructure_failure = (
            episode.operation_status is OperationStatus.FAILED
            and not episode.evidence_refs
        )
        if infrastructure_failure:
            continue
        if episode.claim_status in _UNINFORMATIVE_CLAIM_STATUSES:
            streak += 1
        else:
            break
    return streak


def _priority_sort_key(branch: Branch) -> tuple:
    vector = branch.priority_vector
    return (
        -vector.information_gain,
        -vector.methodological_independence,
        -vector.goal_advancement,
        vector.estimated_cost,
        vector.instability_risk,
        branch.branch_id,
    )


def select_promotion_candidate(
    state: CampaignState,
    *,
    extra_forbidden_families: tuple[str, ...] = (),
) -> tuple[Branch | None, dict[str, Any]]:
    """Best ADMISSIBLE branch by lexicographic priority, gates re-validated.

    Returns (branch or None, per-candidate audit trail).  A candidate is
    eligible only when the six hard gates still pass, its method family is
    not forbidden, and the remaining budget covers its evidence plan.
    """
    campaign = state.require_campaign()
    remaining = campaign.budget.remaining_after(state.spent)
    forbidden = {
        item.lower()
        for item in (*state.exhausted_method_families(), *extra_forbidden_families)
    }
    trail: dict[str, Any] = {}
    eligible: list[Branch] = []
    for branch in sorted(state.branches.values(), key=_priority_sort_key):
        if branch.status is not BranchStatus.ADMISSIBLE:
            continue
        gates = evaluate_branch_admissibility(state, branch)
        family_forbidden = branch.method_family.lower() in forbidden
        affordable = remaining.covers(branch.evidence_plan.estimated_cost)
        trail[branch.branch_id] = {
            "hard_gates_passed": gates.passed,
            "failed_gates": list(gates.failed_gates),
            "forbidden_family": family_forbidden,
            "affordable": affordable,
        }
        if gates.passed and not family_forbidden and affordable:
            eligible.append(branch)
    return (eligible[0] if eligible else None), trail


def _make_decision(
    state: CampaignState,
    *,
    action: DecisionAction,
    rule: str,
    reasons: tuple[str, ...],
    policy_extra: Mapping[str, Any],
    hard_gates_passed: bool,
    subject_branch_id: str | None,
    alternatives: tuple[str, ...],
    model_recommendation: Mapping[str, Any] | None,
    id_factory: Callable[[str], str],
    now_iso: Callable[[], str],
    source_commit: str,
) -> Decision:
    campaign = state.require_campaign()
    policy_result: dict[str, Any] = {
        "hard_gates_passed": hard_gates_passed,
        "rule": rule,
    }
    policy_result.update(dict(policy_extra))
    return Decision(
        decision_id=id_factory("decision"),
        campaign_id=campaign.campaign_id,
        created_at=now_iso(),
        source_commit=source_commit,
        action=action,
        policy_result=policy_result,
        reasons=reasons,
        budget_snapshot=BudgetSnapshot(limits=campaign.budget, spent=state.spent),
        subject_branch_id=subject_branch_id,
        model_recommendation=(
            dict(model_recommendation) if model_recommendation else None
        ),
        alternatives_considered=alternatives,
    )


def _promotion_or_human_review(
    state: CampaignState,
    *,
    rule: str,
    demoted_branch: Branch,
    demotion_status: BranchStatus,
    demotion_reason: str,
    model_recommendation: Mapping[str, Any] | None,
    id_factory: Callable[[str], str],
    now_iso: Callable[[], str],
    source_commit: str,
    notes: tuple[str, ...] = (),
) -> DecisionPlan:
    """Demote the active branch, then widen or escalate to a human."""
    extra_forbidden = (
        (demoted_branch.method_family,)
        if demotion_status
        in {BranchStatus.REFUTED, BranchStatus.EXHAUSTED, BranchStatus.CLOSED}
        else ()
    )
    candidate, trail = select_promotion_candidate(
        state, extra_forbidden_families=extra_forbidden
    )
    notes = tuple(notes)
    recommendation_note = _recommendation_note(
        model_recommendation, candidate, trail
    )
    if recommendation_note:
        notes = (*notes, recommendation_note)
    if candidate is not None:
        decision = _make_decision(
            state,
            action=DecisionAction.PROMOTE,
            rule=rule,
            reasons=(
                demotion_reason,
                f"promoting {candidate.branch_id} "
                f"({candidate.method_family}) by lexicographic priority",
            ),
            policy_extra={"candidates": trail},
            hard_gates_passed=True,
            subject_branch_id=candidate.branch_id,
            alternatives=tuple(
                branch_id
                for branch_id in sorted(trail)
                if branch_id != candidate.branch_id
            ),
            model_recommendation=model_recommendation,
            id_factory=id_factory,
            now_iso=now_iso,
            source_commit=source_commit,
        )
        return DecisionPlan(
            rule=rule,
            decisions=(decision,),
            transitions=(
                PlannedTransition(
                    kind="branch",
                    target_id=demoted_branch.branch_id,
                    new_status=demotion_status.value,
                    reason=demotion_reason,
                    decision_id=decision.decision_id,
                ),
                PlannedTransition(
                    kind="branch",
                    target_id=candidate.branch_id,
                    new_status=BranchStatus.ACTIVE.value,
                    reason=f"promoted by rule {rule}",
                    decision_id=decision.decision_id,
                ),
            ),
            notes=notes,
        )
    decision = _make_decision(
        state,
        action=DecisionAction.REQUEST_HUMAN_REVIEW,
        rule=rule,
        reasons=(
            demotion_reason,
            "no admissible, affordable, non-forbidden alternative remains",
        ),
        policy_extra={"candidates": trail},
        hard_gates_passed=True,
        subject_branch_id=demoted_branch.branch_id,
        alternatives=tuple(sorted(trail)),
        model_recommendation=model_recommendation,
        id_factory=id_factory,
        now_iso=now_iso,
        source_commit=source_commit,
    )
    return DecisionPlan(
        rule=rule,
        decisions=(decision,),
        transitions=(
            PlannedTransition(
                kind="branch",
                target_id=demoted_branch.branch_id,
                new_status=demotion_status.value,
                reason=demotion_reason,
                decision_id=decision.decision_id,
            ),
            PlannedTransition(
                kind="campaign",
                target_id=None,
                new_status=CampaignStatus.PAUSED.value,
                reason="human review requested",
                decision_id=decision.decision_id,
            ),
        ),
        notes=notes,
    )


def _recommendation_note(
    model_recommendation: Mapping[str, Any] | None,
    candidate: Branch | None,
    trail: Mapping[str, Any],
) -> str | None:
    """A model recommendation is recorded, never authoritative."""
    if not model_recommendation:
        return None
    suggested = model_recommendation.get("subject_branch_id")
    if suggested is None:
        return None
    if candidate is not None and suggested == candidate.branch_id:
        return f"model recommendation agrees with policy: {suggested}"
    audit = trail.get(suggested)
    if audit is not None and (
        not audit["hard_gates_passed"]
        or audit["forbidden_family"]
        or not audit["affordable"]
    ):
        return (
            f"model recommendation {suggested} ignored: it fails the "
            "deterministic hard gates and cannot override them"
        )
    return f"model recommendation {suggested} noted; policy selected otherwise"


def decide_after_episode(
    state: CampaignState,
    report: EpisodeRunReport,
    *,
    model_recommendation: Mapping[str, Any] | None = None,
    source_commit: str,
    id_factory: Callable[[str], str] = new_record_id,
    now_iso: Callable[[], str] = utc_now_iso,
) -> DecisionPlan:
    """Apply the ordered rule table to the replayed state after one episode."""
    campaign = state.require_campaign()
    if campaign.status is not CampaignStatus.ACTIVE:
        raise CampaignDecisionError(
            f"Decisions require an ACTIVE campaign; status is "
            f"{campaign.status.value}"
        )
    episode = state.episodes.get(report.episode_id)
    if episode is None:
        raise CampaignDecisionError(
            f"Episode {report.episode_id} is not in the replayed state"
        )
    branch = state.branches.get(episode.branch_id)
    if branch is None or branch.status is not BranchStatus.ACTIVE:
        raise CampaignDecisionError(
            "The decided episode must belong to the ACTIVE branch"
        )
    common = dict(
        model_recommendation=model_recommendation,
        id_factory=id_factory,
        now_iso=now_iso,
        source_commit=source_commit,
    )

    # R1 goal-complete
    if not state.unresolved_deliverables():
        decision = _make_decision(
            state,
            action=DecisionAction.CLOSE,
            rule="R1-goal-complete",
            reasons=("every mandatory deliverable is resolved",),
            policy_extra={},
            hard_gates_passed=True,
            subject_branch_id=None,
            alternatives=(),
            **common,
        )
        return DecisionPlan(
            rule="R1-goal-complete",
            decisions=(decision,),
            transitions=(
                PlannedTransition(
                    kind="campaign",
                    target_id=None,
                    new_status=CampaignStatus.COMPLETED.value,
                    reason="goal complete",
                    decision_id=decision.decision_id,
                ),
            ),
        )

    remaining = campaign.budget.remaining_after(state.spent)
    active_affordable = remaining.covers(branch.evidence_plan.estimated_cost)
    candidate, trail = select_promotion_candidate(state)

    # R2 campaign-exhausted
    if not active_affordable and candidate is None:
        decision = _make_decision(
            state,
            action=DecisionAction.CLOSE,
            rule="R2-campaign-exhausted",
            reasons=(
                "the remaining campaign budget covers no candidate's "
                "evidence plan",
            ),
            policy_extra={"candidates": trail},
            hard_gates_passed=True,
            subject_branch_id=None,
            alternatives=tuple(sorted(trail)),
            **common,
        )
        return DecisionPlan(
            rule="R2-campaign-exhausted",
            decisions=(decision,),
            transitions=(
                PlannedTransition(
                    kind="campaign",
                    target_id=None,
                    new_status=CampaignStatus.EXHAUSTED.value,
                    reason="budget exhausted",
                    decision_id=decision.decision_id,
                ),
            ),
        )

    # R3 refutation
    refuted = report.axes.evidence_outcome is (
        EvidenceOutcome.SCIENTIFIC_REFUTATION
    ) and any(
        claim_id in branch.claim_refs for claim_id in report.tested_claim_ids
    )
    if refuted:
        return _promotion_or_human_review(
            state,
            rule="R3-refutation",
            demoted_branch=branch,
            demotion_status=BranchStatus.REFUTED,
            demotion_reason=(
                f"claim(s) {list(report.tested_claim_ids)} scientifically "
                f"refuted by evidence {report.evidence_id}"
            ),
            **common,
        )

    # R4 branch-exhausted
    spent_on_branch = branch_spent(state, branch.branch_id)
    if spent_on_branch.cycles >= branch.budget.cycles:
        return _promotion_or_human_review(
            state,
            rule="R4-branch-exhausted",
            demoted_branch=branch,
            demotion_status=BranchStatus.EXHAUSTED,
            demotion_reason=(
                f"branch consumed its cycle budget "
                f"({spent_on_branch.cycles}/{branch.budget.cycles})"
            ),
            **common,
        )

    # R5 uninformative streak
    streak = uninformative_streak(state, branch.branch_id)
    if streak >= MAX_UNINFORMATIVE_STREAK:
        return _promotion_or_human_review(
            state,
            rule="R5-uninformative",
            demoted_branch=branch,
            demotion_status=BranchStatus.SUSPENDED,
            demotion_reason=(
                f"{streak} consecutive uninformative episodes "
                "(claim NOT_TESTED/INCONCLUSIVE)"
            ),
            **common,
        )

    # R6 affordability
    if not active_affordable:
        return _promotion_or_human_review(
            state,
            rule="R6-affordability",
            demoted_branch=branch,
            demotion_status=BranchStatus.SUSPENDED,
            demotion_reason=(
                "the remaining budget no longer covers the active branch's "
                "evidence plan"
            ),
            **common,
        )

    # R7 default: continue
    notes: tuple[str, ...] = ()
    recommendation_note = _recommendation_note(model_recommendation, branch, trail)
    if recommendation_note:
        notes = (recommendation_note,)
    decision = _make_decision(
        state,
        action=DecisionAction.CONTINUE,
        rule="R7-continue",
        reasons=(
            "evidence is informative and the next obligation is clear; "
            "the active branch continues",
        ),
        policy_extra={"uninformative_streak": streak},
        hard_gates_passed=True,
        subject_branch_id=branch.branch_id,
        alternatives=tuple(sorted(trail)),
        **common,
    )
    return DecisionPlan(
        rule="R7-continue", decisions=(decision,), transitions=(), notes=notes
    )


def select_initial_branch(
    store: CampaignStore,
    *,
    model_recommendation: Mapping[str, Any] | None = None,
    id_factory: Callable[[str], str] = new_record_id,
    now_iso: Callable[[], str] = utc_now_iso,
) -> DecisionPlan:
    """Bootstrap: SELECT and activate the best admissible branch."""
    state = store.replay().state
    campaign = state.require_campaign()
    if campaign.status is not CampaignStatus.ACTIVE:
        raise CampaignDecisionError(
            f"Selection requires an ACTIVE campaign; status is "
            f"{campaign.status.value}"
        )
    if state.active_branch_id() is not None:
        raise CampaignDecisionError(
            f"A branch is already ACTIVE: {state.active_branch_id()}"
        )
    candidate, trail = select_promotion_candidate(state)
    if candidate is None:
        raise CampaignDecisionError(
            "No admissible, affordable branch is available for selection"
        )
    decision = _make_decision(
        state,
        action=DecisionAction.SELECT,
        rule="R0-initial-selection",
        reasons=(
            f"initial selection of {candidate.branch_id} "
            f"({candidate.method_family}) by lexicographic priority",
        ),
        policy_extra={"candidates": trail},
        hard_gates_passed=True,
        subject_branch_id=candidate.branch_id,
        alternatives=tuple(
            branch_id
            for branch_id in sorted(trail)
            if branch_id != candidate.branch_id
        ),
        model_recommendation=model_recommendation,
        id_factory=id_factory,
        now_iso=now_iso,
        source_commit=store.source_commit,
    )
    plan = DecisionPlan(
        rule="R0-initial-selection",
        decisions=(decision,),
        transitions=(
            PlannedTransition(
                kind="branch",
                target_id=candidate.branch_id,
                new_status=BranchStatus.ACTIVE.value,
                reason="initial selection",
                decision_id=decision.decision_id,
            ),
        ),
    )
    apply_decision_plan(store, plan)
    return plan


def apply_decision_plan(store: CampaignStore, plan: DecisionPlan) -> int:
    """Append the plan's decisions and transitions to the ledger, in order."""
    appended = 0
    for decision in plan.decisions:
        store.append_event(
            event_type="DECISION_RECORDED",
            payload={"decision": decision.to_dict()},
            actor=Actor.SYSTEM,
            occurred_at=decision.created_at,
        )
        appended += 1
    for transition in plan.transitions:
        if transition.kind == "branch":
            payload: dict[str, Any] = {
                "branch_id": transition.target_id,
                "status": transition.new_status,
                "reason": transition.reason[:2000],
            }
            if transition.decision_id is not None:
                payload["decision_id"] = transition.decision_id
            store.append_event(
                event_type="BRANCH_STATUS_CHANGED",
                payload=payload,
                actor=Actor.SYSTEM,
                occurred_at=plan.decisions[0].created_at
                if plan.decisions
                else utc_now_iso(),
            )
        elif transition.kind == "campaign":
            store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={
                    "status": transition.new_status,
                    "reason": transition.reason[:2000],
                },
                actor=Actor.SYSTEM,
                occurred_at=plan.decisions[0].created_at
                if plan.decisions
                else utc_now_iso(),
            )
        else:
            raise CampaignDecisionError(
                f"Unknown transition kind: {transition.kind!r}"
            )
        appended += 1
    store.write_checkpoint()
    return appended


@dataclass(frozen=True)
class StepReport:
    episode: EpisodeRunReport
    plan: DecisionPlan
    events_appended: int


async def campaign_step(
    store: CampaignStore,
    *,
    cycle_runner: Callable[[dict], Any] | None = None,
    model_recommendation: Mapping[str, Any] | None = None,
    evidence_metadata: Mapping[str, Any] | None = None,
    cycle_timeout_seconds: int | None = None,
    id_factory: Callable[[str], str] = new_record_id,
    now_iso: Callable[[], str] = utc_now_iso,
) -> StepReport:
    """One atom of the campaign loop: episode -> decision -> ledger."""
    state = store.replay().state
    active = state.active_branch_id()
    if active is None:
        raise CampaignDecisionError(
            "No ACTIVE branch; run select_initial_branch first"
        )
    episode_report = await run_episode(
        store,
        active,
        cycle_runner=cycle_runner,
        cycle_timeout_seconds=cycle_timeout_seconds,
        evidence_metadata=evidence_metadata,
        id_factory=id_factory,
        now_iso=now_iso,
    )
    state = store.replay().state
    plan = decide_after_episode(
        state,
        episode_report,
        model_recommendation=model_recommendation,
        source_commit=store.source_commit,
        id_factory=id_factory,
        now_iso=now_iso,
    )
    appended = apply_decision_plan(store, plan)
    return StepReport(
        episode=episode_report, plan=plan, events_appended=appended
    )
