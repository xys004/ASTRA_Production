import importlib
import unittest
import sys
import types
from unittest.mock import patch


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self):
        return lambda function: function

    def run(self):
        pass


fastmcp = types.ModuleType("mcp.server.fastmcp")
fastmcp.FastMCP = _FakeFastMCP
server = types.ModuleType("mcp.server")
mcp = types.ModuleType("mcp")
with patch.dict(
    sys.modules,
    {
        "mcp": mcp,
        "mcp.server": server,
        "mcp.server.fastmcp": fastmcp,
    },
):
    server_module = importlib.import_module("mcp_server.server")

_kill_tree = server_module._kill_tree
_pid_alive = server_module._pid_alive


class McpServerPortabilityTests(unittest.TestCase):
    def test_posix_timeout_kills_the_process_group(self):
        with patch.object(server_module.os, "name", "posix"), patch.object(
            server_module.os,
            "getpgid",
            return_value=4321,
            create=True,
        ), patch.object(server_module.os, "killpg", create=True) as killpg:
            with patch.object(
                server_module.signal,
                "SIGKILL",
                9,
                create=True,
            ):
                _kill_tree(1234)
        killpg.assert_called_once()
        self.assertEqual(killpg.call_args.args[0], 4321)

    def test_posix_pid_probe_uses_signal_zero(self):
        with patch.object(server_module.os, "name", "posix"), patch.object(
            server_module.os,
            "kill",
            create=True,
        ) as kill:
            self.assertTrue(_pid_alive(1234))
        kill.assert_called_once_with(1234, 0)


if __name__ == "__main__":
    unittest.main()
