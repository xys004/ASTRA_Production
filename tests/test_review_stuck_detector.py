"""C2 end to end: the real review loop under a reviewer that repeats itself.

Drives astra_tool._do_cycle with a fake model client whose reviewer rejects the
same defect class every round, and checks the escalation the spec prescribes
inside the SAME revision cap: directed correction, one strategy switch (a full
regeneration, not a bounded patch), then a clean stop naming the class.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _do_cycle
from tests.cycle_artifacts import remove_cycle_artifacts

STUCK_REVIEW = {
    "status": "REVISE",
    "reasoning": (
        "Bq uses independent positive symbols wi and wf, while Bq_positive checks the "
        "unrelated numerator num, so (2*Bq).is_positive is undecidable."
    ),
    "revision_instructions": "Use one q-dependent definition of wi and wf throughout.",
    "coverage": [],
    "defect_labels": ["missing_assumption"],
    "runtime_checks": [],
}
SAMPLING_REVIEW = {
    "status": "REVISE",
    "reasoning": "PASS promotes tests at one mass pair and finitely many t values into a universal claim.",
    "revision_instructions": "Replace the sampled assertions with an exact certificate.",
    "coverage": [],
    "defect_labels": ["sampling_as_proof"],
    "runtime_checks": [],
}
APPROVED = {
    "status": "APPROVED",
    "reasoning": "Exact witness ready.",
    "revision_instructions": "",
    "coverage": ["counterexample"],
    "defect_labels": [],
    "runtime_checks": [],
}
VALID_CODE = "print('CHECK counterexample: FAIL')\nprint('VERDICT: FAIL')\n"

PROVIDERS = {
    "conjecture": "codex_cli",
    "translator": "claude_cli",
    "reviewer": "codex_cli",
    "analyst": "codex_cli",
    "navigator": "agy_cli",
    "synth": "codex_cli",
}


def _fake(reviews, analyses=None):
    """A model client whose reviewer replays `reviews` (and the analyst
    `analyses`, default REFUTED) in order."""

    class FakeIntelligence:
        calls = {"translations": [], "patches": [], "reviews": 0, "analyses": 0}

        def __init__(self, provider, cli_models=None, cli_timeout=None):
            self.provider = provider
            self.cli_models = cli_models
            self.cli_timeout = cli_timeout
            self.cli_warnings = []
            self.cli_last_model = None
            self.cli_cost_usd = 0.0

        async def generate_conjecture(self, axiomatic_base, intuition):
            return "The candidate is refuted by x = 0."

        async def translate_to_code(self, conjecture, **kwargs):
            FakeIntelligence.calls["translations"].append(kwargs)
            return VALID_CODE

        async def repair_validation_code(self, conjecture, previous_code, instructions):
            FakeIntelligence.calls["patches"].append(instructions)
            return {"status": "APPLIED", "reason": "patched", "edits": [],
                    "code": previous_code + f"# patch {len(FakeIntelligence.calls['patches'])}\n"}

        async def review_validation_code(self, **_kwargs):
            index = FakeIntelligence.calls["reviews"]
            FakeIntelligence.calls["reviews"] += 1
            return dict(reviews[min(index, len(reviews) - 1)])

        async def analyze_results(self, *_args, **_kwargs):
            index = FakeIntelligence.calls["analyses"]
            FakeIntelligence.calls["analyses"] += 1
            if analyses and index < len(analyses):
                return dict(analyses[index])
            return {"status": "REFUTED", "reasoning": "Counterexample executed."}

    return FakeIntelligence


def _env(cap, detector="1", max_retries="0"):
    return {
        "ASTRA_CYCLE_CACHE": "0",
        "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
        "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
        "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
        "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": str(cap),
        "ASTRA_REVIEW_STUCK_DETECTOR": detector,
        "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
        "ASTRA_MAX_RETRIES": max_retries,
        "ASTRA_ORACLE_MODE": "local",
    }


async def _run(fake, env):
    with patch.dict("os.environ", env, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=PROVIDERS
    ), patch("core.llm_client.ASTRAIntelligence", fake):
        return await _do_cycle(
            {
                "action": "cycle",
                "intuition": "Test the review stuck detector.",
                "cycle_timeout_seconds": 1500,
            }
        )


class StuckDetectorInTheRealLoop(unittest.IsolatedAsyncioTestCase):
    async def test_same_class_thrice_directed_then_switch_then_clean_stop(self):
        fake = _fake([STUCK_REVIEW, STUCK_REVIEW, STUCK_REVIEW])
        result = await _run(fake, _env(cap=2))
        try:
            self.assertEqual(result["status"], "TOOL_ERROR")
            self.assertEqual(result["phase"], "reviewer")
            self.assertTrue(
                result["error"].startswith("Review stuck on defect class undecidable_positivity"),
                result["error"],
            )
            self.assertIn("after a directed correction and a strategy switch", result["error"])
            # Round 0 -> directed bounded patch (same cap slot the blind round used).
            self.assertEqual(len(fake.calls["patches"]), 1)
            self.assertIn("DIRECTED CORRECTION", fake.calls["patches"][0])
            self.assertIn("undecidable_positivity", fake.calls["patches"][0])
            # Round 1 (repeat) -> strategy switch = a full regeneration, not a patch.
            self.assertEqual(len(fake.calls["translations"]), 2)
            switch = fake.calls["translations"][1]
            self.assertTrue(switch.get("is_correction"))
            self.assertIn("STRATEGY SWITCH", switch["previous_error"])
            self.assertIn("q-dependent", switch["previous_error"])
            # Round 2 (repeat after the switch) -> clean stop; no fourth review.
            self.assertEqual(fake.calls["reviews"], 3)
            history = result["code_review_history"]
            self.assertEqual([h["c2_action"] for h in history],
                             ["directed_patch", "strategy_switch", "stop"])
            self.assertEqual(history[1]["repeated_classes"], ["undecidable_positivity"])
            diagnosis = result["code_review"]["stuck_diagnosis"]
            self.assertEqual(diagnosis["stuck_classes"], ["undecidable_positivity"])
            self.assertEqual(diagnosis["rejections"], 3)
            self.assertEqual(len(result["review_defect_trace"]), 3)
            # Provenance survives on disk too.
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["review_defect_trace"]), 3)
            self.assertEqual(checkpoint["code_review"]["stuck_diagnosis"]["stuck_classes"],
                             ["undecidable_positivity"])
        finally:
            remove_cycle_artifacts(result)

    async def test_stop_comes_before_the_cap_when_the_class_persists(self):
        """Decision 4: same budget, smarter. With cap 3 the loop stops at 2."""
        fake = _fake([STUCK_REVIEW, STUCK_REVIEW, STUCK_REVIEW, STUCK_REVIEW])
        result = await _run(fake, _env(cap=3))
        try:
            self.assertEqual(result["status"], "TOOL_ERROR")
            self.assertIn("2 model revision(s) used of 3", result["error"])
            self.assertEqual(fake.calls["reviews"], 3)
        finally:
            remove_cycle_artifacts(result)

    async def test_cap_one_still_names_the_class_without_inventing_a_switch(self):
        fake = _fake([STUCK_REVIEW, STUCK_REVIEW])
        result = await _run(fake, _env(cap=1))
        try:
            self.assertEqual(result["status"], "TOOL_ERROR")
            self.assertTrue(result["error"].startswith("Review stuck on defect class"))
            self.assertIn("after a directed correction;", result["error"])
            self.assertNotIn("strategy switch", result["error"])
            self.assertEqual(len(fake.calls["translations"]), 1)     # no regeneration
        finally:
            remove_cycle_artifacts(result)

    async def test_new_class_each_round_is_directed_and_never_switches(self):
        fake = _fake([STUCK_REVIEW, SAMPLING_REVIEW, APPROVED])
        result = await _run(fake, _env(cap=2))
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(len(fake.calls["patches"]), 2)
            self.assertIn("undecidable_positivity", fake.calls["patches"][0])
            self.assertIn("sampling_as_proof", fake.calls["patches"][1])
            self.assertEqual(len(fake.calls["translations"]), 1)
            actions = [h["c2_action"] for h in result["code_review_history"] if "c2_action" in h]
            self.assertEqual(actions, ["directed_patch", "directed_patch"])
        finally:
            remove_cycle_artifacts(result)

    async def test_post_oracle_retry_starts_a_fresh_comparison(self):
        """Second review loop of the same cycle (after a CODE_ERROR retry): its
        first rejection must not be compared with the earlier loop's last one,
        which was followed by an APPROVED and belongs to another script."""
        fake = _fake(
            [STUCK_REVIEW, APPROVED, STUCK_REVIEW, APPROVED],
            analyses=[{"status": "CODE_ERROR", "reasoning": "NameError at runtime."},
                      {"status": "REFUTED", "reasoning": "Counterexample executed."}],
        )
        result = await _run(fake, _env(cap=2, max_retries="1"))
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(result["retries"], 1)
            actions = [h["c2_action"] for h in result["code_review_history"] if "c2_action" in h]
            self.assertEqual(actions, ["directed_patch", "directed_patch"])
            self.assertEqual(len(fake.calls["translations"]), 1)      # no false switch
            trace = result["review_defect_trace"]
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[1]["repeated"], [])
        finally:
            remove_cycle_artifacts(result)

    async def test_kill_switch_restores_the_blind_loop(self):
        fake = _fake([STUCK_REVIEW, STUCK_REVIEW, STUCK_REVIEW])
        result = await _run(fake, _env(cap=2, detector="0"))
        try:
            self.assertEqual(result["status"], "TOOL_ERROR")
            self.assertTrue(
                result["error"].startswith("Independent reviewer did not approve"),
                result["error"],
            )
            self.assertNotIn("stuck_diagnosis", result["code_review"])
            self.assertEqual(result["review_defect_trace"], [])
            self.assertEqual(len(fake.calls["patches"]), 2)          # two blind patches
            self.assertNotIn("DIRECTED CORRECTION", fake.calls["patches"][0])
            self.assertEqual(len(fake.calls["translations"]), 1)
            self.assertNotIn("c2_action", result["code_review_history"][0])
        finally:
            remove_cycle_artifacts(result)


if __name__ == "__main__":
    unittest.main()
