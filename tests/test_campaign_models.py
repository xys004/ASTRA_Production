"""Fail-closed validation and stable serialization of campaign records."""
import json
import unittest

from core.campaign_models import (
    Actor,
    AssumptionDelta,
    Branch,
    BranchStatus,
    BudgetSnapshot,
    BudgetVector,
    Campaign,
    CampaignModelError,
    CampaignStatus,
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
    canonical_json,
)

COMMIT = "a" * 40
TS = "2026-08-12T00:00:00Z"
SHA = "b" * 64


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


def make_priority() -> PriorityVector:
    return PriorityVector(
        information_gain=0.8,
        evidence_strength=0.2,
        methodological_independence=0.9,
        goal_advancement=0.7,
        estimated_cost=0.3,
        instability_risk=0.1,
    )


def make_campaign(**overrides) -> Campaign:
    base = dict(
        campaign_id="cmp_alpha-0001",
        created_at=TS,
        source_commit=COMMIT,
        objective="Decide whether the bounded identity family holds.",
        success_definition="Every mandatory deliverable has credible evidence.",
        deliverables=("identity proof", "counterexample search report"),
        frozen_resources={"brief.md": SHA},
        allowed_evidence_classes=(EvidenceKind.SYMBOLIC, EvidenceKind.NUMERICAL),
        budget=make_budget(),
    )
    base.update(overrides)
    return Campaign(**base)


