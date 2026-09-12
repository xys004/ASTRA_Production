"""Cycles run by the suite must never touch the production workspace.

Every test cycle used to leave its checkpoint in workspace/cycle_checkpoints
and its heartbeat in workspace/progress, the two pools that
core/cycle_telemetry.py (astra_probe, astra_telemetry, scripts/astra_progress.py
--summary) reads as production history.  conftest.py now points
ASTRA_WORKSPACE_ROOT at a temporary directory.  This file proves three things:

* with the variable absent every writer path is byte-for-byte the historical
  ``<checkout>/workspace/...`` string (production is untouched);
* with the variable set every writer follows it;
* a real ``_do_cycle`` run under the session fixture leaves no heartbeat,
  checkpoint or cache file under the checkout's workspace/ (the three pools
  the telemetry reads) and its two artefacts land in the isolated root, where
  ``tests.cycle_artifacts.remove_cycle_artifacts`` removes both of them.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import astra_tool
from astra_tool import _do_cycle, _jobs_root, _progress_path, _workspace_root
from tests.cycle_artifacts import remove_cycle_artifacts

CHECKOUT = os.path.dirname(os.path.abspath(astra_tool.__file__))
REAL_WORKSPACE = Path(CHECKOUT) / "workspace"


def test_default_paths_are_byte_for_byte_the_historical_ones():
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("ASTRA_WORKSPACE_ROOT", None)
        assert _workspace_root() == os.path.join(CHECKOUT, "workspace")
        assert _progress_path(4242) == os.path.join(
            CHECKOUT, "workspace", "progress", "cycle_4242.json"
        )
        assert _progress_path() == os.path.join(
            CHECKOUT, "workspace", "progress", f"cycle_{os.getpid()}.json"
        )
        assert _jobs_root() == os.path.join(CHECKOUT, "workspace", "jobs")


def test_blank_or_quoted_override_is_handled_like_the_lock_root(tmp_path):
    with patch.dict("os.environ", {"ASTRA_WORKSPACE_ROOT": "   "}, clear=False):
        assert _workspace_root() == os.path.join(CHECKOUT, "workspace")
    # .env files may quote values; ASTRA_LOCK_ROOT strips them the same way.
    quoted = f"'{tmp_path}'"
    with patch.dict("os.environ", {"ASTRA_WORKSPACE_ROOT": quoted}, clear=False):
        assert _workspace_root() == str(tmp_path)


def test_override_redirects_every_writer(tmp_path):
    with patch.dict("os.environ", {"ASTRA_WORKSPACE_ROOT": str(tmp_path)}, clear=False):
        assert _workspace_root() == str(tmp_path)
        assert Path(_progress_path()) == tmp_path / "progress" / f"cycle_{os.getpid()}.json"
        assert Path(_jobs_root()) == tmp_path / "jobs"


def _pid_files(directory: Path, pid: int) -> list:
    """Files THIS process could have written: cycle_<pid>.json, <key>_<pid>.json(.tmp)."""
    if not directory.exists():
        return []
    names = set()
    for pattern in (f"cycle_{pid}.json", f"*_{pid}.json", f"*_{pid}.json.tmp"):
        names.update(p.name for p in directory.glob(pattern))
    return sorted(names)


def test_cycle_under_the_fixture_leaves_no_telemetry_file_in_the_real_workspace(isolated_workspace_root):
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
            return "API_ERROR: workspace isolation probe"

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
        "ASTRA_NAVIGATE_AFTER_CYCLE": "0",
        "ASTRA_MAX_RETRIES": "0",
        "ASTRA_ORACLE_MODE": "local",
    }
    pid = os.getpid()
    watched = ("progress", "cycle_checkpoints", "cycle_cache")
    before = {name: _pid_files(REAL_WORKSPACE / name, pid) for name in watched}

    with patch.dict("os.environ", env, clear=False), patch(
        "core.preflight.phase_provider_map", return_value=providers
    ), patch("core.llm_client.ASTRAIntelligence", FakeIntelligence):
        result = asyncio.run(
            _do_cycle(
                {
                    "action": "cycle",
                    "intuition": "Workspace isolation probe.",
                    "cycle_timeout_seconds": 1500,
                }
            )
        )

    # The cycle really ran (a fake translator failure is a full cycle for
    # checkpoint/heartbeat purposes) and reported its checkpoint.
    assert result["status"] == "TOOL_ERROR", result
    assert result["phase"] == "translator"

    isolated = Path(isolated_workspace_root).resolve()
    checkpoint = Path(result["checkpoint"]).resolve()
    heartbeat = Path(_progress_path()).resolve()
    assert checkpoint.exists()
    assert heartbeat.exists()
    assert isolated in checkpoint.parents, checkpoint
    assert isolated in heartbeat.parents, heartbeat
    assert REAL_WORKSPACE.resolve() not in checkpoint.parents
    assert REAL_WORKSPACE.resolve() not in heartbeat.parents
    # The heartbeat names the isolated checkpoint, so a telemetry reader pointed
    # at the isolated root still sees a consistent pair.
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert Path(payload["checkpoint"]).resolve() == checkpoint

    # Nothing new under the checkout's workspace/ for this pid.  Compared
    # before/after (not "empty") because a recycled pid can match an old file.
    after = {name: _pid_files(REAL_WORKSPACE / name, pid) for name in watched}
    assert after == before

    removed = remove_cycle_artifacts(result)
    assert {Path(p).resolve() for p in removed} == {checkpoint, heartbeat}
    assert not checkpoint.exists()
    assert not heartbeat.exists()
    assert remove_cycle_artifacts(result) == []      # idempotent
