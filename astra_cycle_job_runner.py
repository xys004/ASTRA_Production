"""Detached runner for one complete, persistent ASTRA deliberative cycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
ASTRA_TOOL = ROOT / "astra_tool.py"


def _save(meta: dict, jobdir: Path) -> None:
    meta["ts"] = time.time()
    temporary = jobdir / "job.json.tmp"
    temporary.write_text(json.dumps(meta), encoding="utf-8")
    os.replace(str(temporary), str(jobdir / "job.json"))


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _last_json(path: Path) -> dict:
    last = None
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                candidate = json.loads(line.strip())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(candidate, dict):
                last = candidate
    return last or {"error": "persistent cycle produced no JSON result"}


def _phase_progress(pid: int) -> dict:
    path = ROOT / "workspace" / "progress" / f"cycle_{pid}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main(jobdir_text: str) -> int:
    jobdir = Path(jobdir_text).resolve()
    meta = json.loads((jobdir / "job.json").read_text(encoding="utf-8"))
    request = json.loads((jobdir / "request.json").read_text(encoding="utf-8"))
    request["action"] = "cycle"
    request.pop("cycle_timeout_seconds", None)

    max_seconds = int(meta.get("max_seconds") or 7200)
    stdout_path = jobdir / "stdout.log"
    stderr_path = jobdir / "stderr.log"
    started = time.time()

    with stdout_path.open("w", encoding="utf-8") as stdout_stream, \
            stderr_path.open("w", encoding="utf-8") as stderr_stream:
        process = subprocess.Popen(
            [sys.executable, str(ASTRA_TOOL)],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdin=subprocess.PIPE,
            stdout=stdout_stream,
            stderr=stderr_stream,
            text=True,
            encoding="utf-8",
        )
        meta.update(
            status="running",
            pid=os.getpid(),
            nested_pid=process.pid,
            started_ts=started,
        )
        _save(meta, jobdir)
        assert process.stdin is not None
        process.stdin.write(json.dumps(request, ensure_ascii=False))
        process.stdin.close()

        timed_out = False
        while process.poll() is None:
            elapsed = time.time() - started
            progress = _phase_progress(process.pid)
            if progress:
                meta["phase"] = progress.get("stage")
                meta["phase_timings"] = progress.get("timings") or {}
                meta["cycle_checkpoint"] = progress.get("checkpoint")
            meta["elapsed_s"] = round(elapsed, 1)
            _save(meta, jobdir)
            if elapsed > max_seconds:
                timed_out = True
                _kill_tree(process.pid)
                break
            time.sleep(5)
        try:
            return_code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _kill_tree(process.pid)
            return_code = -9

    result = _last_json(stdout_path)
    if timed_out:
        result = {
            "status": "TIMEOUT",
            "error": f"Persistent cycle exceeded {max_seconds} seconds",
            "last_result": result,
        }
    (jobdir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    operational_error = bool(result.get("error"))
    meta.update(
        status="failed" if timed_out or return_code != 0 else "done",
        finished_ts=time.time(),
        duration_s=round(time.time() - started, 2),
        exit_code=return_code,
        scientific_status=(
            result.get("scientific_status") or result.get("status")
        ),
        atomic_status=result.get("atomic_status") or result.get("status"),
        goal_coverage=(result.get("goal_coverage") or {}).get("status"),
        oracle_verdict=result.get("oracle_verdict"),
        operational_error=operational_error,
    )
    _save(meta, jobdir)
    return 1 if timed_out or return_code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
