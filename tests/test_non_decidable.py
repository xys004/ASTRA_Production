"""NON_DECIDABLE: a validator that cannot be instantiated ends the cycle with
the list of missing inputs instead of CODE_ERROR plus two blind retries.

Regression for cycle pid 32808 (2026-09-09): the validator printed
``RESULT: NON-DECIDABLE`` with ``missing:`` lines and exited 3; the analyst
mapped it to CODE_ERROR and the retry loop regenerated it twice.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _combine_verdicts, _do_cycle
from core.campaign_executor import map_cycle_outcome
from core.campaign_models import ClaimStatus, EvidenceOutcome, OperationStatus
from core.llm_client import ASTRAIntelligence
from core.non_decidable import NON_DECIDABLE, detect_non_decidable, resolve_non_decidable
from tests.cycle_artifacts import remove_cycle_artifacts

REAL_32808_STDOUT = """RESULT: NON-DECIDABLE (this cycle) -- decisive inputs not predeclared:
    missing: A_mat
    missing: gauge_source_U0
    missing: char_outer_BC
    missing: tau_floors
    missing: ansatz_metric
    missing: U0_cartesian
The conjecture makes the cycle NON-DECIDABLE by its one explicit rule.
"""
PROTOCOL_STDOUT = "VERDICT: NON-DECIDABLE\nMISSING: a frozen fixed point U0\nMISSING: the actuator ansatz\n"
ND_CODE = (
    "import sys\n"
    "print('VERDICT: NON-DECIDABLE')\n"
    "print('MISSING: a frozen fixed point U0')\n"
    "print('MISSING: the actuator ansatz')\n"
    "sys.exit(3)\n"
)


class Detection(unittest.TestCase):
    def test_real_32808_output_is_detected_with_its_inputs(self):
        found = detect_non_decidable({"stdout": REAL_32808_STDOUT, "exit_code": 3})
        self.assertIsNotNone(found)
        self.assertEqual(found["missing_inputs"][:2], ["A_mat", "gauge_source_U0"])
        self.assertEqual(len(found["missing_inputs"]), 6)
        self.assertEqual(found["exit_code"], 3)

    def test_protocol_output_and_variants(self):
        self.assertEqual(
            detect_non_decidable({"stdout": PROTOCOL_STDOUT})["missing_inputs"],
            ["a frozen fixed point U0", "the actuator ansatz"],
        )
        self.assertIsNotNone(detect_non_decidable({"stdout": "verdict: non_decidable\nmissing: U0\n"}))
        self.assertIsNotNone(detect_non_decidable({"stdout": "  VERDICT : NONDECIDABLE\nMISSING: x"}))

    def test_a_verdict_or_no_marker_or_no_missing_line_is_not_a_declaration(self):
        self.assertIsNone(detect_non_decidable({"stdout": "CHECK a: OK\nVERDICT: PASS\n"}))
        self.assertIsNone(detect_non_decidable({"stdout": "VERDICT: NON-DECIDABLE\nVERDICT: FAIL\n"}))
        self.assertIsNone(detect_non_decidable({"stdout": "The claim may be non-decidable.\n"}))
        # A bare marker names nothing missing: a crash next to it stays a crash.
        self.assertIsNone(detect_non_decidable({"stdout": "VERDICT: NON-DECIDABLE\n", "exit_code": 1}))
        self.assertIsNone(detect_non_decidable({"stdout": "result: non-decidable region found at k=2\n"}))
        self.assertIsNone(detect_non_decidable({"stdout": ""}))
        self.assertIsNone(detect_non_decidable({}))


class Resolution(unittest.TestCase):
    DECL = {"declared_by": "validator", "missing_inputs": ["U0"], "exit_code": 3}

    def test_analyst_agreement_stops_and_merges_inputs(self):
        analysis = {"status": NON_DECIDABLE, "reasoning": "inputs absent",
                    "missing_inputs": ["A_mat"], "corrected_code": "x", "deferred_items": ["paper"]}
        out = resolve_non_decidable(analysis, self.DECL, 1)
        self.assertEqual(out["status"], NON_DECIDABLE)
        self.assertEqual(out["missing_inputs"], ["U0", "A_mat"])
        self.assertNotIn("corrected_code", out)
        self.assertEqual(out["goal_coverage"], "PARTIAL")
        self.assertEqual(out["deferred_items"],
                         ["paper", "Provide the missing input: U0", "Provide the missing input: A_mat"])
        self.assertEqual(out["non_decidable"]["declarations"], 1)
        self.assertIn("hint", out["non_decidable"])

    def test_decisive_analyst_status_is_overridden(self):
        for status in ("VALIDATED", "REFUTED"):
            out = resolve_non_decidable({"status": status, "reasoning": "r"}, self.DECL, 1)
            self.assertEqual(out["status"], NON_DECIDABLE, status)
            self.assertIn("no oracle verdict", out["reasoning"])

    def test_first_code_error_keeps_one_retry_second_declaration_stops(self):
        first = resolve_non_decidable({"status": "CODE_ERROR", "corrected_code": "y"}, self.DECL, 1)
        self.assertEqual(first["status"], "CODE_ERROR")
        self.assertEqual(first["corrected_code"], "y")
        self.assertIn("one retry allowed", first["non_decidable"]["resolution"])
        second = resolve_non_decidable({"status": "CODE_ERROR", "corrected_code": "z"}, self.DECL, 2)
        self.assertEqual(second["status"], NON_DECIDABLE)
        self.assertNotIn("corrected_code", second)
        self.assertEqual(second["non_decidable"]["declarations"], 2)

    def test_no_retry_available_finalizes_instead_of_half_recording(self):
        out = resolve_non_decidable({"status": "CODE_ERROR", "corrected_code": "y"}, self.DECL, 1,
                                    retry_available=False)
        self.assertEqual(out["status"], NON_DECIDABLE)
        self.assertNotIn("corrected_code", out)
        self.assertIn("no retry is available", out["non_decidable"]["resolution"])

    def test_unexpected_analyst_status_keeps_the_declaration_as_provenance(self):
        out = resolve_non_decidable({"status": "API_ERROR", "reasoning": "quota"}, self.DECL, 1)
        self.assertEqual(out["status"], "API_ERROR")
        self.assertEqual(out["missing_inputs"], ["U0"])
        self.assertIn("left as is", out["non_decidable"]["resolution"])

    def test_no_declaration_leaves_the_analysis_alone_or_downgrades(self):
        same = resolve_non_decidable({"status": "CODE_ERROR", "reasoning": "r"}, None, 0)
        self.assertEqual(same, {"status": "CODE_ERROR", "reasoning": "r"})
        undeclared = resolve_non_decidable({"status": NON_DECIDABLE, "missing_inputs": ["U0"]}, None, 0)
        self.assertEqual(undeclared["status"], "CODE_ERROR")
        self.assertEqual(undeclared["missing_inputs"], ["U0"])

    def test_conservative_consensus_ranks_it_between_code_error_and_refuted(self):
        merged = _combine_verdicts([("a", {"status": "CODE_ERROR"}), ("b", {"status": NON_DECIDABLE})])
        self.assertEqual(merged["status"], NON_DECIDABLE)
        merged = _combine_verdicts([("a", {"status": NON_DECIDABLE}), ("b", {"status": "REFUTED"})])
        self.assertEqual(merged["status"], "REFUTED")
        merged = _combine_verdicts([("a", {"status": "VALIDATED"}), ("b", {"status": NON_DECIDABLE})])
        self.assertEqual(merged["status"], NON_DECIDABLE)

    def test_campaign_mapping(self):
        axes = map_cycle_outcome({"status": NON_DECIDABLE, "goal_coverage": {"status": "partial"},
                                  "code_review": {"status": "APPROVED"}})
        self.assertIs(axes.operation_status, OperationStatus.COMPLETED)
        self.assertIs(axes.claim_status, ClaimStatus.NOT_TESTED)
        self.assertIs(axes.evidence_outcome, EvidenceOutcome.FORMALIZATION_FAILURE)

    def test_prompts_carry_the_protocol(self):
        from agents.analyst import REFUTATION_ANALYST_PROMPT
        from agents.translator import FORMAL_TRANSLATOR_VNEXT_ADDENDUM

        self.assertIn('"NON_DECIDABLE"', REFUTATION_ANALYST_PROMPT)
        self.assertIn("missing_inputs", REFUTATION_ANALYST_PROMPT)
        self.assertIn("VERDICT: NON-DECIDABLE", FORMAL_TRANSLATOR_VNEXT_ADDENDUM)
        self.assertIn("MISSING: <input>", FORMAL_TRANSLATOR_VNEXT_ADDENDUM)
        self.assertIn("exit with code 3", FORMAL_TRANSLATOR_VNEXT_ADDENDUM)
        # Placeholders first, non-decidable last, and no advertised free exit.
        rule = FORMAL_TRANSLATOR_VNEXT_ADDENDUM.split("6. NON-DECIDABLE INPUTS")[1]
        self.assertLess(rule.index("symbolic placeholders"), rule.index("VERDICT: NON-DECIDABLE"))
        self.assertNotIn("does not retry", rule)
        from agents.reviewer import CODE_REVIEWER_VNEXT_PROMPT

        self.assertIn("VERDICT: NON-DECIDABLE", CODE_REVIEWER_VNEXT_PROMPT)
        self.assertIn("lazy non-decidable exit is a defect", CODE_REVIEWER_VNEXT_PROMPT)


def _analyst_client(reply: str):
    client = object.__new__(ASTRAIntelligence)
    client.provider = "codex_cli"
    client.api_key = "x"

    async def _call_api(_system, _user):
        return reply

    client._call_api = _call_api
    return client


class AnalystParsing(unittest.IsolatedAsyncioTestCase):
    async def test_analyst_may_confirm_only_a_declared_non_decidability(self):
        reply = json.dumps({"status": "NON_DECIDABLE", "reasoning": "inputs absent",
                            "missing_inputs": ["U0", " ansatz "]})
        declared = await _analyst_client(reply).analyze_results(
            "c", {"stdout": PROTOCOL_STDOUT, "stderr": "", "exit_code": 3})
        self.assertEqual(declared["status"], "NON_DECIDABLE")
        self.assertEqual(declared["missing_inputs"], ["U0", "ansatz"])
        undeclared = await _analyst_client(reply).analyze_results(
            "c", {"stdout": "", "stderr": "NameError: U0 is not defined", "exit_code": 1})
        self.assertEqual(undeclared["status"], "CODE_ERROR")
        self.assertIn("declared no VERDICT: NON-DECIDABLE", undeclared["reasoning"])
        self.assertEqual(undeclared["missing_inputs"], ["U0", "ansatz"])   # kept as a hint

    async def test_declared_validator_keeps_a_decisive_analyst_status_for_the_override(self):
        """exit 3 is a crash to the client; with the declaration present the
        parsed VALIDATED must reach core/non_decidable.py, which overrides it,
        instead of being rewritten to CODE_ERROR (which would allow retries)."""
        reply = json.dumps({"status": "VALIDATED", "reasoning": "Looks fine."})
        out = await _analyst_client(reply).analyze_results(
            "c", {"stdout": PROTOCOL_STDOUT, "stderr": "", "exit_code": 3})
        self.assertEqual(out["status"], "VALIDATED")
        undeclared = await _analyst_client(reply).analyze_results(
            "c", {"stdout": "", "stderr": "Traceback", "exit_code": 1})
        self.assertEqual(undeclared["status"], "CODE_ERROR")

    async def test_simulated_client_follows_the_declaration(self):
        client = _analyst_client("unused")
        client.api_key = None
        out = await client.analyze_results("c", {"stdout": PROTOCOL_STDOUT, "stderr": "", "exit_code": 3})
        self.assertEqual(out["status"], "NON_DECIDABLE")
        self.assertEqual(out["missing_inputs"], ["a frozen fixed point U0", "the actuator ansatz"])


PROVIDERS = {
    "conjecture": "codex_cli",
    "translator": "claude_cli",
    "reviewer": "codex_cli",
    "analyst": "codex_cli",
    "navigator": "agy_cli",
    "synth": "codex_cli",
}
APPROVED = {"status": "APPROVED", "reasoning": "Honest non-decidable validator.",
            "revision_instructions": "", "coverage": ["inputs"], "defect_labels": [],
            "runtime_checks": []}


def _fake(analyses, patch_status="APPLIED"):
    class FakeIntelligence:
        calls = {"translations": 0, "patches": 0, "analyses": 0}

        def __init__(self, provider, cli_models=None, cli_timeout=None):
            self.provider = provider
            self.cli_models = cli_models
            self.cli_timeout = cli_timeout
            self.cli_warnings = []
            self.cli_last_model = None
            self.cli_cost_usd = 0.0

        async def generate_conjecture(self, axiomatic_base, intuition):
            return "The fit converges once U0 and the ansatz are frozen."

        async def translate_to_code(self, conjecture, **_kwargs):
            FakeIntelligence.calls["translations"] += 1
            return ND_CODE

        async def repair_validation_code(self, conjecture, previous_code, instructions):
            FakeIntelligence.calls["patches"] += 1
            if patch_status != "APPLIED":
                return {"status": patch_status, "reason": "cannot instantiate U0 from nothing",
                        "edits": [], "code": previous_code}
            return {"status": "APPLIED", "reason": "patched", "edits": [],
                    "code": previous_code + f"# patch {FakeIntelligence.calls['patches']}\n"}

        async def review_validation_code(self, **_kwargs):
            return dict(APPROVED)

        async def analyze_results(self, *_args, **_kwargs):
            index = FakeIntelligence.calls["analyses"]
            FakeIntelligence.calls["analyses"] += 1
            return dict(analyses[min(index, len(analyses) - 1)])

    return FakeIntelligence


async def _run(fake, max_retries="2"):
    env = {
        "ASTRA_CYCLE_CACHE": "0",
        "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
        "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
        "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
        "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
        "ASTRA_MAX_RETRIES": max_retries,
        "ASTRA_ORACLE_MODE": "local",
    }
    with patch.dict("os.environ", env, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=PROVIDERS
    ), patch("core.llm_client.ASTRAIntelligence", fake):
        return await _do_cycle(
            {"action": "cycle", "intuition": "Test the non-decidable outcome.",
             "objective": "Certify the accelerated warp fit.", "cycle_timeout_seconds": 1500}
        )


class NonDecidableInTheRealCycle(unittest.IsolatedAsyncioTestCase):
    async def test_declared_and_confirmed_ends_without_retries(self):
        fake = _fake([{"status": "NON_DECIDABLE", "reasoning": "U0 and the ansatz are absent.",
                       "missing_inputs": ["a frozen fixed point U0"], "goal_coverage": "PARTIAL",
                       "deferred_items": ["the full fit"]}])
        result = await _run(fake)
        try:
            self.assertEqual(result["status"], NON_DECIDABLE, result.get("error"))
            self.assertEqual(result["atomic_status"], NON_DECIDABLE)
            self.assertEqual(result["scientific_status"], NON_DECIDABLE)
            self.assertEqual(result["oracle_verdict"], "NONE")
            self.assertEqual(result["retries"], 0)
            self.assertEqual(fake.calls["translations"], 1)
            self.assertEqual(fake.calls["patches"], 0)
            self.assertEqual(result["missing_inputs"],
                             ["a frozen fixed point U0", "the actuator ansatz"])
            self.assertEqual(result["non_decidable"]["declarations"], 1)
            self.assertIn("Provide the missing input: the actuator ansatz", result["deferred_claims"])
            self.assertEqual(result["goal_coverage"]["status"], "partial")
            self.assertEqual(result["execution"]["exit_code"], 3)
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["stage"], "done")
            self.assertEqual(checkpoint["result"]["status"], NON_DECIDABLE)
        finally:
            remove_cycle_artifacts(result)

    async def test_analyst_insisting_on_code_error_gets_one_retry_then_stops(self):
        """The 32808 shape: the analyst keeps answering CODE_ERROR with a
        corrected_code. With ASTRA_MAX_RETRIES=2 the old loop retried twice;
        now the second declaration ends the cycle after one retry."""
        fake = _fake([{"status": "CODE_ERROR", "reasoning": "Instantiate U0 symbolically.",
                       "corrected_code": ND_CODE}])
        result = await _run(fake, max_retries="2")
        try:
            self.assertEqual(result["status"], NON_DECIDABLE, result.get("error"))
            self.assertEqual(result["retries"], 1)
            self.assertEqual(fake.calls["analyses"], 2)
            self.assertEqual(result["non_decidable"]["declarations"], 2)
            self.assertIn("2 validators so far in this cycle", result["non_decidable"]["resolution"])
            self.assertEqual(result["missing_inputs"],
                             ["a frozen fixed point U0", "the actuator ansatz"])
        finally:
            remove_cycle_artifacts(result)

    async def test_no_retries_configured_still_ends_as_non_decidable(self):
        fake = _fake([{"status": "CODE_ERROR", "reasoning": "Instantiate U0.", "corrected_code": ND_CODE}])
        result = await _run(fake, max_retries="0")
        try:
            self.assertEqual(result["status"], NON_DECIDABLE, result.get("error"))
            self.assertEqual(result["scientific_status"], NON_DECIDABLE)
            self.assertEqual(result["retries"], 0)
            self.assertIn("no retry is available", result["non_decidable"]["resolution"])
        finally:
            remove_cycle_artifacts(result)

    async def test_author_cannot_patch_confirms_the_declaration(self):
        """Production repair route: the bounded patch says CANNOT_PATCH. That is
        confirmation, not a tool failure: NON_DECIDABLE, not TOOL_ERROR."""
        fake = _fake([{"status": "CODE_ERROR", "reasoning": "Instantiate U0.", "corrected_code": ND_CODE}],
                     patch_status="CANNOT_PATCH")
        result = await _run(fake, max_retries="2")
        try:
            self.assertEqual(result["status"], NON_DECIDABLE, result.get("error"))
            self.assertEqual(fake.calls["patches"], 1)
            self.assertEqual(result["missing_inputs"],
                             ["a frozen fixed point U0", "the actuator ansatz"])
            self.assertNotIn("error", result)
        finally:
            remove_cycle_artifacts(result)

    async def test_validated_without_a_verdict_is_overridden(self):
        fake = _fake([{"status": "VALIDATED", "reasoning": "Looks fine."}])
        result = await _run(fake)
        try:
            self.assertEqual(result["status"], NON_DECIDABLE, result.get("error"))
            self.assertEqual(result["retries"], 0)
            self.assertIn("no oracle verdict", result["analysis"]["reasoning"])
        finally:
            remove_cycle_artifacts(result)


if __name__ == "__main__":
    unittest.main()
