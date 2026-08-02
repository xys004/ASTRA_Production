import unittest

from core.quality_benchmarks import load_quality_cases, select_quality_cases
from core.quality_metrics import OPERATIONAL_STATUSES, summarize_records, wilson_interval
from scripts.run_quality_benchmarks import _configuration_env


class QualityBenchmarkTests(unittest.TestCase):
    def test_interrupted_cycle_states_are_operational(self):
        self.assertIn("PARTIAL", OPERATIONAL_STATUSES)
        self.assertIn("BUSY", OPERATIONAL_STATUSES)

    def test_quota_optimized_quality_profile_uses_exact_model_ladder(self):
        env = _configuration_env("quota-optimized")
        self.assertEqual(env["ASTRA_CONJECTURE_PROVIDER"], "codex_cli")
        self.assertEqual(
            env["ASTRA_TRANSLATOR_MODELS"],
            "sonnet,claude-opus-4-8",
        )
        self.assertEqual(env["ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS"], "2")

    def test_suite_ids_are_unique_and_tracks_are_present(self):
        cases = load_quality_cases()
        self.assertEqual(len(cases), len({case.id for case in cases}))
        self.assertEqual(
            {case.track for case in cases},
            {"cycle", "validator_audit", "execution"},
        )

    def test_truth_suite_is_balanced(self):
        cases = load_quality_cases()
        cycle = [case for case in cases if case.track == "cycle"]
        validated = sum(case.expected == "VALIDATED" for case in cycle)
        refuted = sum(case.expected == "REFUTED" for case in cycle)
        self.assertLessEqual(abs(validated - refuted), 1)

    def test_smoke_selector_is_strict(self):
        cases = select_quality_cases(load_quality_cases(), tier="smoke")
        self.assertTrue(cases)
        self.assertTrue(all("smoke" in case.tags for case in cases))

    def test_false_acceptance_is_a_separate_veto_metric(self):
        records = [
            {
                "id": "true",
                "track": "cycle",
                "configuration": "full",
                "expected": "VALIDATED",
                "observed": "VALIDATED",
                "correct": True,
                "duration_s": 1.0,
            },
            {
                "id": "false",
                "track": "cycle",
                "configuration": "full",
                "expected": "REFUTED",
                "observed": "VALIDATED",
                "correct": False,
                "duration_s": 1.0,
            },
        ]
        metrics = summarize_records(records)
        self.assertEqual(metrics["scientific"]["strict_accuracy"], 0.5)
        self.assertEqual(metrics["scientific"]["false_acceptance_rate"], 1.0)

    def test_wilson_interval_bounds(self):
        low, high = wilson_interval(8, 10)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)


if __name__ == "__main__":
    unittest.main()
