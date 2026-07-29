import unittest
from unittest.mock import AsyncMock, patch

import main
from core.state import state


class GuiCycleAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_gui_dispatches_the_same_guarded_cycle_as_mcp(self):
        snapshot = {
            "cycle_count": state.cycle_count,
            "investigation_cycle_count": state.investigation_cycle_count,
            "current_cycle": state.current_cycle,
            "axiomatic_base": state.axiomatic_base,
            "research_session": state.research_session,
            "stop_requested": state.stop_requested,
            "last_cycle_result": state.last_cycle_result,
        }
        fake_cycle = {
            "status": "REFUTED",
            "conjecture": "Candidate C",
            "code": "print('VERDICT: FAIL')",
            "execution": {
                "stdout": "VERDICT: FAIL",
                "stderr": "",
                "exit_code": 0,
            },
            "analysis": {
                "status": "REFUTED",
                "reasoning": "Exact counterexample.",
            },
            "navigation": {"next_direction": "Try a weaker claim."},
            "oracle_used": "local",
            "architecture": {"architecture_id": "astra-compact-three-agent-v2"},
        }
        try:
            state.research_session = None
            state.stop_requested = False
            with patch(
                "astra_tool._do_cycle",
                new=AsyncMock(return_value=fake_cycle),
            ) as run_cycle, patch.object(
                main,
                "_write_cycle_report",
            ), patch.object(
                state,
                "save_state",
            ):
                result = await main._execute_one_cycle("Test direction")

            self.assertEqual(result["status"], "REFUTED")
            self.assertEqual(
                result["navigation"]["next_direction"],
                "Try a weaker claim.",
            )
            request = run_cycle.await_args.args[0]
            self.assertEqual(request["intuition"], "Test direction")
            self.assertEqual(request["objective"], "Test direction")
            self.assertEqual(
                state.last_cycle_result["architecture"]["architecture_id"],
                "astra-compact-three-agent-v2",
            )
        finally:
            for key, value in snapshot.items():
                setattr(state, key, value)


if __name__ == "__main__":
    unittest.main()
