import os
import unittest
from unittest.mock import AsyncMock, patch

from core.executor import execute_python_code
from core.remote_executor import execute_remote_engine, list_remote_engines


class RemoteManagedEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pkgs_engine_routes_through_astrum_registry(self):
        response = {
            "stdout": "VERDICT: PASS\n",
            "stderr": "",
            "exit_code": 0,
            "engine": "python",
        }
        with patch(
            "core.remote_executor.execute_remote_code",
            new=AsyncMock(return_value=response),
        ) as remote:
            result = await execute_remote_engine(
                "# ASTRA_ENGINE: pkgs\nprint('VERDICT: PASS')",
                "pkgs",
                timeout=90,
            )
        wrapper = remote.await_args.args[0]
        self.assertIn("astra_engine.sh", wrapper)
        self.assertIn("'pkgs'", wrapper)
        self.assertEqual(result["engine"], "pkgs")
        self.assertEqual(result["engine_route"], "astra_engine.sh")

    async def test_executor_refuses_managed_engine_on_local_oracle(self):
        with patch.dict(os.environ, {"ASTRA_ORACLE_MODE": "local"}, clear=False):
            result = await execute_python_code(
                "# ASTRA_ENGINE: pkgs\nprint('test')",
                timeout=30,
            )
        self.assertEqual(result["exit_code"], -2)
        self.assertIn("ASTRUM-managed", result["stderr"])

    async def test_executor_dispatches_managed_engine_to_remote(self):
        expected = {"stdout": "ok", "stderr": "", "exit_code": 0, "engine": "sci"}
        with patch.dict(os.environ, {"ASTRA_ORACLE_MODE": "remote"}, clear=False), patch(
            "core.remote_executor.execute_remote_engine",
            new=AsyncMock(return_value=expected),
        ) as remote:
            result = await execute_python_code(
                "# ASTRA_ENGINE: sci\nprint('ok')",
                timeout=30,
            )
        self.assertEqual(result, expected)
        remote.assert_awaited_once()

    async def test_engine_inventory_uses_authoritative_runner(self):
        with patch(
            "core.remote_executor.execute_remote_code",
            new=AsyncMock(
                return_value={"stdout": "[OK] pkgs", "stderr": "", "exit_code": 0}
            ),
        ) as remote:
            result = await list_remote_engines()
        self.assertIn('runner, "list"', remote.await_args.args[0])
        self.assertEqual(result["engine"], "registry")


if __name__ == "__main__":
    unittest.main()
