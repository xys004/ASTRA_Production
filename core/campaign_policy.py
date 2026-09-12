"""Deterministic campaign policy for ASTRA 2.0.

This module holds the event-replay reducer, the scientific and budget hard
gates, and the fail-closed transition enforcement demanded by the first-slice
contract.  It contains no learned selection and performs no model, network,
MCP, or remote calls.  The five status axes (operation, claim, evidence,
branch, goal coverage) are never synthesized into one status.

The append-only ledger is the source of truth; ``replay_events`` folds a
validated envelope sequence into a :class:`CampaignState` and refuses any
envelope whose semantics are invalid (unknown references, illegal transitions,
budget overruns, or a second ACTIVE branch).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from core.campaign_models import (
    BUDGET_DIMENSIONS,
    BRANCH_TERMINAL_STATUSES,
    Branch,
    BranchStatus,
    BudgetSnapshot,
    BudgetVector,
    Campaign,
    CampaignStatus,
    CAMPAIGN_TERMINAL_STATUSES,
    Claim,
    Decision,
    Episode,
    EventEnvelope,
    Evidence,
    EvidenceOutcome,
    GoalCoverage,
    assert_branch_transition,
    assert_campaign_transition,
    canonical_sha256,
)


class CampaignPolicyError(ValueError):
    """An event or gate evaluation failed fail-closed policy validation."""


# Branch end states that exhaust a claim/method combination for the
# duplicate-work hard gate.  MERGED work survives inside another branch and
# REJECTED work never ran, so neither blocks a new proposal.
_EXHAUSTED_BRANCH_STATUSES = frozenset(
    {BranchStatus.EXHAUSTED, BranchStatus.REFUTED, BranchStatus.CLOSED}
)


@dataclass
class CampaignState:
    """Derived state; the events ledger remains the authority."""

    campaign: Campaign | None = None
    branches: dict[str, Branch] = field(default_factory=dict)
    episodes: dict[str, Episode] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    spent: BudgetVector = field(default_factory=BudgetVector)
    resolved_deliverables: tuple[str, ...] = ()
    last_sequence: int = 0
    last_event_sha256: str | None = None

    def require_campaign(self) -> Campaign:
        if self.campaign is None:
            raise CampaignPolicyError("No campaign has been created yet")
        return self.campaign

    def active_branch_id(self) -> str | None:
        for branch_id, branch in self.branches.items():
            if branch.status is BranchStatus.ACTIVE:
                return branch_id
        return None

    def unresolved_deliverables(self) -> tuple[str, ...]:
        campaign = self.require_campaign()
        resolved = set(self.resolved_deliverables)
        return tuple(
            item for item in campaign.deliverables if item not in resolved
        )

    def goal_coverage(self) -> GoalCoverage:
        campaign = self.require_campaign()
        if not self.resolved_deliverables:
            return GoalCoverage.NONE
        if set(self.resolved_deliverables) == set(campaign.deliverables):
            return GoalCoverage.COMPLETE
        return GoalCoverage.PARTIAL

    def remaining_budget(self) -> BudgetVector:
        return self.require_campaign().budget.remaining_after(self.spent)

    def exhausted_method_families(self) -> tuple[str, ...]:
        """Method families closed for re-proposal (R4 negative prompting)."""
        return tuple(
            sorted(
                {
                    branch.method_family
                    for branch in self.branches.values()
                    if branch.status in _EXHAUSTED_BRANCH_STATUSES
                }
            )
        )

    def scientific_refutations(self, claim_id: str) -> tuple[str, ...]:
        """Evidence ids that scientifically refute ``claim_id``.

        Operational errors, numerical instability, invalid validators, and
        formalization failures never appear here: a traceback cannot refute a
        scientific claim.
        """
        return tuple(
            evidence_id
            for evidence_id, item in self.evidence.items()
            if claim_id in item.claim_ids and item.is_scientific_refutation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign": (
                self.campaign.to_dict() if self.campaign is not None else None
            ),
            "branches": {
                branch_id: branch.to_dict()
                for branch_id, branch in sorted(self.branches.items())
            },
            "episodes": {
                episode_id: episode.to_dict()
                for episode_id, episode in sorted(self.episodes.items())
            },
            "claims": {
                claim_id: claim.to_dict()
                for claim_id, claim in sorted(self.claims.items())
            },
            "evidence": {
                evidence_id: item.to_dict()
                for evidence_id, item in sorted(self.evidence.items())
            },
            "decisions": {
                decision_id: decision.to_dict()
                for decision_id, decision in sorted(self.decisions.items())
            },
            "spent": self.spent.to_dict(),
            "resolved_deliverables": list(self.resolved_deliverables),
            "last_sequence": self.last_sequence,
            "last_event_sha256": self.last_event_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CampaignState":
        campaign_data = data.get("campaign")
        state = cls(
            campaign=(
                Campaign.from_dict(campaign_data)
                if campaign_data is not None
                else None
            ),
            branches={
                branch_id: Branch.from_dict(item)
                for branch_id, item in dict(data["branches"]).items()
            },
            episodes={
                episode_id: Episode.from_dict(item)
                for episode_id, item in dict(data["episodes"]).items()
            },
            claims={
                claim_id: Claim.from_dict(item)
                for claim_id, item in dict(data["claims"]).items()
            },
            evidence={
                evidence_id: Evidence.from_dict(item)
                for evidence_id, item in dict(data["evidence"]).items()
            },
            decisions={
                decision_id: Decision.from_dict(item)
                for decision_id, item in dict(data["decisions"]).items()
            },
            spent=BudgetVector.from_dict(data["spent"]),
            resolved_deliverables=tuple(data["resolved_deliverables"]),
            last_sequence=int(data["last_sequence"]),
            last_event_sha256=data["last_event_sha256"],
        )
        return state

    def state_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


def _require_payload_keys(
    payload: Mapping[str, Any], required: set[str], optional: set[str], name: str
) -> None:
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required - optional)
    if missing or unknown:
        raise CampaignPolicyError(
            f"{name} payload invalid: missing={missing}, unknown={unknown}"
        )


def _require_active_campaign(state: CampaignState, action: str) -> Campaign:
    campaign = state.require_campaign()
    if campaign.status is not CampaignStatus.ACTIVE:
        raise CampaignPolicyError(
            f"{action} requires an ACTIVE campaign; "
            f"status is {campaign.status.value}"
        )
    return campaign


def _apply_campaign_created(state: CampaignState, event: EventEnvelope) -> None:
    if state.campaign is not None:
        raise CampaignPolicyError("CAMPAIGN_CREATED may only appear once")
    _require_payload_keys(
        event.payload, {"campaign"}, set(), "CAMPAIGN_CREATED"
    )
    campaign = Campaign.from_dict(event.payload["campaign"])
    if campaign.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "CAMPAIGN_CREATED campaign_id does not match the envelope"
        )
    if campaign.status is not CampaignStatus.DRAFT:
        raise CampaignPolicyError("A campaign must be created in DRAFT status")
    if campaign.goal_coverage is not GoalCoverage.NONE:
        raise CampaignPolicyError("A new campaign must start with NONE coverage")
    state.campaign = campaign


def _apply_campaign_status_changed(
    state: CampaignState, event: EventEnvelope
) -> None:
    campaign = state.require_campaign()
    _require_payload_keys(
        event.payload, {"status"}, {"reason"}, "CAMPAIGN_STATUS_CHANGED"
    )
    try:
        new_status = CampaignStatus(event.payload["status"])
    except ValueError as exc:
        raise CampaignPolicyError(
            f"Unknown campaign status: {event.payload['status']!r}"
        ) from exc
    try:
        assert_campaign_transition(campaign.status, new_status)
    except ValueError as exc:
        raise CampaignPolicyError(str(exc)) from exc
    if new_status is CampaignStatus.COMPLETED and state.unresolved_deliverables():
        raise CampaignPolicyError(
            "The campaign cannot be COMPLETED while mandatory deliverables "
            f"remain unresolved: {list(state.unresolved_deliverables())}"
        )
    state.campaign = campaign.with_status(new_status)


def _apply_deliverable_resolved(
    state: CampaignState, event: EventEnvelope
) -> None:
    campaign = _require_active_campaign(state, "DELIVERABLE_RESOLVED")
    _require_payload_keys(
        event.payload, {"deliverable"}, {"evidence_id"}, "DELIVERABLE_RESOLVED"
    )
    deliverable = event.payload["deliverable"]
    if deliverable not in campaign.deliverables:
        raise CampaignPolicyError(
            f"Unknown campaign deliverable: {deliverable!r}"
        )
    if deliverable in state.resolved_deliverables:
        raise CampaignPolicyError(
            f"Deliverable already resolved: {deliverable!r}"
        )
    evidence_id = event.payload.get("evidence_id")
    if evidence_id is not None and evidence_id not in state.evidence:
        raise CampaignPolicyError(
            f"DELIVERABLE_RESOLVED references unknown evidence: {evidence_id!r}"
        )
    state.resolved_deliverables = (*state.resolved_deliverables, deliverable)


def _apply_branch_created(state: CampaignState, event: EventEnvelope) -> None:
    campaign = state.require_campaign()
    if campaign.status in CAMPAIGN_TERMINAL_STATUSES:
        raise CampaignPolicyError(
            "Branches cannot be created in a terminal campaign"
        )
    _require_payload_keys(event.payload, {"branch"}, set(), "BRANCH_CREATED")
    branch = Branch.from_dict(event.payload["branch"])
    if branch.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "BRANCH_CREATED campaign_id does not match the envelope"
        )
    if branch.branch_id in state.branches:
        raise CampaignPolicyError(f"Duplicate branch id: {branch.branch_id}")
    if branch.status is not BranchStatus.PROPOSED:
        raise CampaignPolicyError("A branch must be created in PROPOSED status")
    if branch.decision_history:
        raise CampaignPolicyError(
            "A new branch cannot carry a prior decision history"
        )
    if branch.parent_branch_id is not None and (
        branch.parent_branch_id not in state.branches
    ):
        raise CampaignPolicyError(
            f"Unknown parent branch: {branch.parent_branch_id}"
        )
    if branch.parent_episode_id is not None and (
        branch.parent_episode_id not in state.episodes
    ):
        raise CampaignPolicyError(
            f"Unknown parent episode: {branch.parent_episode_id}"
        )
    unknown_deliverables = [
        item
        for item in branch.deliverable_refs
        if item not in campaign.deliverables
    ]
    if unknown_deliverables:
        raise CampaignPolicyError(
            f"Branch references unknown deliverables: {unknown_deliverables}"
        )
    unknown_claims = [
        item for item in branch.claim_refs if item not in state.claims
    ]
    if unknown_claims:
        raise CampaignPolicyError(
            f"Branch references unknown claims: {unknown_claims}"
        )
    state.branches[branch.branch_id] = branch


def _apply_branch_status_changed(
    state: CampaignState, event: EventEnvelope
) -> None:
    state.require_campaign()
    _require_payload_keys(
        event.payload,
        {"branch_id", "status"},
        {"decision_id", "reason"},
        "BRANCH_STATUS_CHANGED",
    )
    branch_id = event.payload["branch_id"]
    branch = state.branches.get(branch_id)
    if branch is None:
        raise CampaignPolicyError(f"Unknown branch: {branch_id!r}")
    try:
        new_status = BranchStatus(event.payload["status"])
    except ValueError as exc:
        raise CampaignPolicyError(
            f"Unknown branch status: {event.payload['status']!r}"
        ) from exc
    try:
        assert_branch_transition(branch.status, new_status)
    except ValueError as exc:
        raise CampaignPolicyError(str(exc)) from exc
    if new_status is BranchStatus.ACTIVE:
        _require_active_campaign(state, "Branch activation")
        active = state.active_branch_id()
        if active is not None and active != branch_id:
            raise CampaignPolicyError(
                f"Only one branch may be ACTIVE; {active} is already active"
            )
    decision_id = event.payload.get("decision_id")
    if decision_id is not None and decision_id not in state.decisions:
        raise CampaignPolicyError(
            f"BRANCH_STATUS_CHANGED references unknown decision: {decision_id!r}"
        )
    try:
        state.branches[branch_id] = branch.with_status(
            new_status, decision_id=decision_id
        )
    except ValueError as exc:
        raise CampaignPolicyError(str(exc)) from exc


def _apply_claim_recorded(state: CampaignState, event: EventEnvelope) -> None:
    campaign = state.require_campaign()
    if campaign.status in CAMPAIGN_TERMINAL_STATUSES:
        raise CampaignPolicyError(
            "Claims cannot be recorded in a terminal campaign"
        )
    _require_payload_keys(
        event.payload, {"claim"}, {"branch_id"}, "CLAIM_RECORDED"
    )
    claim = Claim.from_dict(event.payload["claim"])
    if claim.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "CLAIM_RECORDED campaign_id does not match the envelope"
        )
    if claim.claim_id in state.claims:
        raise CampaignPolicyError(f"Duplicate claim id: {claim.claim_id}")
    branch_id = event.payload.get("branch_id")
    if branch_id is not None:
        branch = state.branches.get(branch_id)
        if branch is None:
            raise CampaignPolicyError(f"Unknown branch: {branch_id!r}")
        if branch.status in BRANCH_TERMINAL_STATUSES:
            raise CampaignPolicyError(
                f"Claims cannot be attached to terminal branch {branch_id}"
            )
    state.claims[claim.claim_id] = claim
    if branch_id is not None and claim.claim_id not in (
        state.branches[branch_id].claim_refs
    ):
        branch = state.branches[branch_id]
        state.branches[branch_id] = replace(
            branch, claim_refs=(*branch.claim_refs, claim.claim_id)
        )


def _apply_evidence_recorded(state: CampaignState, event: EventEnvelope) -> None:
    campaign = _require_active_campaign(state, "EVIDENCE_RECORDED")
    _require_payload_keys(event.payload, {"evidence"}, set(), "EVIDENCE_RECORDED")
    evidence = Evidence.from_dict(event.payload["evidence"])
    if evidence.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "EVIDENCE_RECORDED campaign_id does not match the envelope"
        )
    if evidence.evidence_id in state.evidence:
        raise CampaignPolicyError(
            f"Duplicate evidence id: {evidence.evidence_id}"
        )
    unknown_claims = [
        item for item in evidence.claim_ids if item not in state.claims
    ]
    if unknown_claims:
        raise CampaignPolicyError(
            f"Evidence references unknown claims: {unknown_claims}"
        )
    unknown_links = [
        item
        for item in evidence.independence_links
        if item not in state.evidence
    ]
    if unknown_links:
        raise CampaignPolicyError(
            f"Evidence references unknown independence links: {unknown_links}"
        )
    if evidence.kind not in campaign.allowed_evidence_classes:
        raise CampaignPolicyError(
            f"Evidence kind {evidence.kind.value} is not allowed by the "
            "campaign's evidence classes"
        )
    state.evidence[evidence.evidence_id] = evidence


def _apply_episode_recorded(state: CampaignState, event: EventEnvelope) -> None:
    _require_active_campaign(state, "EPISODE_RECORDED")
    _require_payload_keys(event.payload, {"episode"}, set(), "EPISODE_RECORDED")
    episode = Episode.from_dict(event.payload["episode"])
    if episode.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "EPISODE_RECORDED campaign_id does not match the envelope"
        )
    if episode.episode_id in state.episodes:
        raise CampaignPolicyError(f"Duplicate episode id: {episode.episode_id}")
    branch = state.branches.get(episode.branch_id)
    if branch is None:
        raise CampaignPolicyError(f"Unknown branch: {episode.branch_id!r}")
    if branch.status is not BranchStatus.ACTIVE:
        raise CampaignPolicyError(
            f"Episodes may only be recorded on the ACTIVE branch; "
            f"{episode.branch_id} is {branch.status.value}"
        )
    if episode.branch_status is not branch.status:
        raise CampaignPolicyError(
            "Episode branch_status axis does not match the branch record"
        )
    unknown_claims = [
        item for item in episode.claim_refs if item not in state.claims
    ]
    if unknown_claims:
        raise CampaignPolicyError(
            f"Episode references unknown claims: {unknown_claims}"
        )
    unknown_evidence = [
        item for item in episode.evidence_refs if item not in state.evidence
    ]
    if unknown_evidence:
        raise CampaignPolicyError(
            f"Episode references unknown evidence: {unknown_evidence}"
        )
    state.episodes[episode.episode_id] = episode


def _apply_decision_recorded(state: CampaignState, event: EventEnvelope) -> None:
    campaign = state.require_campaign()
    if campaign.status in CAMPAIGN_TERMINAL_STATUSES:
        raise CampaignPolicyError(
            "Decisions cannot be recorded in a terminal campaign"
        )
    _require_payload_keys(event.payload, {"decision"}, set(), "DECISION_RECORDED")
    decision = Decision.from_dict(event.payload["decision"])
    if decision.campaign_id != event.campaign_id:
        raise CampaignPolicyError(
            "DECISION_RECORDED campaign_id does not match the envelope"
        )
    if decision.decision_id in state.decisions:
        raise CampaignPolicyError(
            f"Duplicate decision id: {decision.decision_id}"
        )
    if decision.subject_branch_id is not None and (
        decision.subject_branch_id not in state.branches
    ):
        raise CampaignPolicyError(
            f"Decision references unknown branch: {decision.subject_branch_id}"
        )
    unknown_alternatives = [
        item
        for item in decision.alternatives_considered
        if item not in state.branches
    ]
    if unknown_alternatives:
        raise CampaignPolicyError(
            f"Decision references unknown alternatives: {unknown_alternatives}"
        )
    expected = BudgetSnapshot(limits=campaign.budget, spent=state.spent)
    if decision.budget_snapshot != expected:
        raise CampaignPolicyError(
            "Decision budget snapshot does not match the replayed campaign "
            "budget state"
        )
    state.decisions[decision.decision_id] = decision


def _apply_budget_charged(state: CampaignState, event: EventEnvelope) -> None:
    campaign = _require_active_campaign(state, "BUDGET_CHARGED")
    _require_payload_keys(
        event.payload, {"dimension", "amount"}, {"reason"}, "BUDGET_CHARGED"
    )
    dimension = event.payload["dimension"]
    amount = event.payload["amount"]
    if dimension not in BUDGET_DIMENSIONS:
        raise CampaignPolicyError(f"Unknown budget dimension: {dimension!r}")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise CampaignPolicyError(
            f"Budget charge must be a positive integer, got {amount!r}"
        )
    try:
        new_spent = state.spent.charge(dimension, amount)
    except ValueError as exc:
        raise CampaignPolicyError(str(exc)) from exc
    if not campaign.budget.covers(new_spent):
        limit = getattr(campaign.budget, dimension)
        raise CampaignPolicyError(
            f"Budget charge exceeds the campaign {dimension} limit "
            f"({getattr(state.spent, dimension)}+{amount} > {limit})"
        )
    state.spent = new_spent


_EVENT_APPLIERS = {
    "CAMPAIGN_CREATED": _apply_campaign_created,
    "CAMPAIGN_STATUS_CHANGED": _apply_campaign_status_changed,
    "DELIVERABLE_RESOLVED": _apply_deliverable_resolved,
    "BRANCH_CREATED": _apply_branch_created,
    "BRANCH_STATUS_CHANGED": _apply_branch_status_changed,
    "CLAIM_RECORDED": _apply_claim_recorded,
    "EVIDENCE_RECORDED": _apply_evidence_recorded,
    "EPISODE_RECORDED": _apply_episode_recorded,
    "DECISION_RECORDED": _apply_decision_recorded,
    "BUDGET_CHARGED": _apply_budget_charged,
}


def apply_event(state: CampaignState, event: EventEnvelope) -> CampaignState:
    """Apply one validated envelope to the state, failing closed."""
    if not isinstance(event, EventEnvelope):
        raise CampaignPolicyError("apply_event requires an EventEnvelope")
    if event.sequence != state.last_sequence + 1:
        raise CampaignPolicyError(
            f"Non-contiguous sequence: expected {state.last_sequence + 1}, "
            f"got {event.sequence}"
        )
    if event.previous_event_sha256 != state.last_event_sha256:
        raise CampaignPolicyError(
            f"Hash chain break at sequence {event.sequence}: expected previous "
            f"{state.last_event_sha256!r}, got {event.previous_event_sha256!r}"
        )
    if state.campaign is not None and (
        event.campaign_id != state.campaign.campaign_id
    ):
        raise CampaignPolicyError(
            f"Event campaign {event.campaign_id} does not match the "
            f"campaign {state.campaign.campaign_id}"
        )
    if state.campaign is None and event.event_type != "CAMPAIGN_CREATED":
        raise CampaignPolicyError(
            "The first event of a ledger must be CAMPAIGN_CREATED"
        )
    if (
        state.campaign is not None
        and state.campaign.status in CAMPAIGN_TERMINAL_STATUSES
    ):
        raise CampaignPolicyError(
            "Terminal campaign states are immutable; no further events are "
            "accepted"
        )
    applier = _EVENT_APPLIERS.get(event.event_type)
    if applier is None:
        raise CampaignPolicyError(f"Unknown event type: {event.event_type!r}")
    applier(state, event)
    state.last_sequence = event.sequence
    state.last_event_sha256 = event.event_sha256
    return state


def replay_events(events: Iterable[EventEnvelope]) -> CampaignState:
    """Deterministically fold envelopes into a validated state."""
    state = CampaignState()
    seen_event_ids: set[str] = set()
    for event in events:
        if event.event_id in seen_event_ids:
            raise CampaignPolicyError(f"Duplicate event id: {event.event_id}")
        seen_event_ids.add(event.event_id)
        apply_event(state, event)
    return state


# ---------------------------------------------------------------------------
# Hard admissibility gates
# ---------------------------------------------------------------------------

HARD_GATES = (
    "relevant_deliverable",
    "falsifiable_claim",
    "explicit_scope",
    "feasible_evidence_plan",
    "no_exhausted_duplicate",
    "sufficient_budget",
)


@dataclass(frozen=True)
class AdmissibilityResult:
    """Per-gate results; a model recommendation can never override them."""

    gates: dict[str, bool]
    failed_gates: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failed_gates

    def to_dict(self) -> dict[str, Any]:
        return {
            "hard_gates_passed": self.passed,
            "gates": dict(self.gates),
            "failed_gates": list(self.failed_gates),
        }


def evaluate_branch_admissibility(
    state: CampaignState, branch: Branch
) -> AdmissibilityResult:
    """Evaluate the six deterministic hard gates for one branch."""
    campaign = state.require_campaign()
    if branch.campaign_id != campaign.campaign_id:
        raise CampaignPolicyError(
            "Branch belongs to a different campaign than the state"
        )
    gates: dict[str, bool] = {}

    unresolved = set(state.unresolved_deliverables())
    gates["relevant_deliverable"] = any(
        item in unresolved for item in branch.deliverable_refs
    )

    claims = [
        state.claims[claim_id]
        for claim_id in branch.claim_refs
        if claim_id in state.claims
    ]
    gates["falsifiable_claim"] = bool(claims) and len(claims) == len(
        branch.claim_refs
    )

    gates["explicit_scope"] = bool(claims) and all(
        claim.domain and claim.quantifiers for claim in claims
    )

    plan = branch.evidence_plan
    gates["feasible_evidence_plan"] = (
        plan.kind in campaign.allowed_evidence_classes
        and plan.estimated_cost.cycles >= 1
    )

    own_fingerprints = {claim.fingerprint() for claim in claims}
    duplicate = False
    for other in state.branches.values():
        if other.branch_id == branch.branch_id:
            continue
        if other.status not in _EXHAUSTED_BRANCH_STATUSES:
            continue
        if other.method_family != branch.method_family:
            continue
        other_fingerprints = {
            state.claims[claim_id].fingerprint()
            for claim_id in other.claim_refs
            if claim_id in state.claims
        }
        if own_fingerprints & other_fingerprints:
            duplicate = True
            break
    gates["no_exhausted_duplicate"] = not duplicate

    remaining = state.remaining_budget()
    gates["sufficient_budget"] = remaining.covers(plan.estimated_cost)

    failed = tuple(name for name in HARD_GATES if not gates[name])
    return AdmissibilityResult(gates=gates, failed_gates=failed)
