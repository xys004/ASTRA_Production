import unittest
from unittest.mock import patch

from astra_tool import _cycle_cache_payload
from core.architecture_contract import (
    audit_production_architecture,
    production_manifest,
)


class ArchitectureContractTests(unittest.TestCase):
    def canonical_environment(self):
        return {
            "ASTRA_CONJECTURE_PROVIDER": "codex_cli,agy_cli",
            "ASTRA_SYNTH_PROVIDER": "codex_cli",
            "ASTRA_TRANSLATOR_PROVIDER": "claude_cli",
            "ASTRA_REVIEWER_PROVIDER": "codex_cli",
            "ASTRA_ANALYST_PROVIDER": "codex_cli",
            "ASTRA_NAVIGATOR_PROVIDER": "agy_cli",
            "ASTRA_CODEX_MODELS": "gpt-5.6-sol",
            "ASTRA_CLAUDE_MODELS": "claude-opus-4-8,sonnet",
            "ASTRA_AGY_MODELS": "gemini-3.1-pro-high,gemini-3.5-flash-high",
            "ASTRA_CODEX_REASONING": "xhigh",
            "ASTRA_AGY_EFFORT": "high",
            "ASTRA_CODE_REVIEW": "1",
            "ASTRA_NAVIGATE_AFTER_CYCLE": "1",
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
        }

    def test_canonical_three_agent_topology_passes(self):
        audit = audit_production_architecture(
            self.canonical_environment(),
            check_binaries=False,
        )
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["required_failures"], [])

    def test_role_drift_fails_closed(self):
        env = self.canonical_environment()
        env["ASTRA_TRANSLATOR_PROVIDER"] = "codex_cli"
        audit = audit_production_architecture(env, check_binaries=False)
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("production_role_map", audit["required_failures"])

    def test_weaker_agy_effort_fails_contract(self):
        env = self.canonical_environment()
        env["ASTRA_AGY_EFFORT"] = "medium"
        audit = audit_production_architecture(env, check_binaries=False)
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("agy_effort", audit["required_failures"])

    def test_weaker_phase_override_fails_effective_model_contract(self):
        env = self.canonical_environment()
        env["ASTRA_TRANSLATOR_MODELS"] = "sonnet"
        audit = audit_production_architecture(env, check_binaries=False)
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn(
            "author_effective_model",
            audit["required_failures"],
        )

    def test_required_local_engine_fails_closed_when_missing(self):
        env = self.canonical_environment()
        env["ASTRA_REQUIRED_LOCAL_ENGINES"] = "cadabra"
        cas = {
            "sage": "wsl -d Debian -- sage",
            "maxima": "wsl -d Debian -- maxima",
            "cadabra": None,
            "lean4": None,
        }
        with patch(
            "core.engine_router.available_cas",
            return_value=cas,
        ):
            with patch(
                "core.architecture_contract.shutil.which",
                return_value="available",
            ):
                with patch(
                    "core.architecture_contract.importlib.util.find_spec",
                    return_value=object(),
                ):
                    audit = audit_production_architecture(
                        env,
                        check_binaries=True,
                    )
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn(
            "scientific_engine_cadabra",
            audit["required_failures"],
        )

    def test_required_local_engines_are_part_of_manifest(self):
        env = self.canonical_environment()
        env["ASTRA_REQUIRED_LOCAL_ENGINES"] = "z3,sagemath"
        manifest = production_manifest(env)
        self.assertEqual(
            manifest["controls"]["required_local_engines"],
            ["z3", "sagemath"],
        )

    def test_cycle_cache_is_sensitive_to_reflexive_thread_context(self):
        env = self.canonical_environment()
        providers = {
            "conjecture": ["codex_cli", "agy_cli"],
            "translator": "claude_cli",
            "reviewer": "codex_cli",
            "analyst": "codex_cli",
            "navigator": "agy_cli",
            "synth": "codex_cli",
        }
        request = {
            "intuition": "Revisit the boundary case.",
            "axiomatic_base": "A",
            "thread_summary": "Cycle 1 refuted the smooth ansatz.",
            "cycles_since_milestone": 1,
        }
        with patch.dict("os.environ", env, clear=False):
            first = _cycle_cache_payload(request, "Shared objective", providers)
            request = {
                **request,
                "thread_summary": (
                    "Cycle 1 refuted the smooth ansatz. "
                    "Cycle 2 validated the distributional limit."
                ),
                "cycles_since_milestone": 2,
            }
            second = _cycle_cache_payload(request, "Shared objective", providers)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
