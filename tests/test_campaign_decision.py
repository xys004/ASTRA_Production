"""Stage 3: deterministic decision policy and progressive widening."""
import tempfile
import unittest
from pathlib import Path

from core.campaign_decision import (
    CampaignDecisionError,
    MAX_UNINFORMATIVE_STREAK,
    apply_decision_plan,
    branch_spent,
    campaign_step,
    decide_after_episode,
    select_initial_branch,
    select_promotion_candidate,
    uninformative_streak,
)
from core.campaign_executor import record_episode_result
from core.campaign_models import (
    Actor,
    AssumptionDelta,
    Branch,
    BranchStatus,
    BudgetVector,
    CampaignStatus,
    Claim,
    ClaimType,
    DecisionAction,
    EvidenceKind,
    EvidencePlan,
    PriorityVector,
)

from test_campaign_executor import (
    CAMPAIGN_ID,
    COMMIT,
    SEED_BRANCH_ID,
    SEED_CLAIM_ID,
    TS,
    fixed_now,
    make_budget,
    make_cycle_result,
    make_id_factory,
    make_portfolio_dict,
    seed_store,
)


def add_admissible_alternative(
    store,
    *,
    branch_id: str,
    claim_id: str,
    family: str,
    information_gain: float = 0.6,
    quantifiers: tuple = ("forall x in R",),
    deliverable: str = "identity proof",
):
    claim = Claim(
        claim_id=claim_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        statement=f"Alternative claim explored through {family}.",
        claim_type=ClaimType.UNIVERSAL,
        domain="real analysis",
        scope="all real x",
        quantifiers=quantifiers,
    )
    store.append_event(
        event_type="CLAIM_RECORDED",
        payload={"claim": claim.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    branch = Branch(
        branch_id=branch_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        direction=f"Explore the objective through {family}.",
        method_family=family,
        material_difference=f"Materially different family {family}.",
        assumption_delta=AssumptionDelta(),
        evidence_plan=EvidencePlan(
            description=f"Cheapest discriminating check for {family}.",
            kind=EvidenceKind.SYMBOLIC,
            estimated_cost=BudgetVector(
                cycles=1,
                model_calls=8,
                wall_seconds=600,
                execution_seconds=120,
                human_interventions=0,
                remote_jobs=0,
            ),
        ),
        priority_vector=PriorityVector(
            information_gain=information_gain,
            evidence_strength=0.0,
            methodological_independence=0.7,
            goal_advancement=0.5,
            estimated_cost=0.4,
            instability_risk=0.2,
        ),
        budget=make_budget(cycles=4),
        deliverable_refs=(deliverable,),
        claim_refs=(claim_id,),
    )
    store.append_event(
        event_type="BRANCH_CREATED",
        payload={"branch": branch.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    store.append_event(
        event_type="BRANCH_STATUS_CHANGED",
        payload={"branch_id": branch_id, "status": "ADMISSIBLE"},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    return branch


def record(store, result, **overrides):
    return record_episode_result(
        store,
        SEED_BRANCH_ID,
        result,
        id_factory=overrides.pop("id_factory", make_id_factory()),
        now_iso=fixed_now,
        **overrides,
    )


def plain_result(**overrides):
    """A cycle result without a portfolio block (keeps promotions manual)."""
    result = make_cycle_result(**overrides)
    result["deliberation"]["portfolio"] = None
    return result


class DecisionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def decide(self, store, report, **kwargs):
        state = store.replay().state
        return decide_after_episode(
            state,
            report,
            source_commit=COMMIT,
            id_factory=kwargs.pop("id_factory", make_id_factory()),
            now_iso=fixed_now,
            **kwargs,
        )


class ContinueAndCloseRules(DecisionTestCase):
    def test_informative_evidence_continues_the_active_branch(self):
        store = seed_store(self.root, self.addCleanup)
        report = record(store, plain_result())
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R7-continue")
        self.assertEqual(plan.decisions[0].action, DecisionAction.CONTINUE)
        self.assertEqual(plan.transitions, ())
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertIn(plan.decisions[0].decision_id, state.decisions)
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.ACTIVE
        )

    def test_goal_completion_closes_the_campaign(self):
        store = seed_store(self.root, self.addCleanup)
        for deliverable in ("identity proof", "counterexample report"):
            store.append_event(
                event_type="DELIVERABLE_RESOLVED",
                payload={"deliverable": deliverable},
                actor=Actor.HUMAN,
                occurred_at=TS,
            )
        report = record(store, plain_result())
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R1-goal-complete")
        self.assertEqual(plan.decisions[0].action, DecisionAction.CLOSE)
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(state.campaign.status, CampaignStatus.COMPLETED)

    def test_campaign_budget_exhaustion_closes_exhausted(self):
        store = seed_store(
            self.root, self.addCleanup, budget=make_budget(cycles=1)
        )
        report = record(store, plain_result())
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R2-campaign-exhausted")
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(state.campaign.status, CampaignStatus.EXHAUSTED)


class WideningRules(DecisionTestCase):
    def test_refutation_promotes_the_best_alternative(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-high",
            claim_id="clm_alt-high",
            family="lean_formalization",
            information_gain=0.95,
        )
        add_admissible_alternative(
            store,
            branch_id="brn_alt-low",
            claim_id="clm_alt-low",
            family="numerical_scan",
            information_gain=0.30,
        )
        report = record(
            store,
            plain_result(status="REFUTED", scientific_status="ATOMIC_REFUTED"),
        )
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R3-refutation")
        decision = plan.decisions[0]
        self.assertEqual(decision.action, DecisionAction.PROMOTE)
        self.assertEqual(decision.subject_branch_id, "brn_alt-high")
        self.assertIn("brn_alt-low", decision.alternatives_considered)
        self.assertTrue(decision.policy_result["hard_gates_passed"])
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.REFUTED
        )
        self.assertEqual(
            state.branches["brn_alt-high"].status, BranchStatus.ACTIVE
        )
        self.assertIn(
            decision.decision_id,
            state.branches["brn_alt-high"].decision_history,
        )
        self.assertEqual(state.active_branch_id(), "brn_alt-high")

    def test_refutation_without_alternatives_requests_human_review(self):
        store = seed_store(self.root, self.addCleanup)
        report = record(
            store,
            plain_result(status="REFUTED", scientific_status="ATOMIC_REFUTED"),
        )
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R3-refutation")
        self.assertEqual(
            plan.decisions[0].action, DecisionAction.REQUEST_HUMAN_REVIEW
        )
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.REFUTED
        )
        self.assertEqual(state.campaign.status, CampaignStatus.PAUSED)

    def test_one_uninformative_episode_only_retries(self):
        store = seed_store(self.root, self.addCleanup)
        report = record(
            store, plain_result(status="CODE_ERROR", scientific_status="")
        )
        state = store.replay().state
        self.assertEqual(uninformative_streak(state, SEED_BRANCH_ID), 1)
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R7-continue")

    def test_uninformative_streak_suspends_and_promotes(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-0001",
            claim_id="clm_alt-0001",
            family="numerical_scan",
        )
        ids = make_id_factory()
        record(
            store,
            plain_result(status="CODE_ERROR", scientific_status=""),
            id_factory=ids,
        )
        report = record(
            store,
            plain_result(status="CODE_ERROR", scientific_status=""),
            id_factory=ids,
        )
        state = store.replay().state
        self.assertEqual(
            uninformative_streak(state, SEED_BRANCH_ID),
            MAX_UNINFORMATIVE_STREAK,
        )
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R5-uninformative")
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.SUSPENDED
        )
        self.assertEqual(
            state.branches["brn_alt-0001"].status, BranchStatus.ACTIVE
        )

    def test_branch_cycle_budget_exhaustion_promotes(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-0001",
            claim_id="clm_alt-0001",
            family="numerical_scan",
        )
        ids = make_id_factory()
        report = None
        for _ in range(4):  # the seed branch budget allows 4 cycles
            report = record(store, plain_result(), id_factory=ids)
        state = store.replay().state
        self.assertEqual(branch_spent(state, SEED_BRANCH_ID).cycles, 4)
        plan = self.decide(store, report)
        self.assertEqual(plan.rule, "R4-branch-exhausted")
        apply_decision_plan(store, plan)
        state = store.replay().state
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.EXHAUSTED
        )
        self.assertEqual(
            state.branches["brn_alt-0001"].status, BranchStatus.ACTIVE
        )

    def test_model_recommendation_cannot_override_failed_gates(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-good",
            claim_id="clm_alt-good",
            family="lean_formalization",
            information_gain=0.9,
        )
        add_admissible_alternative(
            store,
            branch_id="brn_alt-vague",
            claim_id="clm_alt-vague",
            family="numerical_scan",
            quantifiers=(),  # explicit_scope hard gate fails
        )
        report = record(
            store,
            plain_result(status="REFUTED", scientific_status="ATOMIC_REFUTED"),
        )
        plan = self.decide(
            store,
            report,
            model_recommendation={
                "subject_branch_id": "brn_alt-vague",
                "provider": "agy",
            },
        )
        decision = plan.decisions[0]
        self.assertEqual(decision.subject_branch_id, "brn_alt-good")
        self.assertEqual(
            decision.model_recommendation["subject_branch_id"],
            "brn_alt-vague",
        )
        self.assertFalse(
            decision.policy_result["candidates"]["brn_alt-vague"][
                "hard_gates_passed"
            ]
        )
        self.assertTrue(
            any("cannot override" in note for note in plan.notes)
        )


