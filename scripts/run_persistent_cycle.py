#!/usr/bin/env python3
"""Run one full ASTRA cycle without an MCP client-side timeout.

The script is intended to be launched by ``astra_submit``.  The outer ASTRA
job supplies persistence and heartbeats, while this process invokes the normal
``astra_tool.py`` cycle pipeline and stores its complete JSON result on disk.
Scientific status (VALIDATED/REFUTED/etc.) is kept separate from the
operational success of completing all four pipeline phases.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ASTRA_TOOL = ROOT / "astra_tool.py"


def _load_last_json(log_path: Path) -> dict[str, Any]:
    """Return the last complete JSON object emitted by astra_tool.py."""
    last: dict[str, Any] | None = None
    with log_path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            candidate = line.strip()
            if not candidate:
                continue
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                last = value
    if last is None:
        raise RuntimeError(f"No complete JSON object found in {log_path}")
    return last


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and persist one complete multimodel ASTRA cycle."
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Allow ASTRA's exact-request cycle cache (fresh execution is default).",
    )
    args = parser.parse_args()

    request_path = args.request.resolve()
    output_path = args.output.resolve()
    log_path = output_path.with_suffix(output_path.suffix + ".runner.log")

    with request_path.open("r", encoding="utf-8") as stream:
        request = json.load(stream)
    if not isinstance(request, dict):
        raise ValueError("The request must be a JSON object")
    request["action"] = "cycle"
    if not str(request.get("intuition", "")).strip():
        raise ValueError("The cycle request requires a non-empty intuition")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ASTRA_CYCLE_CACHE"] = "1" if args.use_cache else "0"

    with log_path.open("w", encoding="utf-8") as log_stream:
        process = subprocess.Popen(
            [sys.executable, str(ASTRA_TOOL)],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        print(f"ASTRA_NESTED_PID: {process.pid}", flush=True)
        assert process.stdin is not None
        process.stdin.write(json.dumps(request, ensure_ascii=False))
        process.stdin.close()
        return_code = process.wait()

    result = _load_last_json(log_path)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    scientific_status = result.get("status") or "ERROR"
    required_sections = ("conjecture", "code", "execution", "analysis")
    operational_checks = {
        "child_returncode_zero": return_code == 0,
        "no_pipeline_error": not bool(result.get("error")),
        "all_pipeline_sections_present": all(
            section in result for section in required_sections
        ),
        "terminal_scientific_status": scientific_status
        in {"VALIDATED", "REFUTED", "CODE_ERROR", "WEAK_PASS"},
    }
    operational_pass = all(operational_checks.values())

    print(f"ASTRA_RESULT: {output_path}", flush=True)
    print(f"ASTRA_RAW_LOG: {log_path}", flush=True)
    print(f"SCIENTIFIC_STATUS: {scientific_status}", flush=True)
    for name, passed in operational_checks.items():
        print(f"CHECK {name}: {'PASS' if passed else 'FAIL'}", flush=True)
    print(f"VERDICT: {'PASS' if operational_pass else 'FAIL'}", flush=True)
    return 0 if operational_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
