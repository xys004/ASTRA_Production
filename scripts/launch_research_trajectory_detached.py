#!/usr/bin/env python3
"""Launch the research-trajectory runner outside the caller's Windows job.

Long ASTRA cells can exceed desktop tool lifetimes.  On Windows this launcher
uses DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, and BREAKAWAY_FROM_JOB so the
benchmark continues independently while its normal checkpoint remains the
source of truth.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_research_trajectory_benchmarks.py"
LOG_ROOT = ROOT / "workspace" / "research_trajectory_launches"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch the ASTRA research benchmark as a detached process."
    )
    parser.add_argument(
        "runner_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed verbatim to run_research_trajectory_benchmarks.py",
    )
    args = parser.parse_args()
    forwarded = list(args.runner_args)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_path = LOG_ROOT / f"detached_{stamp}.stdout.log"
    stderr_path = LOG_ROOT / f"detached_{stamp}.stderr.log"
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
        )

    stdout_stream = stdout_path.open("w", encoding="utf-8")
    stderr_stream = stderr_path.open("w", encoding="utf-8")
    command = [sys.executable, str(RUNNER), *forwarded]
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError:
        if os.name != "nt":
            raise
        # Some parent jobs forbid BREAKAWAY_FROM_JOB. Detached execution is
        # still preferable to tying the benchmark to the launching shell.
        fallback_flags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            close_fds=True,
            creationflags=fallback_flags,
        )
    finally:
        stdout_stream.close()
        stderr_stream.close()

    print(
        json.dumps(
            {
                "pid": process.pid,
                "command": command,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
