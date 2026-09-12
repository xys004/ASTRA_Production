"""C3: the opt-in request structurer, from the parser to the real cycle path.

`structure_request=true` must (a) call the structurer once before the
conjecture phase, (b) hand the conjecture engine the structured direction with
the raw request only as context, (c) keep both texts on the result and the
checkpoint, (d) change the cycle cache key, and (e) never kill the cycle when
the structurer fails. Without the flag nothing changes.
"""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _cycle_cache_payload, _do_cycle
from core.request_structurer import (
    HEADINGS,
    compose_direction,
    parse_structured_request,
    structure_requested,
)
from tests.cycle_artifacts import remove_cycle_artifacts

STRUCTURED = """BOUNDED CLAIM: For a free scalar field with m_f = m_i + d, d > 0, the modal coefficient B_q is strictly positive for every real q.
HYPOTHESES: m_i > 0; d > 0; omega_i = sqrt(q^2 + m_i^2); omega_f = sqrt(q^2 + m_f^2); q real.
DECISIVE: exact sign of B_q on the bound q-dependent expression; Z3 unsat of B_q <= 0.
AUXILIARY: numeric samples at fixed seed; the d -> 0 limit.
CERTIFICATION: analytic -- exact identity plus unsat negation.
REQUIRED INPUTS:
- a frozen fixed point U0
- the actuator ansatz
ANTI-PATTERNS: independent symbols wi, wf; positivity on a detached numerator.
DEFERRED: the full quench program and the Hartree extension.
"""

PROVIDERS = {
    "conjecture": "codex_cli",
    "translator": "claude_cli",
    "reviewer": "codex_cli",
    "analyst": "codex_cli",
    "navigator": "agy_cli",
    "synth": "codex_cli",
}
ENV = {
    "ASTRA_CYCLE_CACHE": "0",
    "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
    "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
    "ASTRA_MAX_RETRIES": "0",
    "ASTRA_ORACLE_MODE": "local",
}
RAW = "Test the request structurer."


def _fake(structured_reply):
    class FakeIntelligence:
        seen = {"structure": [], "conjecture_intuition": None}

        def __init__(self, provider, cli_models=None, cli_timeout=None):
            self.provider = provider
            self.cli_models = cli_models
            self.cli_timeout = cli_timeout
            self.cli_warnings = []
            self.cli_last_model = None
            self.cli_cost_usd = 0.0

        async def structure_request(self, intuition, objective="", axiomatic_base=""):
            FakeIntelligence.seen["structure"].append(
                {"provider": self.provider, "intuition": intuition, "objective": objective}
            )
            return structured_reply

        async def generate_conjecture(self, axiomatic_base, intuition):
            FakeIntelligence.seen["conjecture_intuition"] = intuition
            return "The candidate is refuted by x = 0."

        async def translate_to_code(self, conjecture, **_kwargs):
            return "print('CHECK counterexample: FAIL')\nprint('VERDICT: FAIL')\n"

        async def review_validation_code(self, **_kwargs):
            return {"status": "APPROVED", "reasoning": "Exact witness ready.",
                    "revision_instructions": "", "coverage": ["counterexample"],
                    "defect_labels": [], "runtime_checks": []}

        async def analyze_results(self, *_args, **_kwargs):
            return {"status": "REFUTED", "reasoning": "Counterexample executed."}

    return FakeIntelligence


async def _run(fake, req_extra):
    with patch.dict("os.environ", ENV, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=PROVIDERS
    ), patch("core.llm_client.ASTRAIntelligence", fake):
        return await _do_cycle(
            {"action": "cycle", "intuition": RAW, "cycle_timeout_seconds": 1500, **req_extra}
        )


class Parser(unittest.TestCase):
    def test_full_reply_parses_every_heading_and_the_required_inputs(self):
        parsed = parse_structured_request(STRUCTURED)
        self.assertTrue(parsed["complete"])
        self.assertEqual(set(parsed["sections"]), set(HEADINGS))
        self.assertTrue(parsed["sections"]["BOUNDED CLAIM"].startswith("For a free scalar field"))
        self.assertEqual(parsed["required_inputs"], ["a frozen fixed point U0", "the actuator ansatz"])
        self.assertIn("Hartree", parsed["sections"]["DEFERRED"])

    def test_none_and_markdown_headings(self):
        text = "\n".join(f"**{h}:** none" for h in HEADINGS)
        parsed = parse_structured_request(text)
        self.assertTrue(parsed["complete"])
        self.assertEqual(parsed["required_inputs"], [])
        partial = parse_structured_request("BOUNDED CLAIM: x\nDECISIVE: y")
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["sections"]["HYPOTHESES"], "")

    def test_compose_puts_the_direction_first_and_truncates_the_raw_request(self):
        composed = compose_direction("BOUNDED CLAIM: x", "r" * 5000, original_limit=100)
        self.assertTrue(composed.startswith("STRUCTURED RESEARCH DIRECTION"))
        self.assertIn("BOUNDED CLAIM: x", composed)
        self.assertIn("RAW REQUEST (context, not the direction)", composed)
        self.assertIn("[... raw request truncated ...]", composed)
        self.assertLess(len(composed), 600)

    def test_structure_requested_accepts_booleans_and_env_style_strings(self):
        self.assertTrue(structure_requested({"structure_request": True}))
        self.assertTrue(structure_requested({"structure_request": "'yes'"}))
        self.assertFalse(structure_requested({"structure_request": "0"}))
        self.assertFalse(structure_requested({}))

    def test_cache_key_payload_carries_the_flag(self):
        with patch.dict("os.environ", ENV, clear=False):
            on = _cycle_cache_payload(dict(intuition="x", structure_request=True), "x", {})
            off = _cycle_cache_payload(dict(intuition="x"), "x", {})
        self.assertIs(on["structure_request"], True)
        self.assertIs(off["structure_request"], False)


