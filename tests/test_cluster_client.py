import os
import unittest
from unittest.mock import AsyncMock, patch

from core.cluster_client import client_id, cluster_enabled, execute_cluster_code
from core.remote_executor import execute_remote_code


class ClusterClientTests(unittest.IsolatedAsyncioTestCase):
    def test_client_identity_and_scheduler_flag_are_explicit(self):
        with patch.dict(
            os.environ,
            {"ASTRA_CLIENT_ID": "gabriel", "ASTRA_REMOTE_SCHEDULER": "1"},
            clear=False,
        ):
            self.assertEqual(client_id(), "gabriel")
            self.assertTrue(cluster_enabled())

    async def test_execute_cluster_code_unwraps_persistent_result(self):
        status = {
            "job_id": "astrum_test",
            "status": "succeeded",
            "remote_host": "astrum",
            "result": {"stdout": "VERDICT: PASS\n", "stderr": "", "exit_code": 0},
        }
        with patch(
            "core.cluster_client.cluster_rpc",
            new=AsyncMock(return_value=status),
        ):
            result = await execute_cluster_code("print('VERDICT: PASS')", 30, "python")
        self.assertEqual(result["cluster_job_id"], "astrum_test")
        self.assertEqual(result["cluster_status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)

    async def test_remote_executor_routes_through_scheduler_when_enabled(self):
        expected = {"stdout": "ok", "stderr": "", "exit_code": 0, "cluster_job_id": "x"}
        with patch.dict(
            os.environ,
            {"ASTRA_REMOTE_HOST": "astrum", "ASTRA_REMOTE_SCHEDULER": "1"},
            clear=False,
        ), patch(
            "core.cluster_client.execute_cluster_code",
            new=AsyncMock(return_value=expected),
        ) as scheduled:
            result = await execute_remote_code("print('ok')", timeout=30, engine_hint="python")
        self.assertEqual(result, expected)
        scheduled.assert_awaited_once_with("print('ok')", timeout=30, engine="python")


if __name__ == "__main__":
    unittest.main()
