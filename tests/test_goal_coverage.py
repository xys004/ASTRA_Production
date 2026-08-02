import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _do_cycle, _extract_deferred_items, _goal_coverage


class GoalCoverageTests(unittest.TestCase):
    def test_deferred_section_prevents_global_validation(self):
        conjecture = """[Hypothesis]
The curvature has the stated form.

[Deferred]
The spectrum, global holonomy, English review, and submission priorities remain.
"""
        coverage = _goal_coverage(
            "Review the entire paper for physics, structure, and English.",
            "Check the spin-orbit gauge reconstruction.",
            conjecture,
            {"status": "VALIDATED", "goal_coverage": "PARTIAL"},
            {},
        )
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["scientific_status"], "ATOMIC_VALIDATED")
        self.assertFalse(coverage["goal_resolved"])
        self.assertTrue(coverage["deferred_items"])

    def test_atomic_request_can_be_fully_validated(self):
        goal = "Verify x squared is nonnegative for every real x."
        coverage = _goal_coverage(
            goal,
            goal,
            "[Hypothesis] x^2 >= 0 for real x.",
            {"status": "VALIDATED", "goal_coverage": "COMPLETE"},
            {"macro_resolved": True},
        )
        self.assertEqual(coverage["status"], "complete")
        self.assertEqual(coverage["scientific_status"], "VALIDATED")
        self.assertTrue(coverage["goal_resolved"])

    def test_atomic_refutation_does_not_refute_broad_program(self):
        coverage = _goal_coverage(
            "Find a viable model among several candidate families.",
            "Test candidate family A.",
            "[Hypothesis] Family A is viable.\n[Deferred]\nFamilies B and C.",
            {"status": "REFUTED", "goal_coverage": "PARTIAL"},
            {},
        )
        self.assertEqual(coverage["scientific_status"], "ATOMIC_REFUTED")
        self.assertEqual(coverage["atomic_status"], "REFUTED")

    def test_deferred_parser_is_bounded_and_deduplicated(self):
        items = _extract_deferred_items(
            "[Deferred]\n- Boundary conditions\n- Boundary conditions\n- Global proof"
        )
        self.assertEqual(items, ["Boundary conditions", "Global proof"])


class GoalCoverageCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_exposes_atomic_pass_without_global_promotion(self):
        class FakeIntelligence:
            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = provider
                self.cli_cost_usd = 0.0

            async def generate_conjecture(self, **_kwargs):
                return (
                    "[Hypothesis]\nThe bounded identity holds.\n"
                    "[Deferred]\nThe global paper review and English edits remain."
                )

            async def translate_to_code(self, *_args, **_kwargs):
                return (
                    "value = 1 + 1\n"
                    "ok = value == 2\n"
                    "print(f\"CHECK identity: {'OK' if ok else 'FAIL'}\")\n"
                    "print('VERDICT: PASS' if ok else 'VERDICT: FAIL')\n"
                )

            async def review_validation_code(self, **_kwargs):
                return {
                    "status": "APPROVED",
                    "reasoning": "Bounded claim is executable.",
                    "revision_instructions": "",
                    "coverage": ["identity"],
                    "defect_labels": [],
                    "runtime_checks": [],
                }

            async def analyze_results(self, *_args, **_kwargs):
                return {
                    "status": "VALIDATED",
                    "reasoning": "The atomic identity passed; the paper remains open.",
                    "goal_coverage": "PARTIAL",
                    "goal_resolved": False,
                    "deferred_items": ["English edits"],
                }

        providers = {
            "conjecture": "codex_cli",
            "translator": "claude_cli",
            "reviewer": "codex_cli",
            "analyst": "codex_cli",
            "navigator": "agy_cli",
            "synth": "codex_cli",
        }
        env = {
            "ASTRA_CYCLE_CACHE": "0",
            "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
            "ASTRA_MAX_RETRIES": "0",
            "ASTRA_ORACLE_MODE": "local",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map", return_value=providers
        ), patch("core.llm_client.ASTRAIntelligence", FakeIntelligence):
            result = await _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Check one bounded identity.",
                    "objective": "Review the complete paper and its English.",
                    "cycle_timeout_seconds": 120,
                }
            )

        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(result["atomic_status"], "VALIDATED")
        self.assertEqual(result["scientific_status"], "ATOMIC_VALIDATED")
        self.assertEqual(result["oracle_verdict"], "PASS")
        self.assertEqual(result["goal_coverage"]["status"], "partial")
        self.assertIn("English edits", result["deferred_claims"])
        checkpoint = Path(result["checkpoint"])
        if checkpoint.exists():
            checkpoint.unlink()


if __name__ == "__main__":
    unittest.main()