class StructurerInTheRealCycle(unittest.IsolatedAsyncioTestCase):
    async def test_flag_structures_once_and_keeps_both_requests(self):
        fake = _fake(STRUCTURED)
        result = await _run(fake, {"structure_request": True, "objective": "Decide the sign."})
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(len(fake.seen["structure"]), 1)
            call = fake.seen["structure"][0]
            self.assertEqual(call["intuition"], RAW)
            self.assertEqual(call["objective"], "Decide the sign.")
            self.assertEqual(call["provider"], "codex_cli")          # default: the synthesizer
            direction = fake.seen["conjecture_intuition"]
            self.assertIn("STRUCTURED RESEARCH DIRECTION", direction)
            self.assertIn("BOUNDED CLAIM: For a free scalar field", direction)
            self.assertIn("RAW REQUEST (context, not the direction):\n" + RAW, direction)
            request = result["request"]
            self.assertEqual(request["original"], RAW)
            self.assertEqual(request["structured"], STRUCTURED.strip())
            self.assertTrue(request["complete"])
            self.assertEqual(request["required_inputs"], ["a frozen fixed point U0", "the actuator ansatz"])
            self.assertEqual(request["provider"], "codex_cli")
            self.assertEqual(result["shared_goal"], "Decide the sign.")   # objective untouched
            self.assertIn("structure", result["timings"])
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["request"]["original"], RAW)
            self.assertTrue(checkpoint["intuition"].startswith("STRUCTURED RESEARCH DIRECTION"))
        finally:
            remove_cycle_artifacts(result)

    async def test_without_the_flag_nothing_changes(self):
        fake = _fake(STRUCTURED)
        result = await _run(fake, {})
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(fake.seen["structure"], [])
            self.assertNotIn("request", result)
            self.assertNotIn("structure", result["timings"])
            self.assertIn("CURRENT RESEARCH DIRECTION:\n" + RAW, fake.seen["conjecture_intuition"])
        finally:
            remove_cycle_artifacts(result)

    async def test_structurer_failure_falls_back_to_the_raw_request(self):
        fake = _fake("API_ERROR: 'gpt-5.6-sol': usage limit")
        result = await _run(fake, {"structure_request": True})
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertIn("CURRENT RESEARCH DIRECTION:\n" + RAW, fake.seen["conjecture_intuition"])
            self.assertNotIn("STRUCTURED RESEARCH DIRECTION", fake.seen["conjecture_intuition"])
            self.assertTrue(result["request"]["structurer_error"].startswith("API_ERROR:"))
            self.assertNotIn("structured", result["request"])
        finally:
            remove_cycle_artifacts(result)

    async def test_reply_without_a_bounded_claim_is_not_adopted(self):
        fake = _fake("I cannot structure this request without the missing data files.")
        result = await _run(fake, {"structure_request": True})
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertIn("CURRENT RESEARCH DIRECTION:\n" + RAW, fake.seen["conjecture_intuition"])
            self.assertNotIn("STRUCTURED RESEARCH DIRECTION", fake.seen["conjecture_intuition"])
            self.assertIn("no BOUNDED CLAIM heading", result["request"]["structurer_error"])
            self.assertIn("cannot structure", result["request"]["structured_reply"])
            self.assertNotIn("structured", result["request"])
        finally:
            remove_cycle_artifacts(result)

    async def test_a_none_claim_is_not_adopted_either(self):
        fake = _fake("\n".join(f"{h}: none" for h in HEADINGS))
        result = await _run(fake, {"structure_request": True})
        try:
            self.assertIn("no BOUNDED CLAIM heading", result["request"]["structurer_error"])
            self.assertNotIn("STRUCTURED RESEARCH DIRECTION", fake.seen["conjecture_intuition"])
        finally:
            remove_cycle_artifacts(result)

    async def test_provider_override(self):
        fake = _fake(STRUCTURED)
        with patch.dict("os.environ", {"ASTRA_STRUCTURER_PROVIDER": "agy_cli"}, clear=False):
            result = await _run(fake, {"structure_request": True})
        try:
            self.assertEqual(fake.seen["structure"][0]["provider"], "agy_cli")
            self.assertEqual(result["request"]["provider"], "agy_cli")
        finally:
            remove_cycle_artifacts(result)


class ServerExposesTheFlag(unittest.TestCase):
    def test_both_cycle_tools_accept_structure_request(self):
        from tests.test_mcp_server_concurrency import server_module

        for tool in (server_module.astra_cycle, server_module.astra_cycle_submit):
            with self.subTest(tool=tool.__name__):
                parameter = inspect.signature(tool).parameters["structure_request"]
                self.assertIs(parameter.default, False)
                self.assertIn("structure_request", tool.__doc__)


if __name__ == "__main__":
    unittest.main()
