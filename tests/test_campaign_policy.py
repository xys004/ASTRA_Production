"""Deterministic replay, fail-closed transitions, budgets, and hard gates."""
import unittest

from core.campaign_models import (
    Actor,
    AssumptionDelta,
    Branch,
    BranchStatus,
    BudgetSnapshot,
    BudgetVector,
    Campaign,
    Claim,
    ClaimStatus,
    ClaimType,
    Decision,
    DecisionAction,
    Episode,
    EventEnvelope,
    Evidence,
    EvidenceKind,
    EvidenceOutcome,
    EvidencePlan,
    EvidenceStrength,
    GoalCoverage,
    OperationStatus,
    PriorityVector,
)
from core.campaign_policy import (
    CampaignPolicyError,
    CampaignState,
    apply_event,
    evaluate_branch_admissibility,
    replay_events,
)

COMMIT = "a" * 40
TS = "2026-08-12T00:00:00Z"
SHA = "b" * 64
CAMPAIGN_ID = "cmp_policy-001"


def make_budget(**overrides) -> BudgetVector:
    base = dict(
        cycles=10,
        model_calls=40,
        wall_seconds=3600,
        execution_seconds=1800,
        human_interventions=2,
        remote_jobs=4,
    )
    base.update(overrides)
    return BudgetVector(**base)


def make_campaign(**overrides) -> Campaign:
    base = dict(
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        objective="Decide whether the bounded identity family holds.",
        success_definition="Every mandatory deliverable has credible evidence.",
        deliverables=("identity proof", "counterexample report"),
        frozen_resources={"brief.md": SHA},
        allowed_evidence_classes=(EvidenceKind.SYMBOLIC,),
        budget=make_budget(),
    )
    base.update(overrides)
    return Campaign(**base)


def make_plan(**overrides) -> EvidencePlan:
    base = dict(
        description="Symbolic residual check.",
        kind=EvidenceKind.SYMBOLIC,
        estimated_cost=make_budget(
            cycles=1,
            model_calls=4,
            wall_seconds=600,
            execution_seconds=120,
            human_interventions=0,
            remote_jobs=0,
        ),
    )
    base.update(overrides)
    return EvidencePlan(**base)


def make_claim(claim_id: str = "clm_policy-001", **overrides) -> Claim:
    base = dict(
        claim_id=claim_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        statement="For all real x, x**2 >= 0.",
        claim_type=ClaimType.UNIVERSAL,
        domain="real analysis",
        scope="all real x",
        quantifiers=("forall x in R",),
        assumptions=("standard ordering of R",),
    )
    base.update(overrides)
    return Claim(**base)


def make_branch(branch_id: str = "brn_policy-001", **overrides) -> Branch:
    base = dict(
        branch_id=branch_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        direction="Exact residual simplification.",
        method_family="symbolic_residual",
        material_difference="Exact simplification instead of sampling.",
        assumption_delta=AssumptionDelta(),
        evidence_plan=make_plan(),
        priority_vector=PriorityVector(
            information_gain=0.8,
            evidence_strength=0.2,
            methodological_independence=0.9,
            goal_advancement=0.7,
            estimated_cost=0.3,
            instability_risk=0.1,
        ),
        budget=make_budget(cycles=4),
        deliverable_refs=("identity proof",),
        claim_refs=("clm_policy-001",),
    )
    base.update(overrides)
    return Branch(**base)


def make_evidence(evidence_id: str = "evd_policy-001", **overrides) -> Evidence:
    base = dict(
        evidence_id=evidence_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        claim_ids=("clm_policy-001",),
        kind=EvidenceKind.SYMBOLIC,
        strength=EvidenceStrength.SCOPED,
        scope="bounded symbolic residual",
        engine="sympy",
        outcome=EvidenceOutcome.SUPPORTS,
        artifact_hashes={"artifacts/residual.py": SHA},
    )
    base.update(overrides)
    return Evidence(**base)


class LedgerBuilder:
    """Chained, validated envelopes without touching the filesystem."""

    def __init__(self, campaign_id: str = CAMPAIGN_ID):
        self.campaign_id = campaign_id
        self.events: list[EventEnvelope] = []

    def add(self, event_type: str, payload: dict, *, actor=Actor.SYSTEM,
            event_id: str | None = None) -> EventEnvelope:
        sequence = len(self.events) + 1
        envelope = EventEnvelope.create(
            event_id=event_id or f"evt_p{sequence:04d}",
            campaign_id=self.campaign_id,
            sequence=sequence,
            event_type=event_type,
            occurred_at=TS,
            source_commit=COMMIT,
            actor=actor,
            payload=payload,
            previous_event_sha256=(
                self.events[-1].event_sha256 if self.events else None
            ),
        )
        self.events.append(envelope)
        return envelope

    def state(self) -> CampaignState:
        return replay_events(self.events)


