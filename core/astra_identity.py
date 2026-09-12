"""Make it obvious, at a glance, that a running process is ASTRA - and which line.

A multi-agent research engine spawns a lot of activity (Python, subscription CLIs,
WSL) that can look anonymous in a terminal or in Task Manager. This module lets
ASTRA announce itself: a one-time banner on stderr and a live console-window title,
both stamped with the version (1.0 vs 2.0), the action, and the PID. If you see
this, it is ASTRA; if activity is happening WITHOUT it, that is worth a second
look.

The version is inferred from the checkout this file lives in (ASTRA-2.0 vs ASTRA),
overridable with the ASTRA_VERSION environment variable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BANNER_PRINTED = False


def astra_version() -> str:
    override = os.environ.get("ASTRA_VERSION", "").strip()
    if override:
        return override
    parts = Path(__file__).resolve().parts
    if any(p == "ASTRA-2.0" for p in parts):
        return "2.0"
    if any(p == "ASTRA" for p in parts):
        return "1.0"
    return "?"


def checkout_root() -> str:
    # core/astra_identity.py -> the checkout directory two levels up.
    return str(Path(__file__).resolve().parents[1])


def set_console_title(action: str = "running") -> None:
    """Name the cmd/PowerShell window so it is recognisable in the taskbar and
    Task Manager (Apps view). Best-effort; silent if unavailable."""
    title = f"ASTRA {astra_version()} - {action} - PID {os.getpid()}"
    try:
        if os.name == "nt":
            import ctypes  # local import: only needed on Windows
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        else:
            # xterm-family terminals honour this OSC escape.
            sys.stderr.write(f"\033]0;{title}\a")
            sys.stderr.flush()
    except Exception:
        pass


def banner(action: str = "running", *, force: bool = False) -> None:
    """Print a distinctive one-time ASTRA banner to stderr, and set the window
    title. Called at process entry points; safe to call more than once."""
    global _BANNER_PRINTED
    set_console_title(action)
    if _BANNER_PRINTED and not force:
        return
    _BANNER_PRINTED = True
    v = astra_version()
    # ASCII only: Windows cp1252 consoles (cmd, PowerShell 5.1) mangle box-drawing
    # and other non-ASCII glyphs, and a garbled banner defeats the purpose.
    line = "=" * 62
    msg = (
        f"\n{line}\n"
        f"  ASTRA {v} -- scientific validation engine\n"
        f"  action : {action}\n"
        f"  PID    : {os.getpid()}\n"
        f"  source : {checkout_root()}\n"
        f"  NOTE   : closing this window ABORTS the ASTRA run in progress.\n"
        f"           If this appears and you did not start ASTRA, investigate.\n"
        f"{line}\n"
    )
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
    except Exception:
        pass
