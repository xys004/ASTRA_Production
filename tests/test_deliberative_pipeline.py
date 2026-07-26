import unittest
import json
from unittest.mock import patch

from astra_tool import _combine_verdicts, _ensemble_conjecture
from core.llm_client import ASTRAIntelligence


class DeliberativePipelineTests(unittest.IsolatedAsyncioTestCase):
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
