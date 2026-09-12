import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.cycle_budget import CycleBudget
from core.runtime_resources import (
    acquire_cycle_slot,
    detect_compute_capacity,
    recommended_parallelism,
)
from astra_tool import _do_cycle, _do_submit_cycle
from tests.cycle_artifacts import remove_cycle_artifacts


class CycleBudgetTests(unittest.TestCase):
    def test_phase_timeout_preserves_response_buffer(self):
        now = [0.0]
        budget = CycleBudget(
            100,
            return_buffer_seconds=20,
            clock=lambda: now[0],
        )
        self.assertEqual(budget.phase_timeout(90), 80)
        now[0] = 75
        self.assertEqual(budget.phase_timeout(90), 5)
        now[0] = 82
        self.assertEqual(budget.phase_timeout(90), 1)
        self.assertFalse(budget.can_start())

    def test_persistent_budget_keeps_phase_limit(self):
        budget = CycleBudget(None)
        self.assertEqual(budget.phase_timeout(720), 720)
        self.assertEqual(budget.snapshot()["mode"], "persistent")

    def test_synchronous_cycle_returns_partial_before_outer_kill(self):
        class FakeIntelligence:
            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None

            async def generate_conjecture(self, axiomatic_base, intuition):
                return "A falsifiable conjecture."

            async def translate_to_code(self, conjecture, **_kwargs):
                return f"API_ERROR: timeout tras {self.cli_timeout}s"

        providers = {
            "conjecture": "codex_cli",
            "translator": "claude_cli",
            "analyst": "codex_cli",
            "reviewer": "codex_cli",
            "navigator": "agy_cli",
        }
        env = {
            "ASTRA_CYCLE_CACHE": "0",
            "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
            "ASTRA_ANALYST_PROVIDER": "codex_cli",
            "ASTRA_CONJECTURE_TIMEOUT": "420",
            "ASTRA_TRANSLATOR_TIMEOUT": "720",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "core.preflight.phase_provider_map",
            return_value=providers,
        ), patch(
            "core.llm_client.ASTRAIntelligence",
            FakeIntelligence,
        ):
            result = asyncio.run(
                _do_cycle(
                    {
                        "action": "cycle",
                        "intuition": "Test the deadline.",
                        "cycle_timeout_seconds": 80,
                        "cycle_return_buffer_seconds": 60,
                    }
                )
            )
            persistent_result = asyncio.run(
                _do_cycle(
                    {
                        "action": "cycle",
                        "intuition": "Test the persistent deadline.",
                        "persistent_cycle": True,
                        "cycle_timeout_seconds": 80,
                        "cycle_return_buffer_seconds": 60,
                    }
                )
            )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["phase"], "translator")
        self.assertEqual(result["conjecture"], "A falsifiable conjecture.")
        checkpoint = Path(result["checkpoint"])
        self.assertTrue(checkpoint.exists())
        remove_cycle_artifacts(result)
        self.assertEqual(persistent_result["status"], "PARTIAL")
        self.assertEqual(persistent_result["phase"], "translator")
        persistent_checkpoint = Path(persistent_result["checkpoint"])
        self.assertTrue(persistent_checkpoint.exists())
        remove_cycle_artifacts(persistent_result)

    def test_checkpoint_stamps_the_strict_contract_flag_on_a_failed_cycle(self):
        # Regression for the cycle-robustness spec's 'Transversal: procedencia'
        # guarantee: production_manifest() must reach the on-disk checkpoint
        # from EVERY save this cycle makes, not only a successful 'done' one.
        # This drives the REAL astra_tool checkpoint machinery (checkpoint_state
        # / _save_cycle_checkpoint) end to end -- unlike
        # tests/test_cycle_telemetry.py, whose fixtures stuff an 'architecture'
        # block into hand-built dicts and so cannot detect a regression in
        # astra_tool.py itself (an adversarial audit flagged exactly this gap:
        # a prior version of the fix stamped only the final result, leaving
        # every tool_error/failed/partial cycle -- what the strict-translator
        # overlay exists to reduce -- with no record of which contract ran).
        class FakeIntelligence:
            def __init__(self, provider, cli_models=None, cli_timeout=None):
                self.provider = provider
                self.cli_models = cli_models
                self.cli_timeout = cli_timeout
                self.cli_warnings = []
                self.cli_last_model = None

            async def generate_conjecture(self, axiomatic_base, intuition):
                return "A falsifiable conjecture."

            async def translate_to_code(self, conjecture, **_kwargs):
                return f"API_ERROR: timeout tras {self.cli_timeout}s"

        providers = {
            "conjecture": "codex_cli",
            "translator": "claude_cli",
            "analyst": "codex_cli",
            "reviewer": "codex_cli",
            "navigator": "agy_cli",
        }
        base_env = {
            "ASTRA_CYCLE_CACHE": "0",
            "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
            "ASTRA_ANALYST_PROVIDER": "codex_cli",
            "ASTRA_CONJECTURE_TIMEOUT": "420",
            "ASTRA_TRANSLATOR_TIMEOUT": "720",
        }

        def _run_and_read_checkpoint(strict_value):
            env = {**base_env, "ASTRA_TRANSLATOR_STRICT_CONTRACT": strict_value}
            with patch.dict("os.environ", env, clear=False), patch(
                "core.preflight.phase_provider_map",
                return_value=providers,
            ), patch(
                "core.llm_client.ASTRAIntelligence",
                FakeIntelligence,
            ):
                result = asyncio.run(
                    _do_cycle(
                        {
                            "action": "cycle",
                            "intuition": "Test checkpoint provenance under the strict contract.",
                            "cycle_timeout_seconds": 80,
                            "cycle_return_buffer_seconds": 60,
                        }
                    )
                )
            self.assertEqual(result["status"], "PARTIAL")
            checkpoint_path = Path(result["checkpoint"])
            self.assertTrue(checkpoint_path.exists())
            try:
                return json.loads(checkpoint_path.read_text(encoding="utf-8"))
            finally:
                remove_cycle_artifacts(result)

        strict_checkpoint = _run_and_read_checkpoint("1")
        self.assertIs(
            strict_checkpoint["architecture"]["controls"]["translator_strict_contract"],
            True,
        )
        # PARTIAL is exactly the killed/failed outcome class the original
        # defect left unstamped -- confirm the manifest is present here, not
        # only on a successful 'done' result.
        self.assertEqual(strict_checkpoint["stage"], "partial")

        base_checkpoint = _run_and_read_checkpoint("0")
        self.assertIs(
            base_checkpoint["architecture"]["controls"]["translator_strict_contract"],
            False,
        )


