"""Stage 2: the atomic cycle wrapped as a campaign Episode executor."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from core.campaign_executor import (
    CampaignExecutorError,
    build_portfolio_context,
    estimate_model_calls,
    map_cycle_outcome,
    record_episode_result,
    run_episode,
)
from core.campaign_models import (
    Actor,
    AssumptionDelta,
    Branch,
    BranchStatus,
    BudgetVector,
    Campaign,
    Claim,
    ClaimStatus,
    ClaimType,
    EvidenceKind,
    EvidenceOutcome,
    EvidencePlan,
    EvidenceStrength,
    GoalCoverage,
    OperationStatus,
    PriorityVector,
)
from core.campaign_store import CampaignStore

COMMIT = "a" * 40
TS = "2026-08-12T00:00:00Z"
SHA = "b" * 64
CAMPAIGN_ID = "cmp_exec-0001"
SEED_CLAIM_ID = "clm_exec-0001"
SEED_BRANCH_ID = "brn_exec-0001"


def make_budget(**overrides) -> BudgetVector:
    base = dict(
        cycles=10,
        model_calls=100,
        wall_seconds=36000,
        execution_seconds=18000,
        human_interventions=2,
        remote_jobs=4,
    )
    base.update(overrides)
    return BudgetVector(**base)


def make_candidate_dict(**overrides) -> dict:
    base = {
        "statement": "For all real x, x**2 >= 0.",
        "claim_type": "UNIVERSAL",
        "domain": "real analysis",
        "scope": "all real x",
        "quantifiers": ["forall x in R"],
        "assumptions": ["standard ordering of R"],
        "tolerance": None,
        "units": None,
        "method_family": "symbolic_residual",
        "material_difference": "Exact simplification instead of sampling.",
        "assumption_delta": {"added": [], "removed": []},
        "evidence_plan": {
            "description": "Symbolic residual check.",
            "kind": "SYMBOLIC",
        },
        "deliverable": "identity proof",
        "direction": "Attack via exact residual simplification.",
        "crux": "Show the residual simplifies to zero in the general case.",
    }
    base.update(overrides)
    return base


def make_portfolio_dict(**overrides) -> dict:
    base = {
        "schema_version": "astra-portfolio/0.1",
        "selected": make_candidate_dict(),
        "alternatives": [
            make_candidate_dict(
                statement="A bounded numerical scan finds no negative value.",
                method_family="numerical_scan",
                material_difference="Sampling instead of exact simplification.",
                evidence_plan={
                    "description": "Dense scan on a bounded grid.",
                    "kind": "NUMERICAL",
                },
                crux=None,
            )
        ],
    }
    base.update(overrides)
    return base


def make_cycle_result(**overrides) -> dict:
    base = {
        "status": "VALIDATED",
        "scientific_status": "ATOMIC_VALIDATED",
        "code_review": {"status": "APPROVED"},
        "goal_coverage": {"status": "partial"},
        "code": "print('VERDICT: PASS')\n",
        "execution_result": {"stdout": "CHECK identity: OK\nVERDICT: PASS\n"},
        "timings": {
            "conjecture": 10.0,
            "translate": 20.0,
            "execute": 5.0,
            "analysis": 8.0,
        },
        "deliberation": {
            "proposals": [{"provider": "codex_cli"}, {"provider": "agy_cli"}],
            "critiques": [{"provider": "codex_cli"}, {"provider": "agy_cli"}],
            "portfolio": make_portfolio_dict(),
        },
        "providers": {"translator": "claude_cli"},
        "actual_models": {"translator": "claude-opus-4-8"},
        "oracle_mode": "local",
    }
    base.update(overrides)
    return base


def make_id_factory():
    prefixes = {
        "claim": "clm",
        "branch": "brn",
        "episode": "epi",
        "evidence": "evd",
        "decision": "dec",
    }
    counts: dict = {}

    def factory(kind: str) -> str:
        counts[kind] = counts.get(kind, 0) + 1
        return f"{prefixes[kind]}_x{counts[kind]:04d}"

    return factory


def fixed_now() -> str:
    return TS


def seed_store(
    root: Path,
    cleanup,
    *,
    plan_kind: EvidenceKind = EvidenceKind.SYMBOLIC,
    budget: BudgetVector | None = None,
    activate: bool = True,
) -> CampaignStore:
    """Ledger with an ACTIVE campaign and one (optionally ACTIVE) branch."""
    store = CampaignStore(root, CAMPAIGN_ID, source_commit=COMMIT)
    cleanup(store.close)
    campaign = Campaign(
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        objective="Decide whether the bounded identity family holds.",
        success_definition="Every deliverable has credible evidence.",
        deliverables=("identity proof", "counterexample report"),
        frozen_resources={"brief.md": SHA},
        allowed_evidence_classes=(
            EvidenceKind.SYMBOLIC,
            EvidenceKind.NUMERICAL,
        ),
        budget=budget if budget is not None else make_budget(),
    )
    store.append_event(
        event_type="CAMPAIGN_CREATED",
        payload={"campaign": campaign.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    store.append_event(
        event_type="CAMPAIGN_STATUS_CHANGED",
        payload={"status": "ACTIVE"},
        actor=Actor.HUMAN,
        occurred_at=TS,
    )
    claim = Claim(
        claim_id=SEED_CLAIM_ID,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        statement="For all real x, x**2 >= 0.",
        claim_type=ClaimType.UNIVERSAL,
        domain="real analysis",
        scope="all real x",
        quantifiers=("forall x in R",),
        assumptions=("standard ordering of R",),
        unresolved_obligations=("Close the general simplification.",),
    )
    store.append_event(
        event_type="CLAIM_RECORDED",
        payload={"claim": claim.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    branch = Branch(
        branch_id=SEED_BRANCH_ID,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        direction="Attack via exact residual simplification.",
        method_family="symbolic_residual",
        material_difference="Exact simplification instead of sampling.",
        assumption_delta=AssumptionDelta(),
        evidence_plan=EvidencePlan(
            description="Symbolic residual check.",
            kind=plan_kind,
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
            information_gain=0.8,
            evidence_strength=0.2,
            methodological_independence=0.9,
            goal_advancement=0.7,
            estimated_cost=0.3,
            instability_risk=0.1,
        ),
        budget=make_budget(cycles=4),
        deliverable_refs=("identity proof",),
        claim_refs=(SEED_CLAIM_ID,),
    )
    store.append_event(
        event_type="BRANCH_CREATED",
        payload={"branch": branch.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    store.append_event(
        event_type="BRANCH_STATUS_CHANGED",
        payload={"branch_id": SEED_BRANCH_ID, "status": "ADMISSIBLE"},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    if activate:
        store.append_event(
            event_type="BRANCH_STATUS_CHANGED",
            payload={"branch_id": SEED_BRANCH_ID, "status": "ACTIVE"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
    return store


def exhaust_family(
    store: CampaignStore, family: str, claim_id: str, branch_id: str
) -> None:
    """Record a terminal branch so its method family becomes forbidden."""
    claim = Claim(
        claim_id=claim_id,
        campaign_id=CAMPAIGN_ID,
        created_at=TS,
        source_commit=COMMIT,
        statement=f"Exhausted claim for {family}.",
        claim_type=ClaimType.SCOPED_EMPIRICAL,
        domain="real analysis",
        scope="bounded grid",
        quantifiers=("bounded x",),
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
        direction=f"Old {family} attempt.",
        method_family=family,
        material_difference="Historical attempt.",
        assumption_delta=AssumptionDelta(),
        evidence_plan=EvidencePlan(
            description="Old plan.",
            kind=EvidenceKind.NUMERICAL,
            estimated_cost=BudgetVector(cycles=1),
        ),
        priority_vector=PriorityVector(
            information_gain=0.1,
            evidence_strength=0.1,
            methodological_independence=0.1,
            goal_advancement=0.1,
            estimated_cost=0.1,
            instability_risk=0.1,
        ),
        budget=make_budget(cycles=1),
        deliverable_refs=("identity proof",),
        claim_refs=(claim_id,),
    )
    store.append_event(
        event_type="BRANCH_CREATED",
        payload={"branch": branch.to_dict()},
        actor=Actor.SYSTEM,
        occurred_at=TS,
    )
    for status in ("ADMISSIBLE", "SUSPENDED", "EXHAUSTED"):
        store.append_event(
            event_type="BRANCH_STATUS_CHANGED",
            payload={"branch_id": branch_id, "status": status},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )


class OutcomeMappingTests(unittest.TestCase):
    def test_validated_maps_to_supports_scoped(self):
        axes = map_cycle_outcome(make_cycle_result())
        self.assertEqual(axes.operation_status, OperationStatus.COMPLETED)
        self.assertEqual(axes.claim_status, ClaimStatus.SUPPORTED)
        self.assertEqual(axes.evidence_outcome, EvidenceOutcome.SUPPORTS)
        self.assertEqual(axes.evidence_strength, EvidenceStrength.SCOPED)
        self.assertEqual(axes.goal_coverage, GoalCoverage.PARTIAL)

    def test_unreviewed_validation_is_only_preliminary(self):
        axes = map_cycle_outcome(
            make_cycle_result(code_review={"status": "REVISE"})
        )
        self.assertEqual(axes.evidence_strength, EvidenceStrength.PRELIMINARY)

    def test_refuted_maps_to_scientific_refutation(self):
        axes = map_cycle_outcome(
            make_cycle_result(
                status="REFUTED", scientific_status="ATOMIC_REFUTED"
            )
        )
        self.assertEqual(axes.claim_status, ClaimStatus.REFUTED)
        self.assertEqual(
            axes.evidence_outcome, EvidenceOutcome.SCIENTIFIC_REFUTATION
        )

    def test_code_error_is_operational_never_refutation(self):
        axes = map_cycle_outcome(
            make_cycle_result(status="CODE_ERROR", scientific_status="")
        )
        self.assertEqual(axes.operation_status, OperationStatus.FAILED)
        self.assertEqual(axes.claim_status, ClaimStatus.NOT_TESTED)
        self.assertEqual(
            axes.evidence_outcome, EvidenceOutcome.OPERATIONAL_ERROR
        )

    def test_api_error_and_partial_produce_no_evidence(self):
        for status in ("API_ERROR", "PARTIAL", "SOMETHING_NEW"):
            with self.subTest(status=status):
                axes = map_cycle_outcome(
                    make_cycle_result(status=status, scientific_status="")
                )
                self.assertEqual(axes.operation_status, OperationStatus.FAILED)
                self.assertEqual(axes.claim_status, ClaimStatus.NOT_TESTED)
                self.assertIsNone(axes.evidence_outcome)

    def test_weak_pass_is_inconclusive(self):
        axes = map_cycle_outcome(
            make_cycle_result(status="WEAK_PASS", scientific_status="")
        )
        self.assertEqual(axes.claim_status, ClaimStatus.INCONCLUSIVE)
        self.assertEqual(axes.evidence_outcome, EvidenceOutcome.INCONCLUSIVE)

    def test_model_call_estimate_is_deterministic(self):
        self.assertEqual(estimate_model_calls(make_cycle_result()), 8)
        self.assertEqual(estimate_model_calls({}), 3)


class RecordEpisodeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_validated_episode_records_the_full_trail(self):
        store = seed_store(self.root, self.addCleanup)
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            make_cycle_result(),
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertEqual(
            report.axes.operation_status, OperationStatus.COMPLETED
        )
        self.assertEqual(report.tested_claim_ids, (SEED_CLAIM_ID,))
        self.assertIsNotNone(report.evidence_id)
        self.assertFalse(report.budget_exhausted)
        self.assertEqual(len(report.promoted_branch_ids), 1)
        state = store.replay().state
        self.assertEqual(state.spent.cycles, 1)
        self.assertEqual(state.spent.model_calls, 8)
        self.assertEqual(state.spent.wall_seconds, 43)
        self.assertEqual(state.spent.execution_seconds, 5)
        episode = state.episodes[report.episode_id]
        self.assertEqual(episode.claim_refs, (SEED_CLAIM_ID,))
        self.assertEqual(episode.evidence_refs, (report.evidence_id,))
        self.assertEqual(episode.branch_status, BranchStatus.ACTIVE)
        evidence = state.evidence[report.evidence_id]
        self.assertEqual(evidence.outcome, EvidenceOutcome.SUPPORTS)
        self.assertEqual(evidence.strength, EvidenceStrength.SCOPED)
        self.assertEqual(evidence.kind, EvidenceKind.SYMBOLIC)
        self.assertTrue(evidence.artifact_hashes)
        for relpath, digest in evidence.artifact_hashes.items():
            target = store.campaign_dir / Path(relpath)
            self.assertTrue(target.exists())
            self.assertEqual(
                hashlib.sha256(target.read_bytes()).hexdigest(), digest
            )
        promoted = state.branches[report.promoted_branch_ids[0]]
        self.assertEqual(promoted.status, BranchStatus.ADMISSIBLE)
        self.assertEqual(promoted.method_family, "numerical_scan")
        self.assertEqual(promoted.parent_branch_id, SEED_BRANCH_ID)
        self.assertEqual(promoted.parent_episode_id, report.episode_id)
        self.assertEqual(
            store.load_checkpoint()["last_sequence"], state.last_sequence
        )

    def test_refutation_lands_in_the_refutation_index(self):
        store = seed_store(self.root, self.addCleanup)
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            make_cycle_result(
                status="REFUTED", scientific_status="ATOMIC_REFUTED"
            ),
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        state = store.replay().state
        self.assertEqual(
            state.scientific_refutations(SEED_CLAIM_ID),
            (report.evidence_id,),
        )

    def test_code_error_records_operational_evidence_not_refutation(self):
        store = seed_store(self.root, self.addCleanup)
        result = make_cycle_result(status="CODE_ERROR", scientific_status="")
        result["deliberation"]["portfolio"] = None
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            result,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        state = store.replay().state
        evidence = state.evidence[report.evidence_id]
        self.assertEqual(evidence.outcome, EvidenceOutcome.OPERATIONAL_ERROR)
        self.assertFalse(evidence.is_scientific_refutation)
        self.assertEqual(state.scientific_refutations(SEED_CLAIM_ID), ())
        episode = state.episodes[report.episode_id]
        self.assertEqual(episode.operation_status, OperationStatus.FAILED)
        self.assertEqual(episode.claim_status, ClaimStatus.NOT_TESTED)

    def test_api_error_records_episode_without_evidence(self):
        store = seed_store(self.root, self.addCleanup)
        result = make_cycle_result(status="API_ERROR", scientific_status="")
        result["deliberation"]["portfolio"] = None
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            result,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertIsNone(report.evidence_id)
        state = store.replay().state
        self.assertEqual(state.evidence, {})
        self.assertEqual(
            state.episodes[report.episode_id].operation_status,
            OperationStatus.FAILED,
        )

    def test_new_selected_claim_is_recorded_and_attached(self):
        store = seed_store(self.root, self.addCleanup)
        portfolio = make_portfolio_dict()
        portfolio["selected"]["statement"] = (
            "For all real x and y, (x*y)**2 >= 0."
        )
        result = make_cycle_result()
        result["deliberation"]["portfolio"] = portfolio
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            result,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertNotEqual(report.tested_claim_ids, (SEED_CLAIM_ID,))
        state = store.replay().state
        tested = report.tested_claim_ids[0]
        self.assertIn(tested, state.claims)
        self.assertIn(tested, state.branches[SEED_BRANCH_ID].claim_refs)
        evidence = state.evidence[report.evidence_id]
        self.assertEqual(evidence.claim_ids, (tested,))

    def test_forbidden_family_alternative_is_rejected(self):
        store = seed_store(self.root, self.addCleanup, activate=False)
        exhaust_family(
            store, "numerical_scan", "clm_exec-0002", "brn_exec-0002"
        )
        store.append_event(
            event_type="BRANCH_STATUS_CHANGED",
            payload={"branch_id": SEED_BRANCH_ID, "status": "ACTIVE"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        state = store.replay().state
        context = build_portfolio_context(state)
        self.assertIn("numerical_scan", context["forbidden_method_families"])
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            make_cycle_result(),
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertEqual(report.promoted_branch_ids, ())
        self.assertEqual(len(report.rejected_branch_ids), 1)
        self.assertTrue(any("R4" in note for note in report.notes))
        state = store.replay().state
        rejected = state.branches[report.rejected_branch_ids[0]]
        self.assertEqual(rejected.status, BranchStatus.REJECTED)

    def test_budget_overspend_is_clamped_and_flagged(self):
        store = seed_store(
            self.root, self.addCleanup, budget=make_budget(wall_seconds=30)
        )
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            make_cycle_result(),
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertTrue(report.budget_exhausted)
        self.assertTrue(any("wall_seconds" in note for note in report.notes))
        state = store.replay().state
        self.assertEqual(state.spent.wall_seconds, 30)
        self.assertEqual(state.spent.cycles, 1)

    def test_numerical_evidence_requires_mandatory_metadata(self):
        store = seed_store(
            self.root, self.addCleanup, plan_kind=EvidenceKind.NUMERICAL
        )
        with self.assertRaises(CampaignExecutorError):
            record_episode_result(
                store,
                SEED_BRANCH_ID,
                make_cycle_result(),
                id_factory=make_id_factory(),
                now_iso=fixed_now,
            )
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            make_cycle_result(),
            evidence_metadata={
                "precision": "float64",
                "convergence": "grid refinement x2",
                "stability": "no cancellation observed",
            },
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        state = store.replay().state
        self.assertEqual(
            state.evidence[report.evidence_id].kind, EvidenceKind.NUMERICAL
        )

    def test_real_cycle_result_shape_is_transcribed(self):
        # Regression from the first live canary: the real _do_cycle result
        # stores oracle output under "execution", actual models under
        # "cli_models", and the oracle route under "oracle_used".
        store = seed_store(self.root, self.addCleanup)
        result = make_cycle_result()
        del result["execution_result"]
        del result["actual_models"]
        del result["oracle_mode"]
        result["execution"] = {"stdout": "CHECK identity: OK\nVERDICT: PASS\n"}
        result["cli_models"] = {"translator": "claude-opus-4-8"}
        result["oracle_used"] = "local"
        report = record_episode_result(
            store,
            SEED_BRANCH_ID,
            result,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        state = store.replay().state
        evidence = state.evidence[report.evidence_id]
        self.assertIn(
            f"artifacts/{report.episode_id}/stdout.txt",
            evidence.artifact_hashes,
        )
        self.assertEqual(evidence.engine, "local")
        episode = state.episodes[report.episode_id]
        self.assertEqual(
            episode.actual_models, {"translator": "claude-opus-4-8"}
        )

    def test_recording_requires_the_active_branch(self):
        store = seed_store(self.root, self.addCleanup, activate=False)
        with self.assertRaises(CampaignExecutorError):
            record_episode_result(
                store,
                SEED_BRANCH_ID,
                make_cycle_result(),
                id_factory=make_id_factory(),
                now_iso=fixed_now,
            )


class RunEpisodeTests(unittest.IsolatedAsyncioTestCase):
    def fresh_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    async def test_run_episode_builds_the_request_contract(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        captured = {}

        async def fake_runner(request):
            captured.update(request)
            return make_cycle_result()

        report = await run_episode(
            store,
            SEED_BRANCH_ID,
            cycle_runner=fake_runner,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        self.assertEqual(captured["action"], "cycle")
        self.assertIn(
            "Attack via exact residual simplification.", captured["intuition"]
        )
        self.assertIn("ATOMIC CLAIM UNDER TEST", captured["intuition"])
        self.assertIn(
            "Close the general simplification.", captured["intuition"]
        )
        self.assertEqual(
            captured["objective"],
            "Decide whether the bounded identity family holds.",
        )
        context = captured["portfolio_context"]
        self.assertEqual(
            context["deliverables"],
            ["identity proof", "counterexample report"],
        )
        self.assertEqual(
            context["allowed_evidence_kinds"], ["SYMBOLIC", "NUMERICAL"]
        )
        self.assertEqual(context["forbidden_method_families"], [])
        self.assertGreaterEqual(captured["cycle_timeout_seconds"], 60)
        self.assertEqual(report.axes.claim_status, ClaimStatus.SUPPORTED)
        state = store.replay().state
        episode = state.episodes[report.episode_id]
        self.assertIn("ATOMIC CLAIM UNDER TEST", episode.inputs["intuition"])

    async def test_a_reviewer_objection_reaches_the_next_author(self):
        """End-to-end: a refusal persists to the ledger and surfaces next time."""
        store = seed_store(self.fresh_root(), self.addCleanup)
        objection = "delta>0 is decided in QQ, not QQbar; wrap it as QQbar(...)."
        id_factory = make_id_factory()  # shared, so ids do not collide across episodes

        async def refusing_runner(_request):
            return make_cycle_result(
                status="TOOL_ERROR",
                scientific_status="",
                phase="reviewer",
                error="Independent reviewer did not approve: " + objection,
                code_review={
                    "status": "REVISE",
                    "reasoning": objection,
                    "revision_instructions": "decide every sign in QQbar",
                },
            )

        first = await run_episode(
            store,
            SEED_BRANCH_ID,
            cycle_runner=refusing_runner,
            id_factory=id_factory,
            now_iso=fixed_now,
        )
        self.assertEqual(first.axes.claim_status, ClaimStatus.NOT_TESTED)

        # The objection round-trips through the real Evidence record.
        state = store.replay().state
        episode = state.episodes[first.episode_id]
        self.assertTrue(episode.evidence_refs)
        evidence = state.evidence[episode.evidence_refs[0]]
        self.assertIn("QQbar", evidence.metadata.get("reviewer_objection", ""))

        # The next episode on the same branch receives it in its request.
        captured = {}

        async def capturing_runner(request):
            captured.update(request)
            return make_cycle_result()

        await run_episode(
            store,
            SEED_BRANCH_ID,
            cycle_runner=capturing_runner,
            id_factory=id_factory,
            now_iso=fixed_now,
        )
        self.assertIn("PRIOR REVIEWER OBJECTION ON THIS BRANCH", captured["intuition"])
        self.assertIn("decide every sign in QQbar", captured["intuition"])

    async def test_pre_gates_block_the_cycle_before_any_model_call(self):
        called = {"n": 0}

        async def fake_runner(_request):
            called["n"] += 1
            return make_cycle_result()

        inactive = seed_store(self.fresh_root(), self.addCleanup,
                              activate=False)
        with self.assertRaises(CampaignExecutorError):
            await run_episode(
                inactive, SEED_BRANCH_ID, cycle_runner=fake_runner
            )
        self.assertEqual(called["n"], 0)

        poor = seed_store(
            self.fresh_root(), self.addCleanup, budget=make_budget(cycles=0)
        )
        with self.assertRaises(CampaignExecutorError):
            await run_episode(poor, SEED_BRANCH_ID, cycle_runner=fake_runner)
        self.assertEqual(called["n"], 0)

    async def test_non_mapping_cycle_result_fails_closed(self):
        store = seed_store(self.fresh_root(), self.addCleanup)

        async def fake_runner(_request):
            return "not a dict"

        with self.assertRaises(CampaignExecutorError):
            await run_episode(store, SEED_BRANCH_ID, cycle_runner=fake_runner)


if __name__ == "__main__":
    unittest.main()