def seeded_builder() -> LedgerBuilder:
    builder = LedgerBuilder()
    builder.add("CAMPAIGN_CREATED", {"campaign": make_campaign().to_dict()})
    builder.add("CAMPAIGN_STATUS_CHANGED", {"status": "ACTIVE"})
    builder.add("CLAIM_RECORDED", {"claim": make_claim().to_dict()})
    builder.add("BRANCH_CREATED", {"branch": make_branch().to_dict()})
    return builder


class ReplayReducerTests(unittest.TestCase):
    def test_full_campaign_lifecycle_replays(self):
        builder = seeded_builder()
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ADMISSIBLE"},
        )
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ACTIVE"},
        )
        builder.add(
            "BUDGET_CHARGED",
            {"dimension": "cycles", "amount": 1, "reason": "episode"},
        )
        builder.add(
            "EVIDENCE_RECORDED", {"evidence": make_evidence().to_dict()}
        )
        builder.add(
            "EPISODE_RECORDED",
            {
                "episode": Episode(
                    episode_id="epi_policy-001",
                    campaign_id=CAMPAIGN_ID,
                    branch_id="brn_policy-001",
                    created_at=TS,
                    source_commit=COMMIT,
                    inputs={"direction": "check the residual"},
                    providers={"translator": "claude_cli"},
                    actual_models={"translator": "claude-opus-4-8"},
                    budget=make_budget(cycles=1, model_calls=5),
                    timings={"translate": 12.5},
                    operation_status=OperationStatus.COMPLETED,
                    claim_status=ClaimStatus.SUPPORTED,
                    branch_status=BranchStatus.ACTIVE,
                    goal_coverage=GoalCoverage.PARTIAL,
                    claim_refs=("clm_policy-001",),
                    evidence_refs=("evd_policy-001",),
                ).to_dict()
            },
        )
        state = builder.state()
        self.assertEqual(state.spent.cycles, 1)
        self.assertEqual(state.active_branch_id(), "brn_policy-001")
        self.assertEqual(
            state.unresolved_deliverables(),
            ("identity proof", "counterexample report"),
        )
        self.assertEqual(state.goal_coverage(), GoalCoverage.NONE)
        self.assertEqual(state.last_sequence, 9)

        builder.add(
            "DELIVERABLE_RESOLVED",
            {"deliverable": "identity proof", "evidence_id": "evd_policy-001"},
        )
        state = builder.state()
        self.assertEqual(state.goal_coverage(), GoalCoverage.PARTIAL)

    def test_first_event_must_be_campaign_created(self):
        builder = LedgerBuilder()
        builder.add("CAMPAIGN_STATUS_CHANGED", {"status": "ACTIVE"})
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_campaign_created_may_only_appear_once(self):
        builder = seeded_builder()
        builder.add(
            "CAMPAIGN_CREATED", {"campaign": make_campaign().to_dict()}
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_duplicate_event_id_fails_closed(self):
        builder = seeded_builder()
        builder.add(
            "BUDGET_CHARGED",
            {"dimension": "cycles", "amount": 1},
            event_id="evt_p0004",
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_hash_chain_break_is_detected(self):
        builder = seeded_builder()
        state = replay_events(builder.events[:3])
        orphan = EventEnvelope.create(
            event_id="evt_p9999",
            campaign_id=CAMPAIGN_ID,
            sequence=4,
            event_type="BRANCH_CREATED",
            occurred_at=TS,
            source_commit=COMMIT,
            actor=Actor.SYSTEM,
            payload={"branch": make_branch().to_dict()},
            previous_event_sha256=SHA,  # wrong link
        )
        with self.assertRaises(CampaignPolicyError):
            apply_event(state, orphan)

    def test_terminal_campaign_accepts_no_further_events(self):
        builder = seeded_builder()
        builder.add("CAMPAIGN_STATUS_CHANGED", {"status": "CANCELLED"})
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 1})
        with self.assertRaises(CampaignPolicyError):
            builder.state()


