"""Ask instead of stop, end to end through the real cycle.

A NON_DECIDABLE cycle hands the calling agent an `input_request`; the three
answers re-run the cycle with `inputs` / `input_policy=assume` and
`resume_checkpoint`, which reuses the paid conjecture and starts at the
validator with the inputs in hand.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _cycle_cache_payload, _do_cycle
from core.input_request import ASSUME_POLICY_TEXT
from tests.cycle_artifacts import remove_cycle_artifacts

PROVIDERS = {
    "conjecture": "codex_cli",
    "translator": "claude_cli",
    "reviewer": "codex_cli",
    "analyst": "codex_cli",
    "navigator": "agy_cli",
    "synth": "codex_cli",
}
APPROVED = {"status": "APPROVED", "reasoning": "ok", "revision_instructions": "",
            "coverage": ["inputs"], "defect_labels": [], "runtime_checks": []}
ND_CODE = "import sys\nprint('VERDICT: NON-DECIDABLE')\nprint('MISSING: a frozen fixed point U0')\nsys.exit(3)\n"
ASSUMED_CODE = ("print('ASSUMED: U0 = 0.30 -- typical fixed point')\n"
                "print('CHECK sign: FAIL')\nprint('VERDICT: FAIL')\n")
DECIDED_CODE = "print('CHECK sign: FAIL')\nprint('VERDICT: FAIL')\n"
RAW = "Test the input request flow."
GOAL = "Certify the accelerated warp fit."


def _fake(code, analysis):
    class FakeIntelligence:
        seen = {"conjectures": 0, "axiomatic": [], "translation_inputs": []}

        def __init__(self, provider, cli_models=None, cli_timeout=None):
            self.provider = provider
            self.cli_models = cli_models
            self.cli_timeout = cli_timeout
            self.cli_warnings = []
            self.cli_last_model = None
            self.cli_cost_usd = 0.0

        async def generate_conjecture(self, axiomatic_base, intuition):
            FakeIntelligence.seen["conjectures"] += 1
            FakeIntelligence.seen["axiomatic"].append(axiomatic_base)
            return "The fit converges once U0 is frozen."

        async def translate_to_code(self, conjecture, **_kwargs):
            FakeIntelligence.seen["translation_inputs"].append(conjecture)
            return code

        async def review_validation_code(self, **kwargs):
            FakeIntelligence.seen.setdefault("review_conjectures", []).append(kwargs.get("conjecture", ""))
            return dict(APPROVED)

        async def analyze_results(self, *args, **_kwargs):
            FakeIntelligence.seen.setdefault("analysis_conjectures", []).append(args[0] if args else "")
            return dict(analysis)

    return FakeIntelligence


async def _run(fake, extra):
    env = {
        "ASTRA_CYCLE_CACHE": "0",
        "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
        "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
        "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
        "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
        "ASTRA_MAX_RETRIES": "0",
        "ASTRA_ORACLE_MODE": "local",
    }
    with patch.dict("os.environ", env, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=PROVIDERS
    ), patch("core.llm_client.ASTRAIntelligence", fake):
        return await _do_cycle(
            {"action": "cycle", "intuition": RAW, "objective": GOAL,
             "cycle_timeout_seconds": 1500, **extra}
        )


class AskInsteadOfStop(unittest.IsolatedAsyncioTestCase):
    async def test_non_decidable_result_carries_the_question_and_the_resume(self):
        fake = _fake(ND_CODE, {"status": "NON_DECIDABLE", "reasoning": "U0 absent",
                               "missing_inputs": ["a frozen fixed point U0"]})
        result = await _run(fake, {})
        try:
            self.assertEqual(result["status"], "NON_DECIDABLE", result.get("error"))
            ask = result["input_request"]
            self.assertEqual(ask["action_required"], "ASK_USER")
            self.assertIn("a frozen fixed point U0", ask["question"])
            self.assertEqual(ask["resume_checkpoint"], result["checkpoint"])
            self.assertEqual(ask["options"]["assume"]["rerun"]["input_policy"], "assume")
            self.assertEqual(ask["options"]["provide"]["rerun"]["objective"], GOAL)
            self.assertEqual(ask["options"]["provide"]["rerun"]["resume_checkpoint"], result["checkpoint"])
            # The default run passes nothing extra to the models.
            self.assertEqual(fake.seen["axiomatic"], [""])
            self.assertNotIn("FROZEN INPUTS", fake.seen["translation_inputs"][0])
            self.assertNotIn("assumed_inputs", result)
        finally:
            remove_cycle_artifacts(result)

    async def test_provide_reruns_from_the_checkpoint_with_the_inputs(self):
        asked = _fake(ND_CODE, {"status": "NON_DECIDABLE", "reasoning": "U0 absent",
                                "missing_inputs": ["a frozen fixed point U0"]})
        first = await _run(asked, {})
        checkpoint = first["checkpoint"]
        resumed = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "sign is negative"})
        try:
            second = await _run(resumed, {"inputs": "U0 = 0.30\nansatz = gaussian(w=2)",
                                          "resume_checkpoint": checkpoint})
        finally:
            remove_cycle_artifacts(first)
        try:
            self.assertEqual(second["status"], "REFUTED", second.get("error"))
            self.assertEqual(resumed.seen["conjectures"], 0)          # conjecture reused
            self.assertEqual(second["conjecture"], "The fit converges once U0 is frozen.")
            self.assertEqual(second["resumed_from"], checkpoint)
            self.assertEqual(second["deliberation"]["resumed_from"], checkpoint)
            translation = resumed.seen["translation_inputs"][0]
            self.assertIn("FROZEN INPUTS (supplied by the user", translation)
            self.assertIn("U0 = 0.30", translation)
            # Inputs precede the conjecture: the bounded repairer reads only the head.
            self.assertLess(translation.index("FROZEN INPUTS"), translation.index("CONSENSUS CONJECTURE"))
            self.assertNotIn("input_request", second)
            self.assertNotIn("conjecture", second["timings"])          # nothing was paid for it
            self.assertEqual(second["input_policy"], "strict")
            self.assertEqual(second["inputs"], "U0 = 0.30\nansatz = gaussian(w=2)")
            checkpoint = json.loads(Path(second["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["inputs"], "U0 = 0.30\nansatz = gaussian(w=2)")
            self.assertEqual(checkpoint["input_policy"], "strict")
            # The reviewer and the analyst saw the inputs too, not only the author.
            self.assertIn("FROZEN INPUTS", resumed.seen["review_conjectures"][0])
            self.assertIn("FROZEN INPUTS", resumed.seen["analysis_conjectures"][0])
        finally:
            remove_cycle_artifacts(second)

    async def test_assume_policy_makes_the_verdict_conditional(self):
        fake = _fake(ASSUMED_CODE, {"status": "REFUTED", "reasoning": "sign is negative"})
        result = await _run(fake, {"input_policy": "assume"})
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertIn(ASSUME_POLICY_TEXT, fake.seen["axiomatic"][0])
            self.assertIn(ASSUME_POLICY_TEXT, fake.seen["translation_inputs"][0])
            self.assertEqual(result["assumed_inputs"], ["U0 = 0.30 -- typical fixed point"])
            self.assertIs(result["conditional_on_assumptions"], True)
            self.assertIn("Confirm assumed input: U0 = 0.30 -- typical fixed point",
                          result["deferred_claims"])
            self.assertEqual(result["goal_coverage"]["status"], "partial")
            self.assertEqual(result["scientific_status"], "ATOMIC_REFUTED")
            self.assertEqual(result["input_policy"], "assume")
            self.assertIn(ASSUME_POLICY_TEXT, fake.seen["review_conjectures"][0])
            self.assertLess(fake.seen["translation_inputs"][0].index(ASSUME_POLICY_TEXT),
                            fake.seen["translation_inputs"][0].index("CONSENSUS CONJECTURE"))
        finally:
            remove_cycle_artifacts(result)

    async def test_large_inputs_under_assume_still_show_the_policy_to_the_reviewer(self):
        fake = _fake(ASSUMED_CODE, {"status": "REFUTED", "reasoning": "r", "deferred_items": "none"})
        result = await _run(fake, {"input_policy": "assume", "inputs": "v = 1\n" * 600})
        try:
            reviewed = fake.seen["review_conjectures"][0]
            self.assertTrue(reviewed.startswith(ASSUME_POLICY_TEXT))
            self.assertIn("inputs shortened for this reader", reviewed)
            # A string deferred_items from the analyst is not exploded into letters.
            self.assertNotIn("n", [d for d in result["deferred_claims"] if len(d) == 1])
            self.assertIn("Confirm assumed input: U0 = 0.30 -- typical fixed point", result["deferred_claims"])
        finally:
            remove_cycle_artifacts(result)

    async def test_silent_assume_never_becomes_a_whole_goal_verdict(self):
        """Policy assume, validator declares no ASSUMED line, analyst says the
        goal is complete: the verdict must stay atomic and flagged."""
        fake = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "r",
                                    "goal_coverage": "COMPLETE", "goal_resolved": True})
        result = await _run(fake, {"input_policy": "assume", "objective": RAW})   # same goal
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(result["assumed_inputs"], [])
            self.assertIs(result["conditional_on_assumptions"], True)
            self.assertEqual(result["goal_coverage"]["status"], "partial")
            self.assertEqual(result["scientific_status"], "ATOMIC_REFUTED")
            self.assertTrue(any("declared no ASSUMED line" in d for d in result["deferred_claims"]))
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["input_policy"], "assume")
        finally:
            remove_cycle_artifacts(result)

    async def test_resume_with_another_direction_regenerates_and_warns(self):
        asked = _fake(ND_CODE, {"status": "NON_DECIDABLE", "reasoning": "U0 absent",
                                "missing_inputs": ["U0"]})
        first = await _run(asked, {})
        checkpoint = first["checkpoint"]
        other = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "r"})
        try:
            second = await _run(other, {"intuition": "A different direction, same objective.",
                                        "inputs": "U0 = 1", "resume_checkpoint": checkpoint})
        finally:
            remove_cycle_artifacts(first)
        try:
            self.assertEqual(other.seen["conjectures"], 1)
            self.assertNotIn("resumed_from", second)
            self.assertIn("different objective or direction", second["request"]["resume_warning"])
            self.assertTrue(any("resume_checkpoint ignored" in w for w in second["warnings"]))
        finally:
            remove_cycle_artifacts(second)

    async def test_resume_with_another_objective_regenerates_and_warns(self):
        asked = _fake(ND_CODE, {"status": "NON_DECIDABLE", "reasoning": "U0 absent",
                                "missing_inputs": ["U0"]})
        first = await _run(asked, {})
        checkpoint = first["checkpoint"]
        other = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "r"})
        try:
            second = await _run(other, {"objective": "A different objective.",
                                        "inputs": "U0 = 1", "resume_checkpoint": checkpoint})
        finally:
            remove_cycle_artifacts(first)
        try:
            self.assertEqual(other.seen["conjectures"], 1)
            self.assertNotIn("resumed_from", second)
            self.assertIn("different objective or direction", second["request"]["resume_warning"])
        finally:
            remove_cycle_artifacts(second)

    async def test_cache_key_sees_inputs_policy_and_resume(self):
        base = _cycle_cache_payload(dict(intuition="x"), "x", {})
        with_inputs = _cycle_cache_payload(dict(intuition="x", inputs="U0 = 1"), "x", {})
        assume = _cycle_cache_payload(dict(intuition="x", input_policy="assume"), "x", {})
        self.assertEqual(base["input_policy"], "strict")
        self.assertEqual(base["inputs"], "")
        self.assertNotEqual(json.dumps(base, sort_keys=True), json.dumps(with_inputs, sort_keys=True))
        self.assertNotEqual(json.dumps(base, sort_keys=True), json.dumps(assume, sort_keys=True))


class ServerExposesTheFields(unittest.TestCase):
    def test_both_cycle_tools_accept_inputs_policy_and_resume(self):
        import inspect

        from tests.test_mcp_server_concurrency import server_module

        for tool in (server_module.astra_cycle, server_module.astra_cycle_submit):
            params = inspect.signature(tool).parameters
            with self.subTest(tool=tool.__name__):
                self.assertEqual(params["inputs"].default, "")
                self.assertEqual(params["input_policy"].default, "strict")
                self.assertEqual(params["resume_checkpoint"].default, "")
                self.assertIn("input_request", tool.__doc__)


if __name__ == "__main__":
    unittest.main()
