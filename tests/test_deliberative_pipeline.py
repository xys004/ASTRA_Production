import unittest

from astra_tool import _combine_verdicts
from core.llm_client import ASTRAIntelligence


class DeliberativePipelineTests(unittest.IsolatedAsyncioTestCase):
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
