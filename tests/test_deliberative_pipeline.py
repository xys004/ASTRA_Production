import unittest
import json
from unittest.mock import patch

from astra_tool import (
    _combine_verdicts,
    _do_cycle,
    _ensemble_conjecture,
    _escalate_agent_models,
)
from tests.cycle_artifacts import remove_cycle_artifacts
from core.llm_client import ASTRAIntelligence
from agents.conjecture import CONJECTURE_ENGINE_PROMPT


class DeliberativePipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_conjecture_contract_requires_one_atomic_research_step(self):
        self.assertIn("exactly ONE decisive", CONJECTURE_ENGINE_PROMPT)
        self.assertIn("under 200 lines", CONJECTURE_ENGINE_PROMPT)
        self.assertIn("remaining deliverables as deferred", CONJECTURE_ENGINE_PROMPT)

    def test_quality_escalation_promotes_sonnet_to_opus(self):
        agent = type("Agent", (), {})()
        agent.cli_models = "sonnet,claude-opus-4-8"
        self.assertEqual(_escalate_agent_models(agent), "claude-opus-4-8")
        self.assertEqual(agent.cli_models, "claude-opus-4-8")

    def test_quality_escalation_never_downgrades_opus_to_sonnet(self):
        agent = type("Agent", (), {})()
        agent.cli_models = "claude-opus-4-8,sonnet"
        self.assertIsNone(_escalate_agent_models(agent))
        self.assertEqual(agent.cli_models, "claude-opus-4-8,sonnet")

    async def test_preflight_quality_escalation_regenerates_invalid_output(self):
        class FakeIntelligence:
            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None
                self.cli_cost_usd = 0.0

            async def generate_conjecture(self, axiomatic_base, intuition):
                self.cli_last_model = "gpt-5.6-sol"
                return "The candidate is refuted by x = 1."

            async def translate_to_code(self, conjecture, **_kwargs):
                if str(self.cli_models or "").startswith("sonnet"):
                    self.cli_last_model = "sonnet"
                    return "Write operation completed"
                self.cli_last_model = "claude-opus-4-8"
                return (
                    "print('CHECK counterexample: FAIL')\n"
                    "print('VERDICT: FAIL')\n"
                )

            async def review_validation_code(self, **_kwargs):
                return {
                    "status": "APPROVED",
                    "reasoning": "Executable counterexample.",
                    "revision_instructions": "",
                    "coverage": ["counterexample"],
                    "defect_labels": [],
                    "runtime_checks": [],
                }

            async def analyze_results(self, *_args, **_kwargs):
                return {
                    "status": "REFUTED",
                    "reasoning": "Counterexample executed.",
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
            "ASTRA_TRANSLATOR_MODELS": "sonnet,claude-opus-4-8",
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
            "ASTRA_MAX_RETRIES": "0",
            "ASTRA_ORACLE_MODE": "local",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map",
            return_value=providers,
        ), patch(
            "core.llm_client.ASTRAIntelligence",
            FakeIntelligence,
        ):
            result = await _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Test quality escalation.",
                    "cycle_timeout_seconds": 1500,
                }
            )

        self.assertEqual(result["status"], "REFUTED")
        self.assertEqual(
            result["quality_escalations"][0]["translator_now"],
            "claude-opus-4-8",
        )
        self.assertIn("VERDICT: FAIL", result["code"])
        remove_cycle_artifacts(result)

    async def test_rejected_bounded_patch_falls_back_to_regeneration(self):
        class FakeIntelligence:
            translations = 0
            reviews = 0

            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None
                self.cli_cost_usd = 0.0

            async def generate_conjecture(self, axiomatic_base, intuition):
                self.cli_last_model = "gpt-5.6-sol"
                return "The candidate is refuted by x = 0."

            async def translate_to_code(self, conjecture, **_kwargs):
                FakeIntelligence.translations += 1
                self.cli_last_model = (
                    "sonnet"
                    if str(self.cli_models or "").startswith("sonnet")
                    else "claude-opus-4-8"
                )
                return (
                    "print('CHECK counterexample: FAIL')\n"
                    "print('VERDICT: FAIL')\n"
                )

            async def review_validation_code(self, **_kwargs):
                FakeIntelligence.reviews += 1
                if FakeIntelligence.reviews == 1:
                    return {
                        "status": "REVISE",
                        "reasoning": "Tighten the exact witness.",
                        "revision_instructions": "Preserve the witness and clarify it.",
                        "coverage": [],
                        "defect_labels": ["missing_assumption"],
                        "runtime_checks": [],
                    }
                return {
                    "status": "APPROVED",
                    "reasoning": "Exact witness ready.",
                    "revision_instructions": "",
                    "coverage": ["counterexample"],
                    "defect_labels": [],
                    "runtime_checks": [],
                }

            async def repair_validation_code(self, *args, **kwargs):
                return {
                    "status": "REJECTED",
                    "reason": "Patch replaces too much source.",
                    "code": args[1],
                    "edits": [],
                }

            async def analyze_results(self, *_args, **_kwargs):
                return {
                    "status": "REFUTED",
                    "reasoning": "Counterexample executed.",
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
            "ASTRA_TRANSLATOR_MODELS": "sonnet,claude-opus-4-8",
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
            "ASTRA_MAX_RETRIES": "0",
            "ASTRA_ORACLE_MODE": "local",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map",
            return_value=providers,
        ), patch(
            "core.llm_client.ASTRAIntelligence",
            FakeIntelligence,
        ):
            result = await _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Test rejected patch regeneration.",
                    "cycle_timeout_seconds": 1500,
                }
            )

        self.assertEqual(result["status"], "REFUTED")
        self.assertEqual(FakeIntelligence.translations, 2)
        self.assertEqual(FakeIntelligence.reviews, 2)
        self.assertEqual(result["validator_model_patch_history"][0]["status"], "REJECTED")
        remove_cycle_artifacts(result)

    async def test_failed_conjecture_ensemble_preserves_provider_errors(self):
        async def fake_generate(_self, axiomatic_base, intuition):
            return "API_ERROR: respuesta vacia (posible tope de cuota)"

        with patch.object(
            ASTRAIntelligence,
            "generate_conjecture",
            fake_generate,
        ):
            error, _used, trace = await _ensemble_conjecture(
                ["agy_cli", "agy_cli"],
                "axioms",
                "problem",
                30,
                "agy_cli",
            )

        self.assertIn("agy_cli=API_ERROR: respuesta vacia", error)
        self.assertEqual(trace["proposals"], [])

    async def test_clean_pass_still_calls_independent_analyst(self):
        analyst = ASTRAIntelligence(provider="codex_cli")
        prompts = []

        async def fake_call(_system, user):
            prompts.append(user)
            return (
                '{"status":"CODE_ERROR",'
                '"reasoning":"validator omits a decisive assumption"}'
            )

        analyst._call_api = fake_call
        result = await analyst.analyze_results(
            "For all real x, x+x=2*x",
            {
                "exit_code": 0,
                "stdout": "CHECK symbolic: OK\nVERDICT: PASS",
                "stderr": "",
                "validation_code": "print('VERDICT: PASS')",
                "code_review": {"status": "APPROVED"},
            },
            shared_goal="Establish the identity without circular validation.",
        )

        self.assertTrue(prompts)
        self.assertIn("VALIDATION SCRIPT", prompts[0])
        self.assertEqual(result["status"], "CODE_ERROR")

    async def test_reviewer_normalizes_non_json_to_revision(self):
        reviewer = ASTRAIntelligence(provider="codex_cli")

        async def fake_call(_system, _user):
            return "The script needs a real failure path."

        reviewer._call_api = fake_call
        result = await reviewer.review_validation_code(
            "Prove an identity",
            "For all x, x=x",
            "print('VERDICT: PASS')",
        )
        self.assertEqual(result["status"], "REVISE")
        self.assertTrue(result["revision_instructions"])

    async def test_vnext1_model_repair_applies_bounded_exact_patch(self):
        repairer = ASTRAIntelligence(provider="claude_cli")
        prompts = []

        async def fake_call(system, user):
            prompts.append((system, user))
            return json.dumps(
                {
                    "status": "PATCH",
                    "reason": "Make indeterminacy explicit.",
                    "edits": [
                        {
                            "old": "ok = expr.is_zero is not True",
                            "new": "ok = expr.is_zero is False",
                        }
                    ],
                }
            )

        repairer._call_api = fake_call
        result = await repairer.repair_validation_code(
            "Prove expr is nonzero",
            (
                "import sympy as sp\n"
                "expr = sp.symbols('x')\n"
                "ok = expr.is_zero is not True\n"
                "print('CHECK explicit:', ok)\n"
                "print('VERDICT: PASS' if ok else 'VERDICT: FAIL')\n"
            ),
            "Unknown cannot pass.",
        )
        self.assertEqual(result["status"], "APPLIED")
        self.assertIn("expr.is_zero is False", result["code"])
        self.assertTrue(prompts)
        self.assertIn("CURRENT VALIDATION SCRIPT", prompts[0][1])

    async def test_reviewer_receives_deterministic_smoke_context(self):
        reviewer = ASTRAIntelligence(provider="codex_cli")
        prompts = []

        async def fake_call(_system, user):
            prompts.append(user)
            return (
                '{"status":"APPROVED","reasoning":"ready",'
                '"revision_instructions":"","coverage":[],'
                '"defect_labels":[],"runtime_checks":[]}'
            )

        reviewer._call_api = fake_call
        result = await reviewer.review_validation_code(
            "Prove an identity",
            "For all x, x=x",
            "print('VERDICT: PASS')",
            static_context={"compiled": True, "missing_modules": []},
        )
        self.assertEqual(result["status"], "APPROVED")
        self.assertIn("DETERMINISTIC COMPILE/IMPORT SMOKE", prompts[0])

    async def test_vnext1_refuses_oversized_patch_context_without_model_call(self):
        repairer = ASTRAIntelligence(provider="claude_cli")
        called = False

        async def fake_call(_system, _user):
            nonlocal called
            called = True
            return "{}"

        repairer._call_api = fake_call
        result = await repairer.repair_validation_code(
            "objective",
            "x = 1\n" * 5000,
            "repair",
        )
        self.assertEqual(result["status"], "CANNOT_PATCH")
        self.assertFalse(called)

    async def test_author_api_error_during_regeneration_keeps_last_real_code(self):
        """A quota failure must not be published as the validator source.

        Historical defect (cycle_20260819_231945_f371): the translator hit its
        weekly limit while REGENERATING after a failed preflight, and the error
        string replaced `code`.  The preflight then reported "unterminated
        string literal at line 1" on the error message itself, and the cycle
        blamed the reviewer for a failure that belonged to the author.
        """

        class FakeIntelligence:
            translations = 0

            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None
                self.cli_cost_usd = 0.0

            async def generate_conjecture(self, axiomatic_base, intuition):
                self.cli_last_model = "gpt-5.6-sol"
                return "The candidate is refuted by x = 1."

            async def translate_to_code(self, conjecture, **_kwargs):
                FakeIntelligence.translations += 1
                self.cli_last_model = "claude-opus-4-8"
                if FakeIntelligence.translations == 1:
                    # Not repairable by the deterministic preflight: forces the
                    # regeneration branch.
                    return "print('unterminated\n"
                return (
                    "API_ERROR: 'claude-opus-4-8': You've hit your weekly limit "
                    "- resets 5am (America/Buenos_Aires)"
                )

            async def review_validation_code(self, **_kwargs):
                return {
                    "status": "REVISE",
                    "reasoning": "Syntax error.",
                    "revision_instructions": "Fix line 1.",
                    "coverage": [],
                    "defect_labels": ["syntax_error"],
                    "runtime_checks": [],
                }

            async def analyze_results(self, *_args, **_kwargs):
                return {"status": "REFUTED", "reasoning": "unused"}

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
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
            "ASTRA_VNEXT_REVIEW_MAX_REVISIONS": "1",
            "ASTRA_REVIEW_MAX_REVISIONS": "1",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
            "ASTRA_MAX_RETRIES": "0",
            "ASTRA_ORACLE_MODE": "local",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map",
            return_value=providers,
        ), patch(
            "core.llm_client.ASTRAIntelligence",
            FakeIntelligence,
        ):
            result = await _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Test author quota failure during regeneration.",
                    "cycle_timeout_seconds": 1500,
                }
            )

        self.assertEqual(result["status"], "TOOL_ERROR")
        # The failure belongs to the author, not to the reviewer that asked for
        # the revision.
        self.assertEqual(result["phase"], "translator")
        self.assertTrue(str(result["error"]).startswith("API_ERROR:"))
        # The regression itself: `code` must still hold the last real source.
        self.assertFalse(str(result.get("code", "")).startswith("API_ERROR:"))
        self.assertIn("unterminated", str(result.get("code", "")))
        remove_cycle_artifacts(result)

    async def test_author_api_error_during_bounded_patch_aborts_immediately(self):
        """A provider failure in the bounded patch is a tool error, not a verdict.

        Sibling of the regeneration defect above.  `repair_validation_code`
        reports a quota failure as `status=API_ERROR`, but the cycle wrapped it
        as "Bounded model patch was not applicable", which (a) dropped the
        `API_ERROR:` prefix every downstream consumer keys on and (b) fell
        through to a regeneration that could only burn another call against the
        same exhausted account.
        """
        valid_validator = (
            "import sympy as sp\n"
            "\n"
            "x = sp.symbols('x')\n"
            "CHECK_1 = sp.simplify(sp.expand((x + 1) ** 2)"
            " - (x ** 2 + 2 * x + 1)) == 0\n"
            "print('CHECK_1 identity:', CHECK_1)\n"
            "print('VERDICT: PASS' if CHECK_1 else 'VERDICT: FAIL')\n"
        )
        quota_error = (
            "API_ERROR: 'claude-opus-4-8': You've hit your weekly limit "
            "- resets 5am (America/Buenos_Aires)"
        )

        class FakeIntelligence:
            translations = 0
            patches = 0

            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None
                self.cli_cost_usd = 0.0

            async def generate_conjecture(self, axiomatic_base, intuition):
                return "The expansion of (x + 1)^2 is x^2 + 2x + 1."

            async def translate_to_code(self, conjecture, **_kwargs):
                FakeIntelligence.translations += 1
                self.cli_last_model = "claude-opus-4-8"
                return valid_validator

            async def review_validation_code(self, **_kwargs):
                # Clean syntax: the reviewer asks for BROADER coverage, which is
                # exactly the case routed to a bounded patch instead of a full
                # regeneration.
                return {
                    "status": "REVISE",
                    "reasoning": "Coverage is too narrow.",
                    "revision_instructions": "Also check x = -1.",
                    "coverage": [],
                    "defect_labels": ["insufficient_coverage"],
                    "runtime_checks": [],
                }

            async def repair_validation_code(self, *_args, **_kwargs):
                FakeIntelligence.patches += 1
                self.cli_last_model = "claude-opus-4-8"
                return {
                    "status": "API_ERROR",
                    "reason": quota_error,
                    "code": valid_validator,
                    "edits": [],
                }

            async def analyze_results(self, *_args, **_kwargs):
                return {"status": "REFUTED", "reasoning": "unused"}

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
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
            "ASTRA_VNEXT_REVIEW_MAX_REVISIONS": "1",
            "ASTRA_REVIEW_MAX_REVISIONS": "1",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
            "ASTRA_MAX_RETRIES": "0",
            "ASTRA_ORACLE_MODE": "local",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map",
            return_value=providers,
        ), patch(
            "core.llm_client.ASTRAIntelligence",
            FakeIntelligence,
        ):
            result = await _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Test author quota failure during bounded patch.",
                    "cycle_timeout_seconds": 1500,
                }
            )

        self.assertEqual(result["status"], "TOOL_ERROR")
        self.assertEqual(result["phase"], "translator")
        # The provider error must reach the caller VERBATIM, prefix included.
        self.assertTrue(str(result["error"]).startswith("API_ERROR:"))
        self.assertIn("weekly limit", str(result["error"]))
        self.assertNotIn("not applicable", str(result["error"]))
        # The last real source survives; the error never becomes `code`.
        self.assertEqual(result.get("code"), valid_validator)
        # And the exhausted account is not asked to regenerate on the way out.
        self.assertEqual(FakeIntelligence.patches, 1)
        self.assertEqual(FakeIntelligence.translations, 1)
        remove_cycle_artifacts(result)

    def test_conservative_analyst_consensus_uses_most_cautious_verdict(self):
        result = _combine_verdicts(
            [
                ("codex_cli", {"status": "VALIDATED", "reasoning": "passes"}),
                ("agy_cli", {"status": "WEAK_PASS", "reasoning": "coverage gap"}),
            ]
        )
        self.assertEqual(result["status"], "WEAK_PASS")
        self.assertEqual(len(result["ensemble"]), 2)


if __name__ == "__main__":
    unittest.main()
