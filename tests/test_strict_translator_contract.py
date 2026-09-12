"""C0 of the cycle-robustness spec: the opt-in strict certification contract.

The addendum encodes the five wiring defects the independent reviewer rejects,
and it must bind BOTH the from-scratch translator and the bounded repairer --
but only when ASTRA_TRANSLATOR_STRICT_CONTRACT is on, so production is unchanged
by default. The prompt is captured by stubbing _call_api; the stub returns an
API_ERROR so the methods return early without patching anything.
"""
import os
import unittest
from unittest.mock import patch

from agents.translator import (
    FORMAL_PATCH_REPAIR_PROMPT,
    FORMAL_TRANSLATOR_PROMPT,
    FORMAL_TRANSLATOR_STRICT_ADDENDUM,
    parse_strict_flag,
    strict_contract_enabled,
)
from core.architecture_contract import production_manifest
from core.llm_client import ASTRAIntelligence


RULE_MARKERS = (
    "EXECUTED check",                 # 1. no links in comments
    "RELATIONS between symbols",      # 2. decidable signs/domain
    "EXHIBITED POINT",                # 3. strict integrals, no measure bounds
    "NEVER assume the conclusion",    # 4. no self-confirming gates
    "FAIL branch must be reachable",  # 5. falsifiable
)


def _client():
    # Skip __init__ (no network/CLI probing): the methods only need provider.
    c = object.__new__(ASTRAIntelligence)
    c.provider = "claude_cli"
    return c


class AddendumContent(unittest.TestCase):
    def test_all_five_rules_present(self):
        for m in RULE_MARKERS:
            self.assertIn(m, FORMAL_TRANSLATOR_STRICT_ADDENDUM, m)

    def test_addendum_is_not_in_base_prompts_by_default(self):
        self.assertNotIn("STRICT CERTIFICATION CONTRACT", FORMAL_TRANSLATOR_PROMPT)
        self.assertNotIn("STRICT CERTIFICATION CONTRACT", FORMAL_PATCH_REPAIR_PROMPT)


class ManifestAndTranslatorAgreeOnTheFlag(unittest.TestCase):
    """production_manifest()'s provenance stamp and strict_contract_enabled()'s
    actual gate must never disagree, or a cycle's telemetry/cache key would
    record a contract that did not run. Both now delegate to the one
    parse_strict_flag() rule; this asserts that on the exact values an audit
    found disagreeing under the old (generic, deny-list) manifest parser."""

    def test_non_canonical_values_agree(self):
        for raw in ("", "2", "enabled", "TRUE", " 1 ", "'1'", "yes", "off", "0", "no", "banana"):
            with self.subTest(raw=raw):
                env = {"ASTRA_TRANSLATOR_STRICT_CONTRACT": raw}
                manifest_says = production_manifest(env)["controls"]["translator_strict_contract"]
                translator_says = parse_strict_flag(raw)
                self.assertEqual(manifest_says, translator_says, raw)

    def test_empty_value_is_off_on_both_sides(self):
        # The audit's headline case: an empty .env line ("KEY=") must not be
        # stamped strict when the translator in fact ran the base prompt.
        env = {"ASTRA_TRANSLATOR_STRICT_CONTRACT": ""}
        self.assertFalse(production_manifest(env)["controls"]["translator_strict_contract"])
        self.assertFalse(parse_strict_flag(""))


class FlagParsing(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRA_TRANSLATOR_STRICT_CONTRACT", None)
            self.assertFalse(strict_contract_enabled())

    def test_truthy_values_enable(self):
        for v in ("1", "true", "on", "yes", "'1'"):
            with patch.dict(os.environ, {"ASTRA_TRANSLATOR_STRICT_CONTRACT": v}):
                self.assertTrue(strict_contract_enabled(), v)

    def test_falsey_values_disable(self):
        for v in ("0", "false", "off", "no", ""):
            with patch.dict(os.environ, {"ASTRA_TRANSLATOR_STRICT_CONTRACT": v}):
                self.assertFalse(strict_contract_enabled(), v)


class TranslatorBinding(unittest.IsolatedAsyncioTestCase):
    async def _captured_system_prompt(self, flag: str, repair: bool) -> str:
        seen = {}

        async def stub(system_prompt, user_prompt):
            seen["system"] = system_prompt
            return "API_ERROR: stub"

        c = _client()
        with patch.dict(os.environ, {"ASTRA_TRANSLATOR_STRICT_CONTRACT": flag,
                                     "ASTRA_VALIDATOR_REPAIR_VNEXT": "0"}), \
             patch.object(c, "_call_api", stub):
            if repair:
                await c.repair_validation_code("conj", "print('VERDICT: PASS')", "fix it")
            else:
                await c.translate_to_code("conj")
        return seen["system"]

    async def test_translator_gets_addendum_only_when_enabled(self):
        self.assertIn("STRICT CERTIFICATION CONTRACT", await self._captured_system_prompt("1", False))
        self.assertNotIn("STRICT CERTIFICATION CONTRACT", await self._captured_system_prompt("0", False))

    async def test_repairer_gets_addendum_only_when_enabled(self):
        on = await self._captured_system_prompt("1", True)
        self.assertTrue(on.startswith(FORMAL_PATCH_REPAIR_PROMPT[:40]))
        self.assertIn("STRICT CERTIFICATION CONTRACT", on)
        self.assertNotIn("STRICT CERTIFICATION CONTRACT", await self._captured_system_prompt("0", True))


if __name__ == "__main__":
    unittest.main()