class TransitionAndInvariantTests(unittest.TestCase):
    def test_invalid_branch_transition_fails_closed(self):
        builder = seeded_builder()
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ACTIVE"},
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_single_active_branch_is_enforced(self):
        builder = seeded_builder()
        second_claim = make_claim(
            "clm_policy-002", statement="For all real x, x**4 >= 0."
        )
        builder.add("CLAIM_RECORDED", {"claim": second_claim.to_dict()})
        builder.add(
            "BRANCH_CREATED",
            {
                "branch": make_branch(
                    "brn_policy-002",
                    method_family="numerical_scan",
                    claim_refs=("clm_policy-002",),
                ).to_dict()
            },
        )
        for branch_id in ("brn_policy-001", "brn_policy-002"):
            builder.add(
                "BRANCH_STATUS_CHANGED",
                {"branch_id": branch_id, "status": "ADMISSIBLE"},
            )
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ACTIVE"},
        )
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-002", "status": "ACTIVE"},
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_branch_activation_requires_an_active_campaign(self):
        builder = LedgerBuilder()
        builder.add("CAMPAIGN_CREATED", {"campaign": make_campaign().to_dict()})
        builder.add("CLAIM_RECORDED", {"claim": make_claim().to_dict()})
        builder.add("BRANCH_CREATED", {"branch": make_branch().to_dict()})
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ADMISSIBLE"},
        )
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ACTIVE"},
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_campaign_cannot_complete_with_unresolved_deliverables(self):
        builder = seeded_builder()
        builder.add("CAMPAIGN_STATUS_CHANGED", {"status": "COMPLETED"})
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_campaign_completes_once_deliverables_are_resolved(self):
        builder = seeded_builder()
        builder.add(
            "DELIVERABLE_RESOLVED", {"deliverable": "identity proof"}
        )
        builder.add(
            "DELIVERABLE_RESOLVED", {"deliverable": "counterexample report"}
        )
        builder.add("CAMPAIGN_STATUS_CHANGED", {"status": "COMPLETED"})
        state = builder.state()
        self.assertEqual(state.goal_coverage(), GoalCoverage.COMPLETE)

    def test_episode_requires_the_active_branch(self):
        builder = seeded_builder()
        builder.add(
            "EPISODE_RECORDED",
            {
                "episode": Episode(
                    episode_id="epi_policy-002",
                    campaign_id=CAMPAIGN_ID,
                    branch_id="brn_policy-001",  # still PROPOSED
                    created_at=TS,
                    source_commit=COMMIT,
                    inputs={},
                    providers={},
                    actual_models={},
                    budget=make_budget(cycles=1),
                    timings={},
                    operation_status=OperationStatus.COMPLETED,
                    claim_status=ClaimStatus.NOT_TESTED,
                    branch_status=BranchStatus.PROPOSED,
                    goal_coverage=GoalCoverage.NONE,
                ).to_dict()
            },
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()


class BudgetTests(unittest.TestCase):
    def test_budget_charges_accumulate_per_dimension(self):
        builder = seeded_builder()
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 3})
        builder.add("BUDGET_CHARGED", {"dimension": "model_calls", "amount": 7})
        state = builder.state()
        self.assertEqual(state.spent.cycles, 3)
        self.assertEqual(state.spent.model_calls, 7)
        self.assertEqual(state.remaining_budget().cycles, 7)

    def test_budget_overrun_fails_closed(self):
        builder = seeded_builder()
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 11})
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_unknown_dimension_and_bad_amount_fail_closed(self):
        for payload in (
            {"dimension": "quantum_leaps", "amount": 1},
            {"dimension": "cycles", "amount": 0},
            {"dimension": "cycles", "amount": -2},
            {"dimension": "cycles", "amount": True},
        ):
            with self.subTest(payload=payload):
                builder = seeded_builder()
                builder.add("BUDGET_CHARGED", payload)
                with self.assertRaises(CampaignPolicyError):
                    builder.state()

    def test_decision_snapshot_must_match_replayed_budget(self):
        builder = seeded_builder()
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 2})
        stale = Decision(
            decision_id="dec_policy-001",
            campaign_id=CAMPAIGN_ID,
            created_at=TS,
            source_commit=COMMIT,
            action=DecisionAction.CONTINUE,
            policy_result={"hard_gates_passed": True},
            reasons=("keep going",),
            budget_snapshot=BudgetSnapshot(
                limits=make_budget(), spent=BudgetVector()
            ),
            subject_branch_id="brn_policy-001",
        )
        builder.add("DECISION_RECORDED", {"decision": stale.to_dict()})
        with self.assertRaises(CampaignPolicyError):
            builder.state()

        builder = seeded_builder()
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 2})
        exact = Decision(
            decision_id="dec_policy-001",
            campaign_id=CAMPAIGN_ID,
            created_at=TS,
            source_commit=COMMIT,
            action=DecisionAction.CONTINUE,
            policy_result={"hard_gates_passed": True},
            reasons=("keep going",),
            budget_snapshot=BudgetSnapshot(
                limits=make_budget(), spent=BudgetVector(cycles=2)
            ),
            subject_branch_id="brn_policy-001",
        )
        builder.add("DECISION_RECORDED", {"decision": exact.to_dict()})
        state = builder.state()
        self.assertIn("dec_policy-001", state.decisions)


