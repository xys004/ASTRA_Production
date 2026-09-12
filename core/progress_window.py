"""One console window per deliberative cycle, showing what it is working on.

Requested 2026-09-09: every ASTRA 1.0 cycle, from whichever agent invoked it,
should open its own window naming the instruction it works on, the phase it
is in, a progress bar and an ETA. The window is a plain console running
``scripts/astra_progress.py --follow <pid> --checkpoint <path>`` (stdlib
only, ASCII only), which tails this cycle's heartbeat
(workspace/progress/cycle_<pid>.json) and its checkpoint, and estimates the
remaining time from the median phase durations of recent finished cycles.

Rules
-----
* Windows only; a no-op elsewhere.
* ``ASTRA_PROGRESS_WINDOW``: ``0/off/false/no`` disables it; ``1`` forces it;
  absent means on, except under a test runner (pytest / unittest), so a suite
  never pops windows.
* The console is opened through a hidden ``cmd /c start`` trampoline, not as
  a child of the cycle: the MCP server and the persistent runner kill a timed
  out cycle with ``taskkill /F /T``, and a child window would vanish exactly
  when its last heartbeat is the only account of what happened. The
  trampoline exits at once, so the follower is nobody's child.
* Observability never harms the cycle: any failure to spawn returns None.
* The follower closes itself ``ASTRA_PROGRESS_WINDOW_LINGER`` seconds after
  the cycle ends (default 120; ``-1`` keeps it open until Enter).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLLOWER = ROOT / "scripts" / "astra_progress.py"
WINDOW_TITLE = "ASTRA 1.0 cycle"
_OFF = {"0", "off", "false", "no"}
_CREATE_NO_WINDOW = 0x08000000


def _under_test_runner() -> bool:
    if "pytest" in sys.modules:
        return True
    argv0 = os.path.basename(str(sys.argv[0] if sys.argv else ""))
    return "unittest" in argv0 or (argv0 == "__main__.py" and "unittest" in str(sys.argv[0]))


def window_enabled(env=None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get("ASTRA_PROGRESS_WINDOW", "") or "").strip().strip("'\"").lower()
    if raw in _OFF:
        return False
    if raw:
        return True                      # explicitly on, even under a test runner
    return not _under_test_runner()


def linger_seconds(env=None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get("ASTRA_PROGRESS_WINDOW_LINGER", "120") or "120").strip().strip("'\"")
    try:
        return max(-1, int(raw))
    except ValueError:
        return 120


def follower_command(pid: int, workspace_root: str | None = None, env=None,
                     python: str | None = None, checkpoint: str | None = None) -> list:
    cmd = [python or sys.executable, str(FOLLOWER), "--follow", str(int(pid)),
           "--linger", str(linger_seconds(env))]
    if workspace_root:
        cmd += ["--workspace", str(workspace_root)]
    if checkpoint:
        cmd += ["--checkpoint", str(checkpoint)]
    return cmd


def launcher_command(follower: list) -> list:
    """`cmd /c start "title" /D <root> <follower...>`: start opens the console
    and returns immediately, so the follower is not a child of the cycle."""
    return ["cmd.exe", "/c", "start", WINDOW_TITLE, "/D", str(ROOT), *follower]


def open_progress_window(pid: int, workspace_root: str | None = None, env=None,
                         popen=subprocess.Popen, checkpoint: str | None = None) -> int | None:
    """Open the follower's console through the trampoline. Returns the
    trampoline's pid (the follower itself is not a child), or None."""
    try:
        if os.name != "nt" or not window_enabled(env):
            return None
        if not FOLLOWER.exists():
            return None
        process = popen(
            launcher_command(follower_command(pid, workspace_root, env, checkpoint=checkpoint)),
            creationflags=_CREATE_NO_WINDOW,
            close_fds=True,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return getattr(process, "pid", None)
    except Exception:
        return None
