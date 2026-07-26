import json
import unittest
from pathlib import Path

from core.diversity_metrics import (
    compute_diversity_metrics,
    paired_architecture_summary,
)
from scripts.freeze_diversity_suite import OUTPUT, build_suite
from scripts.run_external_comparison import _scheduled_pairs


class DiversityBenchmarkTests(unittest.TestCase):
    def test_process_metrics_capture_diversity_review_and_repair_lift(self):
        report = {
            "architecture": {
                "proposers": ["codex_cli", "agy_cli"],
            },
            "designs": [
                {
                    "provider": "codex_cli",
                    "text": "Use a symbolic conservation-law derivation.",
                },
                {
                    "provider": "agy_cli",
                    "text": "Use dimensional analysis and a numerical limit check.",
                },
            ],
            "synthesis": (
                "Combine the conservation law, dimensional analysis, and a "
                "numerical limit check."
            ),
            "review": {"status": "REVISE"},
            "attempts": [
                {"evaluation": {"status": "FAIL"}},
                {"evaluation": {"status": "PASS"}},
            ],
            "evaluation": {"status": "PASS"},
        }
        metrics = compute_diversity_metrics(report)
        self.assertEqual(metrics["provider_count"], 2)
        self.assertTrue(metrics["heterogeneous_providers"])
        self.assertGreater(metrics["perspective_diversity_score"], 0)
        self.assertTrue(metrics["review_intervened"])
        self.assertEqual(metrics["repair_attempts"], 1)
        self.assertTrue(metrics["repair_lift"])

    def test_paired_summary_excludes_operational_cells(self):
        def record(case, configuration, status, diversity):
            return {
                "case_id": case,
                "configuration": configuration,
                "state": "complete",
                "status": status,
                "diversity": {
                    "perspective_diversity_score": diversity,
                },
            }

        records = [
            record("case-1", "full", "PASS", 0.8),
            record("case-1", "homogeneous-proposers", "FAIL", 0.3),
            record("case-2", "full", "PASS", 0.7),
            record("case-2", "homogeneous-proposers", "PASS", 0.2),
            record("case-3", "full", "TOOL_ERROR", None),
            record("case-3", "homogeneous-proposers", "PASS", 0.4),
        ]
        summary = paired_architecture_summary(records, seed=7)
        self.assertEqual(summary["paired_scored_cases"], 2)
        self.assertEqual(summary["diverse_wins"], 1)
        self.assertEqual(summary["control_wins"], 0)
        self.assertEqual(summary["ties"], 1)
        self.assertEqual(summary["pass_rate_delta"], 0.5)

    def test_vnext1_repairs_are_visible_in_process_metrics(self):
        report = {
            "cycle": {
                "validator_local_repair_history": [
                    {"repairs": [{"label": "unknown_as_pass"}]}
                ],
                "validator_model_patch_history": [
                    {"status": "APPLIED", "edit_count": 1}
                ],
            }
        }
        metrics = compute_diversity_metrics(report)
        self.assertEqual(metrics["deterministic_repair_edits"], 1)
        self.assertEqual(metrics["model_patch_attempts"], 1)
        self.assertEqual(metrics["model_patches_applied"], 1)
        self.assertEqual(metrics["repair_attempts"], 2)

    def test_frozen_suite_is_deterministic_balanced_and_disjoint(self):
        generated = build_suite()
        existing = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))
        self.assertEqual(generated, existing)
        self.assertEqual(len(generated["cases"]), 40)
        self.assertEqual(len(generated["execution_schedule"]), 80)
        calibration_ids = set(
            generated["selection"]["excluded_calibration_case_ids"]
        )
        self.assertFalse(
            calibration_ids & {item["id"] for item in generated["cases"]}
        )
        first = [
            item["configuration"]
            for item in generated["execution_schedule"]
            if item["position_within_pair"] == 1
        ]
        self.assertEqual(first.count("full"), 20)
        self.assertEqual(first.count("homogeneous-proposers"), 20)

    def test_frozen_schedule_covers_every_pair_once(self):
        suite = build_suite()
        pairs = _scheduled_pairs(
            suite,
            suite["cases"],
            suite["configurations"],
        )
        self.assertEqual(len(pairs), 80)
        self.assertEqual(
            len({(spec["id"], configuration) for spec, configuration in pairs}),
            80,
        )


if __name__ == "__main__":
    unittest.main()