class ReferenceValidationTests(unittest.TestCase):
    def test_evidence_requires_known_claims(self):
        builder = seeded_builder()
        builder.add(
            "EVIDENCE_RECORDED",
            {
                "evidence": make_evidence(
                    claim_ids=("clm_policy-404",)
                ).to_dict()
            },
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_evidence_kind_must_be_allowed_by_the_campaign(self):
        builder = seeded_builder()
        builder.add(
            "EVIDENCE_RECORDED",
            {
                "evidence": make_evidence(
                    kind=EvidenceKind.LITERATURE,
                    metadata={"source": "arXiv:2608.00001"},
                ).to_dict()
            },
        )
        with self.assertRaises(CampaignPolicyError):
            builder.state()

    def test_operational_error_evidence_never_refutes(self):
        builder = seeded_builder()
        builder.add(
            "EVIDENCE_RECORDED",
            {
                "evidence": make_evidence(
                    outcome=EvidenceOutcome.OPERATIONAL_ERROR
                ).to_dict()
            },
        )
        builder.add(
            "EVIDENCE_RECORDED",
            {
                "evidence": make_evidence(
                    "evd_policy-002",
                    outcome=EvidenceOutcome.SCIENTIFIC_REFUTATION,
                ).to_dict()
            },
        )
        state = builder.state()
        self.assertEqual(
            state.scientific_refutations("clm_policy-001"),
            ("evd_policy-002",),
        )


class AdmissibilityGateTests(unittest.TestCase):
    def activated_builder(self) -> LedgerBuilder:
        builder = seeded_builder()
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ADMISSIBLE"},
        )
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "ACTIVE"},
        )
        return builder

    def test_all_hard_gates_pass_for_a_sound_branch(self):
        state = seeded_builder().state()
        result = evaluate_branch_admissibility(
            state, state.branches["brn_policy-001"]
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.failed_gates, ())
        self.assertTrue(result.to_dict()["hard_gates_passed"])

    def test_resolved_deliverable_fails_the_relevance_gate(self):
        builder = seeded_builder()
        builder.add(
            "DELIVERABLE_RESOLVED", {"deliverable": "identity proof"}
        )
        state = builder.state()
        result = evaluate_branch_admissibility(
            state, state.branches["brn_policy-001"]
        )
        self.assertIn("relevant_deliverable", result.failed_gates)

    def test_missing_claims_fail_the_falsifiability_gate(self):
        state = seeded_builder().state()
        unclaimed = make_branch("brn_policy-003", claim_refs=())
        result = evaluate_branch_admissibility(state, unclaimed)
        self.assertIn("falsifiable_claim", result.failed_gates)

    def test_claim_without_quantifiers_fails_the_scope_gate(self):
        builder = seeded_builder()
        vague = make_claim(
            "clm_policy-002",
            statement="Something interesting happens for large x.",
            quantifiers=(),
        )
        builder.add("CLAIM_RECORDED", {"claim": vague.to_dict()})
        state = builder.state()
        candidate = make_branch(
            "brn_policy-003", claim_refs=("clm_policy-002",)
        )
        result = evaluate_branch_admissibility(state, candidate)
        self.assertIn("explicit_scope", result.failed_gates)

    def test_disallowed_evidence_kind_fails_the_plan_gate(self):
        state = seeded_builder().state()
        candidate = make_branch(
            "brn_policy-003",
            evidence_plan=make_plan(kind=EvidenceKind.LITERATURE),
        )
        result = evaluate_branch_admissibility(state, candidate)
        self.assertIn("feasible_evidence_plan", result.failed_gates)

    def test_exhausted_duplicate_fails_the_duplicate_gate(self):
        builder = self.activated_builder()
        builder.add(
            "BRANCH_STATUS_CHANGED",
            {"branch_id": "brn_policy-001", "status": "EXHAUSTED"},
        )
        twin_claim = make_claim("clm_policy-002")  # same fingerprint content
        builder.add("CLAIM_RECORDED", {"claim": twin_claim.to_dict()})
        state = builder.state()
        candidate = make_branch(
            "brn_policy-003", claim_refs=("clm_policy-002",)
        )
        result = evaluate_branch_admissibility(state, candidate)
        self.assertIn("no_exhausted_duplicate", result.failed_gates)

        different_method = make_branch(
            "brn_policy-004",
            method_family="numerical_scan",
            claim_refs=("clm_policy-002",),
        )
        result = evaluate_branch_admissibility(state, different_method)
        self.assertNotIn("no_exhausted_duplicate", result.failed_gates)

    def test_insufficient_budget_fails_the_budget_gate(self):
        builder = seeded_builder()
        builder.add("BUDGET_CHARGED", {"dimension": "cycles", "amount": 10})
        state = builder.state()
        result = evaluate_branch_admissibility(
            state, state.branches["brn_policy-001"]
        )
        self.assertIn("sufficient_budget", result.failed_gates)


if __name__ == "__main__":
    unittest.main()
