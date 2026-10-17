"""The planner sizes the code author: tier ladder and ceiling (1.1.22)."""
import os
import unittest
from unittest.mock import patch

from agents.translator import parse_complexity
from astra_tool import _author_tier, apply_max_mode, restore_max_mode
from tests.cycle_artifacts import remove_cycle_artifacts
from tests.test_input_request_cycle import DECIDED_CODE, _fake, _run

PLAN = "1. PROPOSITION: P\n8. RISKS: a naive hard-coded check\n9. COMPLEXITY: {}"


class Parse(unittest.TestCase):
    def test_reads_the_class(self):
        self.assertEqual(parse_complexity(PLAN.format("hard")), "hard")
        self.assertEqual(parse_complexity("COMPLEXITY: Moderate"), "moderate")
        self.assertEqual(parse_complexity("**COMPLEXITY:** simple"), "simple")
        self.assertIsNone(parse_complexity("no class here"))

    def test_last_mention_wins(self):
        plan = "8. RISKS: COMPLEXITY: simple would be wrong here\n9. COMPLEXITY: hard"
        self.assertEqual(parse_complexity(plan), "hard")


class Tier(unittest.TestCase):
    def test_hard_and_moderate_start_on_opus_with_longer_ceilings(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("ASTRA_AUTHOR_MODELS_HARD", "ASTRA_TRANSLATOR_TIMEOUT_HARD",
                        "ASTRA_AUTHOR_MODELS_MODERATE", "ASTRA_TRANSLATOR_TIMEOUT_MODERATE"):
                os.environ.pop(key, None)
            hard = _author_tier(PLAN.format("hard"))
            moderate = _author_tier(PLAN.format("moderate"))
        self.assertEqual(hard["models"].split(",")[0], "claude-opus-5-5@high")
        self.assertEqual(hard["timeout"], 1500)
        self.assertEqual(moderate["timeout"], 1200)

    def test_simple_or_unknown_keeps_the_configured_author(self):
        self.assertEqual(_author_tier(PLAN.format("simple")), {"complexity": "simple"})
        self.assertIsNone(_author_tier("plan without a class"))

    def test_env_overrides_and_max_mode_keeps_its_author(self):
        env = {"ASTRA_AUTHOR_MODELS_HARD": "claude-fable-5-1@high",
               "ASTRA_TRANSLATOR_TIMEOUT_HARD": "2000"}
        with patch.dict(os.environ, env, clear=False):
            tier = _author_tier(PLAN.format("hard"))
            max_tier = _author_tier(PLAN.format("hard"), max_mode=True)
        self.assertEqual((tier["models"], tier["timeout"]), ("claude-fable-5-1@high", 2000))
        self.assertNotIn("models", max_tier)
        self.assertEqual(max_tier["timeout"], 2000)


class MaxModeAuthor(unittest.TestCase):
    def test_max_mode_author_runs_at_high_and_never_steps_down(self):
        with patch.dict(os.environ, {"ASTRA_REVIEWER_FOLLOWUP_MODELS": "gpt-6-luna@xhigh"}):
            snap = apply_max_mode({"max_mode": True})
            try:
                self.assertEqual(os.environ["ASTRA_TRANSLATOR_MODELS"], "claude-opus-5-5@high")
                self.assertEqual(os.environ["ASTRA_REVIEWER_FOLLOWUP_MODELS"], "")
            finally:
                restore_max_mode(snap)
            self.assertEqual(os.environ["ASTRA_REVIEWER_FOLLOWUP_MODELS"], "gpt-6-luna@xhigh")


class Cycle(unittest.IsolatedAsyncioTestCase):
    async def _cycle(self, complexity):
        fake = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "sign check failed"})
        authors = []

        async def plan_validation(self, translation_input):
            return PLAN.format(complexity)

        original = fake.translate_to_code

        async def translate_to_code(self, conjecture, **kwargs):
            authors.append((self.cli_models, self.cli_timeout))
            return await original(self, conjecture, **kwargs)

        fake.plan_validation = plan_validation
        fake.translate_to_code = translate_to_code
        env = {"ASTRA_CODE_REVIEW": "0", "ASTRA_AUTHOR_SPLIT": "1",
               "ASTRA_TRANSLATOR_MODELS": "sonnet@high,claude-opus-5-5@high",
               "ASTRA_TRANSLATOR_TIMEOUT": "720"}
        with patch.dict(os.environ, env, clear=False):
            for key in ("ASTRA_AUTHOR_MODELS_HARD", "ASTRA_TRANSLATOR_TIMEOUT_HARD"):
                os.environ.pop(key, None)
            result = await _run(fake, {})
        return result, authors

    async def test_hard_plan_skips_sonnet_and_lengthens_the_ceiling(self):
        result, authors = await self._cycle("hard")
        try:
            models, timeout = authors[0]
            self.assertTrue(models.startswith("claude-opus-5-5@high"), models)
            self.assertGreater(timeout, 720)
            self.assertEqual(result.get("complexity"), "hard")
        finally:
            remove_cycle_artifacts(result)

    async def test_simple_plan_keeps_sonnet_first(self):
        result, authors = await self._cycle("simple")
        try:
            self.assertTrue(authors[0][0].startswith("sonnet@high"))
            self.assertEqual(result.get("complexity"), "simple")
        finally:
            remove_cycle_artifacts(result)


if __name__ == "__main__":
    unittest.main()


class SimpleCodexTier(unittest.IsolatedAsyncioTestCase):
    """1.1.23: a simple plan moves the Codex judges to the Luna ladder."""

    async def _cycle(self, complexity, switch):
        fake = _fake(DECIDED_CODE, {"status": "REFUTED", "reasoning": "sign check failed"})
        seen = {}

        async def plan_validation(self, translation_input):
            return PLAN.format(complexity)

        original_analyze = fake.analyze_results

        async def analyze_results(self, *args, **kwargs):
            seen["analyst"] = self.cli_models
            return await original_analyze(self, *args, **kwargs)

        fake.plan_validation = plan_validation
        fake.analyze_results = analyze_results
        env = {"ASTRA_CODE_REVIEW": "0", "ASTRA_AUTHOR_SPLIT": "1", "ASTRA_SIMPLE_CODEX_TIER": switch,
               "ASTRA_ANALYST_MODELS": "gpt-6.1-sol@high,gpt-6-luna@high"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("ASTRA_ANALYST_MODELS_SIMPLE", None)
            result = await _run(fake, {})
        return result, seen

    async def test_simple_plan_puts_the_analyst_on_luna(self):
        result, seen = await self._cycle("simple", "1")
        try:
            self.assertTrue(str(seen.get("analyst")).startswith("gpt-6-luna@high"), seen)
            self.assertEqual(result.get("codex_tier"), "simple")
        finally:
            remove_cycle_artifacts(result)

    async def test_hard_plan_or_switch_off_keep_sol(self):
        for complexity, switch in (("hard", "1"), ("simple", "0")):
            result, seen = await self._cycle(complexity, switch)
            try:
                self.assertTrue(str(seen.get("analyst")).startswith("gpt-6.1-sol@high"), (complexity, switch, seen))
                self.assertNotIn("codex_tier", result)
            finally:
                remove_cycle_artifacts(result)
