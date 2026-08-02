import unittest
import json
from pathlib import Path
from unittest.mock import patch

from astra_tool import (
    _combine_verdicts,
    _do_cycle,
    _ensemble_conjecture,
    _escalate_agent_models,
)
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
                    "cycle_timeout_seconds": 120,
                }
            )

        self.assertEqual(result["status"], "REFUTED")
        self.assertEqual(
            result["quality_escalations"][0]["translator_now"],
            "claude-opus-4-8",
        )
        self.assertIn("VERDICT: FAIL", result["code"])
        checkpoint = Path(result["checkpoint"])
        if checkpoint.exists():
            checkpoint.unlink()

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
                    "cycle_timeout_seconds": 120,
                }
            )

        self.assertEqual(result["status"], "REFUTED")
        self.assertEqual(FakeIntelligence.translations, 2)
        self.assertEqual(FakeIntelligence.reviews, 2)
        self.assertEqual(result["validator_model_patch_history"][0]["status"], "REJECTED")
        checkpoint = Path(result["checkpoint"])
        if checkpoint.exists():
            checkpoint.unlink()

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
