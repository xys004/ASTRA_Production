"""The cycle opens its console once, right after its first heartbeat, with
its own pid and workspace; the suite itself never spawns one (conftest sets
ASTRA_PROGRESS_WINDOW=0 and the launcher detects pytest).

The fake Popen is injected through the launcher's own ``popen`` parameter:
patching ``subprocess.Popen`` would also break the oracle executor.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_tool import _do_cycle
from core import progress_window
from tests.cycle_artifacts import remove_cycle_artifacts

PROVIDERS = {
    "conjecture": "codex_cli",
    "translator": "claude_cli",
    "reviewer": "codex_cli",
    "analyst": "codex_cli",
    "navigator": "agy_cli",
    "synth": "codex_cli",
}


class FakeIntelligence:
    def __init__(self, provider, cli_models=None, cli_timeout=None):
        self.provider = provider
        self.cli_models = cli_models
        self.cli_timeout = cli_timeout
        self.cli_warnings = []
        self.cli_last_model = None
        self.cli_cost_usd = 0.0

    async def generate_conjecture(self, axiomatic_base, intuition):
        return "The candidate is refuted by x = 0."

    async def translate_to_code(self, conjecture, **_kwargs):
        return "print('CHECK counterexample: FAIL')\nprint('VERDICT: FAIL')\n"

    async def review_validation_code(self, **_kwargs):
        return {"status": "APPROVED", "reasoning": "ok", "revision_instructions": "",
                "coverage": ["counterexample"], "defect_labels": [], "runtime_checks": []}

    async def analyze_results(self, *_args, **_kwargs):
        return {"status": "REFUTED", "reasoning": "Counterexample executed."}


def _spy(spawned):
    """The real launcher with a recording popen injected."""
    real = progress_window.open_progress_window

    def fake_popen(args, **kwargs):
        spawned.append((args, kwargs))
        return type("P", (), {"pid": 31337})()

    def wrapper(pid, workspace_root=None, env=None, checkpoint=None):
        return real(pid, workspace_root, env, popen=fake_popen, checkpoint=checkpoint)

    return wrapper


async def _run(extra_env, spawned):
    env = {
        "ASTRA_CYCLE_CACHE": "0",
        "ASTRA_CONJECTURE_PROVIDER": "codex_cli",
        "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
        "ASTRA_MAX_RETRIES": "0",
        "ASTRA_ORACLE_MODE": "local",
        **extra_env,
    }
    with patch.dict("os.environ", env, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=PROVIDERS
    ), patch("core.llm_client.ASTRAIntelligence", FakeIntelligence), patch(
        "core.progress_window.open_progress_window", _spy(spawned)
    ):
        return await _do_cycle(
            {"action": "cycle", "intuition": "Test the progress window hook.",
             "cycle_timeout_seconds": 1500}
        )


@unittest.skipUnless(os.name == "nt", "the console launcher is Windows-only")
class Hook(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_opens_one_console_for_its_own_pid(self):
        spawned = []
        result = await _run({"ASTRA_PROGRESS_WINDOW": "1"}, spawned)
        try:
            self.assertEqual(result["status"], "REFUTED", result.get("error"))
            self.assertEqual(len(spawned), 1)
            args, kwargs = spawned[0]
            self.assertEqual(args[:3], ["cmd.exe", "/c", "start"])          # trampoline, not a child
            self.assertIn("--follow", args)
            self.assertIn(str(os.getpid()), args)
            self.assertEqual(args[args.index("--workspace") + 1], os.environ["ASTRA_WORKSPACE_ROOT"])
            self.assertEqual(args[args.index("--checkpoint") + 1], result["checkpoint"])
            self.assertTrue(kwargs["creationflags"] & 0x08000000)     # CREATE_NO_WINDOW (cmd)
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["progress_window"], {"launcher_pid": 31337})
        finally:
            remove_cycle_artifacts(result)

    async def test_an_escaping_exception_leaves_a_failed_heartbeat(self):
        """The window (and telemetry) key on the heartbeat: a cycle that dies
        with an exception must not leave it at its last phase forever."""
        from astra_tool import _progress_path

        with patch("astra_tool._do_cycle_impl", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                await _run({"ASTRA_PROGRESS_WINDOW": "0"}, [])
        heartbeat = json.loads(Path(_progress_path()).read_text(encoding="utf-8"))
        try:
            self.assertEqual(heartbeat["stage"], "failed")
            self.assertEqual(heartbeat["phase"], "exception")
            self.assertIn("RuntimeError: boom", heartbeat["error"])
        finally:
            remove_cycle_artifacts({})

    async def test_disabled_or_default_under_the_suite_spawns_nothing(self):
        spawned = []
        off = await _run({"ASTRA_PROGRESS_WINDOW": "0"}, spawned)
        remove_cycle_artifacts(off)
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("ASTRA_PROGRESS_WINDOW", None)          # default path: pytest guard
            default = await _run({}, spawned)
            remove_cycle_artifacts(default)
        self.assertEqual(spawned, [])
        self.assertEqual(off["status"], "REFUTED")
        self.assertEqual(default["status"], "REFUTED")
