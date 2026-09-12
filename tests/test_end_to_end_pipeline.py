"""End-to-end integration test of the ASTRA pipeline in SIMULATED mode.

Exercises the full five-phase flow — intuition -> conjecture (2) -> translation
(3) -> Oracle validation (4) -> refutation analysis (5) — without spending any
tokens. SIMULATED mode is the framework's built-in offline path (returned when an
LLM client has no API key); the test forces it deterministically by nulling each
client's credentials, so it holds even on a machine that *does* have real keys.

The Oracle (phase 4) still runs the generated Python for real via a subprocess,
so this is a genuine integration test of orchestration + executor + analyst, not
a mock of the whole thing.
"""

import asyncio
import importlib.util
import os
import sys
import unittest

# Ensure the project root is importable when pytest is invoked from elsewhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import main  # noqa: E402
from core.state import state  # noqa: E402

INTUITION = "For a free relativistic particle, energy and momentum satisfy E^2 = (pc)^2 + (m c^2)^2."
TERMINAL_STATUSES = {"VALIDATED", "REFUTED"}


def _force_simulated(client) -> None:
    """Drop credentials so every phase falls back to its SIMULATED response."""
    client.api_key = None
    client.client = None


class EndToEndSimulatedPipelineTest(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec("sympy") is None:
            self.skipTest("sympy not available; run under the project venv")

        # Force single-provider (non-ensemble) branch and local Oracle so the
        # test is deterministic and never touches the network or ASTRUM cluster.
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("ASTRA_CONJECTURE_PROVIDER", "ASTRA_ORACLE_MODE")
        }
        os.environ["ASTRA_CONJECTURE_PROVIDER"] = "anthropic"
        os.environ["ASTRA_ORACLE_MODE"] = "local"

        for client in (main.conjecture_llm, main.translator_llm, main.analyst_llm):
            _force_simulated(client)

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_five_phase_pipeline_reaches_terminal_verdict(self):
        async def _run():
            # Phase 1 is the human intuition fed into the loop (INTUITION).
            conjecture = await main.phase_2_generate_conjecture("", INTUITION)
            code = await main.phase_3_formal_translation(conjecture)
            exec_result = await main.phase_4_validation_oracle(code)
            analysis = await main.phase_5_result_analysis(conjecture, exec_result)
            return conjecture, code, exec_result, analysis

        conjecture, code, exec_result, analysis = asyncio.run(_run())

        # Phase 2 — a hypothesis was produced.
        self.assertIsInstance(conjecture, str)
        self.assertTrue(conjecture.strip(), "phase 2 produced no conjecture")

        # Phase 3 — a runnable validation script was produced.
        self.assertIsInstance(code, str)
        self.assertTrue(code.strip(), "phase 3 produced no code")

        # Phase 4 — the Oracle actually executed the script (real subprocess).
        self.assertIsInstance(exec_result, dict)
        self.assertIn("exit_code", exec_result)
        self.assertEqual(exec_result.get("exit_code"), 0, exec_result.get("stderr"))
        self.assertIn("VERDICT: PASS", (exec_result.get("stdout") or "").upper())

        # Phase 5 — analysis returns a terminal scientific verdict.
        self.assertIsInstance(analysis, dict)
        self.assertIn(analysis.get("status"), TERMINAL_STATUSES)
        # A clean PASS must be adjudicated VALIDATED.
        self.assertEqual(analysis.get("status"), "VALIDATED")

        # The pipeline advanced the shared state through the phases.
        self.assertTrue(state.current_phase)


if __name__ == "__main__":
    unittest.main()
