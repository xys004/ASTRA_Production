"""Regression test for the MCP server concurrency fix.

Before this fix every @mcp.tool() was a plain `def`; FastMCP calls a sync tool
directly on its single event-loop thread (mcp/server/fastmcp/utilities/
func_metadata.py: `else: return fn(**arguments_parsed_dict)`), so one
long-running tool call (e.g. astra_cycle, ~15-30 min) froze the whole server -
including trivially fast, unrelated calls on the SAME connection, and calls
issued from a different chat/project. Every blocking tool is now `async def`,
offloading its blocking body via asyncio.to_thread so the event loop stays free
to service other in-flight tool calls concurrently (the SDK's own request loop
already spawns one task per incoming message via anyio task-group start_soon;
only the per-tool blocking was missing the offload).

This test proves the property directly: two "slow" tool calls run concurrently
via asyncio.gather must finish in roughly the time of ONE of them, not their
sum. Before the fix (calling the tool functions directly, without
asyncio.to_thread) they would serialize and this would fail.
"""
import asyncio
import importlib
import sys
import time
import types
import unittest
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


SLEEP_SECONDS = 0.25


def _slow_call_astra(_req, timeout=300):  # noqa: ARG001 - matches _call_astra's shape
    time.sleep(SLEEP_SECONDS)
    return {"ok": True}


class McpServerConcurrencyTests(unittest.TestCase):
    def test_two_slow_tool_calls_overlap_instead_of_serializing(self):
        async def run_both():
            with patch.object(server_module, "_call_astra", _slow_call_astra):
                started = time.monotonic()
                await asyncio.gather(
                    server_module.astra_capacity(),
                    server_module.astra_engines(),
                )
                return time.monotonic() - started

        elapsed = asyncio.run(run_both())
        # Serialized (the pre-fix behaviour) would take >= 2*SLEEP_SECONDS.
        # Overlapped (fixed) takes roughly one SLEEP_SECONDS plus scheduling
        # slack; the threshold sits well below the serialized floor so this
        # fails loudly if the offload regresses.
        self.assertLess(elapsed, 1.5 * SLEEP_SECONDS)

    def test_astra_probe_is_deliberately_left_synchronous(self):
        # astra_probe only reads local heartbeat files (documented as
        # "zero cost, instant"); it is the one intentional non-async tool,
        # not an oversight. Guard that choice explicitly so a future refactor
        # that "fixes" it by making everything async does so on purpose.
        self.assertFalse(asyncio.iscoroutinefunction(server_module.astra_probe))
        self.assertTrue(asyncio.iscoroutinefunction(server_module.astra_capacity))
        self.assertTrue(asyncio.iscoroutinefunction(server_module.astra_execute))


if __name__ == "__main__":
    unittest.main()