class BootstrapAndStepTests(unittest.IsolatedAsyncioTestCase):
    def fresh_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    async def test_select_initial_branch_bootstraps_the_loop(self):
        store = seed_store(self.fresh_root(), self.addCleanup, activate=False)
        plan = select_initial_branch(
            store, id_factory=make_id_factory(), now_iso=fixed_now
        )
        self.assertEqual(plan.rule, "R0-initial-selection")
        self.assertEqual(plan.decisions[0].action, DecisionAction.SELECT)
        state = store.replay().state
        self.assertEqual(state.active_branch_id(), SEED_BRANCH_ID)
        with self.assertRaises(CampaignDecisionError):
            select_initial_branch(
                store, id_factory=make_id_factory(), now_iso=fixed_now
            )

    async def test_two_steps_close_the_loop_end_to_end(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        ids = make_id_factory()

        async def validated_runner(_request):
            return make_cycle_result()  # includes a portfolio alternative

        step1 = await campaign_step(
            store,
            cycle_runner=validated_runner,
            id_factory=ids,
            now_iso=fixed_now,
        )
        self.assertEqual(step1.plan.rule, "R7-continue")
        self.assertEqual(len(step1.episode.promoted_branch_ids), 1)
        promoted_id = step1.episode.promoted_branch_ids[0]

        async def refuted_runner(_request):
            result = make_cycle_result(
                status="REFUTED", scientific_status="ATOMIC_REFUTED"
            )
            result["deliberation"]["portfolio"] = None
            return result

        step2 = await campaign_step(
            store,
            cycle_runner=refuted_runner,
            id_factory=ids,
            now_iso=fixed_now,
        )
        self.assertEqual(step2.plan.rule, "R3-refutation")
        state = store.replay().state
        self.assertEqual(
            state.branches[SEED_BRANCH_ID].status, BranchStatus.REFUTED
        )
        self.assertEqual(state.active_branch_id(), promoted_id)
        self.assertEqual(state.spent.cycles, 2)
        self.assertEqual(
            store.load_checkpoint()["last_sequence"], state.last_sequence
        )

    async def test_step_without_active_branch_fails_closed(self):
        store = seed_store(self.fresh_root(), self.addCleanup, activate=False)

        async def runner(_request):
            return make_cycle_result()

        with self.assertRaises(CampaignDecisionError):
            await campaign_step(store, cycle_runner=runner)


class SelectionHelperTests(DecisionTestCase):
    def test_selection_prefers_information_gain_then_id(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-bbb",
            claim_id="clm_alt-bbb",
            family="numerical_scan",
            information_gain=0.5,
        )
        add_admissible_alternative(
            store,
            branch_id="brn_alt-aaa",
            claim_id="clm_alt-aaa",
            family="lean_formalization",
            information_gain=0.5,
        )
        state = store.replay().state
        candidate, trail = select_promotion_candidate(state)
        self.assertEqual(candidate.branch_id, "brn_alt-aaa")  # id tiebreak
        self.assertEqual(set(trail), {"brn_alt-aaa", "brn_alt-bbb"})

    def test_forbidden_families_are_excluded_from_selection(self):
        store = seed_store(self.root, self.addCleanup)
        add_admissible_alternative(
            store,
            branch_id="brn_alt-0001",
            claim_id="clm_alt-0001",
            family="numerical_scan",
        )
        state = store.replay().state
        candidate, trail = select_promotion_candidate(
            state, extra_forbidden_families=("numerical_scan",)
        )
        self.assertIsNone(candidate)
        self.assertTrue(trail["brn_alt-0001"]["forbidden_family"])


if __name__ == "__main__":
    unittest.main()