class RuntimeResourceTests(unittest.TestCase):
    def test_capacity_and_plan_are_positive(self):
        capacity = detect_compute_capacity()
        plan = recommended_parallelism(capacity)
        self.assertGreaterEqual(capacity["logical_cpus_available"], 1)
        self.assertGreaterEqual(capacity["physical_cores_estimate"], 1)
        self.assertGreaterEqual(plan["local_scientific_workers"], 1)
        self.assertEqual(plan["deliberative_cycles"], 1)

    def test_worker_override_respects_available_cpus(self):
        capacity = {
            "logical_cpus_available": 8,
            "physical_cores_estimate": 4,
        }
        with patch.dict("os.environ", {"ASTRA_LOCAL_WORKERS": "99"}, clear=False):
            plan = recommended_parallelism(capacity)
        self.assertEqual(plan["local_scientific_workers"], 8)

    def test_cycle_slot_serializes_processes_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, active = acquire_cycle_slot(root, 1)
            self.assertIsNotNone(first)
            self.assertEqual(active, [])
            second, active = acquire_cycle_slot(root, 1)
            self.assertIsNone(second)
            self.assertEqual(active[0]["pid"], first.holder["pid"])
            first.release()
            third, _ = acquire_cycle_slot(root, 1)
            self.assertIsNotNone(third)
            third.release()

    @patch("subprocess.Popen")
    def test_persistent_cycle_submission_writes_resumable_request(self, popen):
        popen.return_value.pid = 12345
        with tempfile.TemporaryDirectory() as directory, patch(
            "astra_tool._jobs_root",
            return_value=directory,
        ):
            result = _do_submit_cycle(
                {
                    "action": "cycle_submit",
                    "intuition": "Audit the invariant.",
                    "objective": "Obtain a falsifiable result.",
                    "oracle": "local",
                    "max_seconds": 3600,
                }
            )
            request_path = (
                Path(directory) / result["job_id"] / "request.json"
            )
            request = json.loads(
                request_path.read_text(encoding="utf-8")
            )
        self.assertEqual(result["kind"], "deliberative_cycle")
        self.assertEqual(request["wait_for_cycle_slot_seconds"], 3600)
        self.assertTrue(request["persistent_cycle"])
        self.assertNotIn("cycle_timeout_seconds", request)

    def test_persistent_runner_has_an_internal_response_buffer(self):
        source = Path("astra_cycle_job_runner.py").read_text(encoding="utf-8")
        self.assertIn('request["cycle_timeout_seconds"] = max_seconds', source)
        self.assertIn('request.setdefault("cycle_return_buffer_seconds", 60)', source)


if __name__ == "__main__":
    unittest.main()
