import unittest
from unittest.mock import AsyncMock, patch

import main
from core.research_session import ResearchSession
from core.state import state


class ResearchLoopRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.snapshot = {
            "research_session": state.research_session,
            "stop_requested": state.stop_requested,
            "start_research_requested": state.start_research_requested,
            "max_runtime_minutes": state.max_runtime_minutes,
            "navigator_proposal": state.navigator_proposal,
            "last_cycle_result": state.last_cycle_result,
            "status": state.status,
            "current_phase": state.current_phase,
        }

    def tearDown(self):
        for key, value in self.snapshot.items():
            setattr(state, key, value)

    async def test_partial_and_busy_retry_without_navigation_or_history(self):
        for operational_status in ("PARTIAL", "BUSY"):
            with self.subTest(status=operational_status):
                session = ResearchSession("Test macro question")
                state.research_session = session
                state.max_runtime_minutes = 0
                state.stop_requested = False
                state.start_research_requested = True

                interrupted = {
                    "status": operational_status,
                    "conjecture": "",
                    "analysis": {
                        "status": operational_status,
                        "reasoning": "No scientific verdict.",
                    },
                    "error": "Operational interruption",
                }
                stopped = {
                    "status": "STOPPED",
                    "conjecture": "",
                    "analysis": {
                        "status": "STOPPED",
                        "reasoning": "End test.",
                    },
                }

                with patch.object(main, "_reload_llm_clients"), patch.object(
                    main,
                    "_execute_one_cycle",
                    new=AsyncMock(side_effect=[interrupted, stopped]),
                ) as execute, patch.object(
                    main,
                    "phase_nav_navigate",
                    new=AsyncMock(),
                ) as navigate, patch.object(
                    main.asyncio,
                    "sleep",
                    new=AsyncMock(),
                ), patch.object(state, "save_state"):
                    await main._run_research_loop()

                self.assertEqual(execute.await_count, 2)
                navigate.assert_not_awaited()
                self.assertEqual(session.thread, [])
                self.assertEqual(session.cycles_since_milestone, 0)

    async def test_external_navigation_is_written_back_to_cycle_trace(self):
        session = ResearchSession("Test macro question")
        state.research_session = session
        state.max_runtime_minutes = 0
        state.stop_requested = False
        state.start_research_requested = True

        result = {
            "status": "REFUTED",
            "conjecture": "Candidate claim",
            "analysis": {
                "status": "REFUTED",
                "reasoning": "Counterexample found.",
            },
            "navigation": {},
        }
        navigation = {
            "next_direction": "Test the boundary case.",
            "parallel_branches": [],
            "macro_resolved": True,
            "milestone": False,
            "progress_assessment": "One claim refuted.",
        }

        with patch.object(main, "_reload_llm_clients"), patch.object(
            main,
            "_execute_one_cycle",
            new=AsyncMock(return_value=result),
        ), patch.object(
            main,
            "phase_nav_navigate",
            new=AsyncMock(return_value=navigation),
        ) as navigate, patch.object(state, "save_state") as save_state:
            await main._run_research_loop()

        navigate.assert_awaited_once()
        self.assertEqual(result["navigation"], navigation)
        self.assertEqual(state.last_cycle_result["navigation"], navigation)
        self.assertEqual(session.thread[0]["nav_direction"], "Test the boundary case.")
        save_state.assert_called()


if __name__ == "__main__":
    unittest.main()