def make_plan(**overrides) -> EvidencePlan:
    base = dict(
        description="Symbolic residual check on the bounded family.",
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


def make_branch(**overrides) -> Branch:
    base = dict(
        branch_id="brn_alpha-0001",
        campaign_id="cmp_alpha-0001",
        created_at=TS,
        source_commit=COMMIT,
        direction="Attack the identity through exact residual simplification.",
        method_family="symbolic_residual",
        material_difference="Uses exact simplification instead of sampling.",
        assumption_delta=AssumptionDelta(added=("real domain",), removed=()),
        evidence_plan=make_plan(),
        priority_vector=make_priority(),
        budget=make_budget(cycles=4),
        deliverable_refs=("identity proof",),
        claim_refs=("clm_alpha-0001",),
    )
    base.update(overrides)
    return Branch(**base)


def make_claim(**overrides) -> Claim:
    base = dict(
        claim_id="clm_alpha-0001",
        campaign_id="cmp_alpha-0001",
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


def make_evidence(**overrides) -> Evidence:
    base = dict(
        evidence_id="evd_alpha-0001",
        campaign_id="cmp_alpha-0001",
        created_at=TS,
        source_commit=COMMIT,
        claim_ids=("clm_alpha-0001",),
        kind=EvidenceKind.SYMBOLIC,
        strength=EvidenceStrength.SCOPED,
        scope="bounded symbolic residual",
        engine="sympy",
        outcome=EvidenceOutcome.SUPPORTS,
        artifact_hashes={"artifacts/residual.py": SHA},
    )
    base.update(overrides)
    return Evidence(**base)


def make_episode(**overrides) -> Episode:
    base = dict(
        episode_id="epi_alpha-0001",
        campaign_id="cmp_alpha-0001",
        branch_id="brn_alpha-0001",
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
        claim_refs=("clm_alpha-0001",),
        evidence_refs=("evd_alpha-0001",),
        artifacts=("artifacts/residual.py",),
    )
    base.update(overrides)
    return Episode(**base)


def make_decision(**overrides) -> Decision:
    base = dict(
        decision_id="dec_alpha-0001",
        campaign_id="cmp_alpha-0001",
        created_at=TS,
        source_commit=COMMIT,
        action=DecisionAction.CONTINUE,
        policy_result={"hard_gates_passed": True, "failed_gates": []},
        reasons=("evidence is informative and the next obligation is clear",),
        budget_snapshot=BudgetSnapshot(
            limits=make_budget(), spent=make_budget(cycles=1, model_calls=5,
                                                    wall_seconds=100,
                                                    execution_seconds=10,
                                                    human_interventions=0,
                                                    remote_jobs=0)
        ),
        subject_branch_id="brn_alpha-0001",
    )
    base.update(overrides)
    return Decision(**base)


def make_envelope(**overrides) -> EventEnvelope:
    base = dict(
        event_id="evt_alpha-0001",
        campaign_id="cmp_alpha-0001",
        sequence=1,
        event_type="CAMPAIGN_CREATED",
        occurred_at=TS,
        source_commit=COMMIT,
        actor=Actor.SYSTEM,
        payload={"campaign": make_campaign().to_dict()},
        previous_event_sha256=None,
    )
    base.update(overrides)
    return EventEnvelope.create(**base)


class RoundTripTests(unittest.TestCase):
    def test_every_record_round_trips_stably(self):
        records = [
            (Campaign, make_campaign()),
            (Branch, make_branch()),
            (Claim, make_claim()),
            (Evidence, make_evidence()),
            (Episode, make_episode()),
            (Decision, make_decision()),
            (EventEnvelope, make_envelope()),
        ]
        for record_cls, record in records:
            with self.subTest(record=record_cls.__name__):
                first = record.to_dict()
                reloaded = record_cls.from_dict(json.loads(json.dumps(first)))
                second = reloaded.to_dict()
                self.assertEqual(first, second)
                self.assertEqual(canonical_json(first), canonical_json(second))

    def test_round_trip_preserves_canonical_hash_under_key_reordering(self):
        first = make_claim().to_dict()
        shuffled = dict(reversed(list(first.items())))
        self.assertEqual(canonical_json(first), canonical_json(shuffled))


class FailClosedValidationTests(unittest.TestCase):
    def test_invalid_ids_fail_closed(self):
        for bad_id in ("campaign-1", "CMP_ALPHA", "cmp_a", "brn_alpha-0001", 7):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(CampaignModelError):
                    make_campaign(campaign_id=bad_id)

    def test_timestamps_must_be_timezone_aware_utc(self):
        with self.assertRaises(CampaignModelError):
            make_campaign(created_at="2026-08-12T00:00:00")
        with self.assertRaises(CampaignModelError):
            make_campaign(created_at="2026-08-12T00:00:00+02:00")
        normalized = make_campaign(created_at="2026-08-12T00:00:00+00:00")
        self.assertEqual(normalized.created_at, TS)

    def test_unknown_schema_version_fails_closed(self):
        data = make_campaign().to_dict()
        data["schema_version"] = "astra-campaign/9.9"
        with self.assertRaises(CampaignModelError):
            Campaign.from_dict(data)
        envelope = make_envelope().to_dict()
        envelope["schema_version"] = "astra-campaign-event/9.9"
        with self.assertRaises(CampaignModelError):
            EventEnvelope.from_dict(envelope)

    def test_unknown_fields_fail_closed(self):
        data = make_campaign().to_dict()
        data["surprise"] = 1
        with self.assertRaises(CampaignModelError):
            Campaign.from_dict(data)

    def test_invalid_source_commit_fails_closed(self):
        with self.assertRaises(CampaignModelError):
            make_campaign(source_commit="not-a-sha")

    def test_portable_content_rejects_machine_paths(self):
        with self.assertRaises(CampaignModelError):
            make_claim(statement=r"The file C:\Users\nelson\proof.py shows it.")
        with self.assertRaises(CampaignModelError):
            make_campaign(objective="Reproduce /home/nelson/run.log exactly.")

    def test_artifact_paths_must_be_relative_with_valid_hashes(self):
        with self.assertRaises(CampaignModelError):
            make_evidence(artifact_hashes={r"C:\abs\path.py": SHA})
        with self.assertRaises(CampaignModelError):
            make_evidence(artifact_hashes={"../escape.py": SHA})
        with self.assertRaises(CampaignModelError):
            make_evidence(artifact_hashes={"artifacts/x.py": "zz"})

    def test_budget_vector_fails_closed(self):
        with self.assertRaises(CampaignModelError):
            make_budget(cycles=-1)
        with self.assertRaises(CampaignModelError):
            make_budget(model_calls=True)
        with self.assertRaises(CampaignModelError):
            make_budget().charge("quantum_leaps", 1)
        with self.assertRaises(CampaignModelError):
            make_budget().charge("cycles", 0)
        with self.assertRaises(CampaignModelError):
            BudgetSnapshot(
                limits=make_budget(cycles=1), spent=make_budget(cycles=2)
            )


class TransitionTests(unittest.TestCase):
    def test_campaign_transitions_follow_the_contract(self):
        campaign = make_campaign()
        active = campaign.with_status(CampaignStatus.ACTIVE)
        paused = active.with_status(CampaignStatus.PAUSED)
        resumed = paused.with_status(CampaignStatus.ACTIVE)
        completed = resumed.with_status(CampaignStatus.COMPLETED)
        self.assertEqual(completed.status, CampaignStatus.COMPLETED)

    def test_invalid_campaign_transitions_fail_closed(self):
        with self.assertRaises(CampaignModelError):
            make_campaign().with_status(CampaignStatus.COMPLETED)
        terminal = make_campaign(status=CampaignStatus.CANCELLED)
        with self.assertRaises(CampaignModelError):
            terminal.with_status(CampaignStatus.ACTIVE)

    def test_branch_transitions_follow_the_contract(self):
        branch = make_branch()
        admissible = branch.with_status(BranchStatus.ADMISSIBLE)
        active = admissible.with_status(BranchStatus.ACTIVE)
        suspended = active.with_status(BranchStatus.SUSPENDED)
        resumed = suspended.with_status(
            BranchStatus.ACTIVE, decision_id="dec_alpha-0002"
        )
        closed = resumed.with_status(BranchStatus.CLOSED)
        self.assertEqual(closed.status, BranchStatus.CLOSED)
        self.assertIn("dec_alpha-0002", closed.decision_history)

    def test_invalid_branch_transitions_fail_closed(self):
        with self.assertRaises(CampaignModelError):
            make_branch().with_status(BranchStatus.ACTIVE)
        terminal = make_branch(status=BranchStatus.REFUTED)
        with self.assertRaises(CampaignModelError):
            terminal.with_status(BranchStatus.ACTIVE)


class ClaimFingerprintTests(unittest.TestCase):
    def test_fingerprint_changes_when_semantic_scope_changes(self):
        base = make_claim()
        rescoped = make_claim(scope="x in [0, 1] only")
        self.assertNotEqual(base.fingerprint(), rescoped.fingerprint())

    def test_fingerprint_ignores_identity_but_not_content(self):
        twin = make_claim(claim_id="clm_alpha-0002")
        self.assertEqual(make_claim().fingerprint(), twin.fingerprint())
        reworded = make_claim(statement="For all real x, x*x >= 0.")
        self.assertNotEqual(make_claim().fingerprint(), reworded.fingerprint())

    def test_declared_fingerprint_mismatch_fails_closed(self):
        data = make_claim().to_dict()
        data["fingerprint"] = "0" * 64
        with self.assertRaises(CampaignModelError):
            Claim.from_dict(data)

    def test_numerical_prediction_requires_tolerance_and_units(self):
        with self.assertRaises(CampaignModelError):
            make_claim(claim_type=ClaimType.NUMERICAL_PREDICTION)
        claim = make_claim(
            claim_type=ClaimType.NUMERICAL_PREDICTION,
            tolerance="1e-9",
            units="dimensionless",
        )
        self.assertEqual(claim.tolerance, "1e-9")


class EvidenceContractTests(unittest.TestCase):
    def test_kind_specific_metadata_is_mandatory(self):
        cases = [
            (EvidenceKind.NUMERICAL, {"precision": "mpmath 50 digits"}),
            (EvidenceKind.FORMAL, {}),
            (EvidenceKind.LITERATURE, {}),
            (EvidenceKind.EMPIRICAL, {}),
        ]
        for kind, partial in cases:
            with self.subTest(kind=kind.value):
                with self.assertRaises(CampaignModelError):
                    make_evidence(kind=kind, metadata=partial)
        complete = make_evidence(
            kind=EvidenceKind.NUMERICAL,
            metadata={
                "precision": "mpmath 50 digits",
                "convergence": "richardson",
                "stability": "condition number 1e3",
            },
        )
        self.assertEqual(complete.kind, EvidenceKind.NUMERICAL)

    def test_kind_and_strength_stay_separate(self):
        evidence = make_evidence(strength=EvidenceStrength.CERTIFIED)
        payload = evidence.to_dict()
        self.assertEqual(payload["kind"], "SYMBOLIC")
        self.assertEqual(payload["strength"], "CERTIFIED")

    def test_operational_error_is_not_scientific_refutation(self):
        operational = make_evidence(outcome=EvidenceOutcome.OPERATIONAL_ERROR)
        self.assertFalse(operational.is_scientific_refutation)
        instability = make_evidence(
            outcome=EvidenceOutcome.NUMERICAL_INSTABILITY
        )
        self.assertFalse(instability.is_scientific_refutation)
        refutation = make_evidence(
            outcome=EvidenceOutcome.SCIENTIFIC_REFUTATION
        )
        self.assertTrue(refutation.is_scientific_refutation)

    def test_evidence_must_name_the_claims_it_tests(self):
        with self.assertRaises(CampaignModelError):
            make_evidence(claim_ids=())

    def test_self_referential_independence_link_fails_closed(self):
        with self.assertRaises(CampaignModelError):
            make_evidence(independence_links=("evd_alpha-0001",))


class DecisionContractTests(unittest.TestCase):
    def test_promoting_action_cannot_override_failed_hard_gates(self):
        for action in (
            DecisionAction.PROMOTE,
            DecisionAction.SELECT,
            DecisionAction.CONTINUE,
        ):
            with self.subTest(action=action.value):
                with self.assertRaises(CampaignModelError):
                    make_decision(
                        action=action,
                        policy_result={"hard_gates_passed": False},
                    )

    def test_non_promoting_action_may_record_failed_gates(self):
        decision = make_decision(
            action=DecisionAction.SUSPEND,
            policy_result={"hard_gates_passed": False, "failed_gates": ["x"]},
        )
        self.assertEqual(decision.action, DecisionAction.SUSPEND)

    def test_policy_result_must_carry_the_deterministic_gate_bit(self):
        with self.assertRaises(CampaignModelError):
            make_decision(policy_result={"note": "no gate result"})

    def test_model_recommendation_is_stored_separately(self):
        decision = make_decision(
            model_recommendation={"action": "PROMOTE", "provider": "agy"}
        )
        payload = decision.to_dict()
        self.assertEqual(payload["action"], "CONTINUE")
        self.assertEqual(payload["model_recommendation"]["action"], "PROMOTE")

    def test_reasons_are_mandatory(self):
        with self.assertRaises(CampaignModelError):
            make_decision(reasons=())


class EventEnvelopeTests(unittest.TestCase):
    def test_payload_mutation_is_detected(self):
        data = make_envelope().to_dict()
        data["payload"]["campaign"]["objective"] = "Silently different."
        with self.assertRaises(CampaignModelError):
            EventEnvelope.from_dict(data)

    def test_stored_hash_mutation_is_detected(self):
        data = make_envelope().to_dict()
        data["event_sha256"] = "0" * 64
        with self.assertRaises(CampaignModelError):
            EventEnvelope.from_dict(data)

    def test_first_event_must_not_link_backwards(self):
        with self.assertRaises(CampaignModelError):
            make_envelope(previous_event_sha256=SHA)
        with self.assertRaises(CampaignModelError):
            make_envelope(sequence=2, previous_event_sha256=None)

    def test_actor_and_event_type_are_closed_sets(self):
        data = make_envelope().to_dict()
        data["actor"] = "gemini"
        with self.assertRaises(CampaignModelError):
            EventEnvelope.from_dict(data)
        with self.assertRaises(CampaignModelError):
            make_envelope(event_type="CAMPAIGN_IMAGINED")


if __name__ == "__main__":
    unittest.main()
