"""Detached runner for one ASTRA 2.0 campaign step.

Unlike astra_cycle_job_runner.py, this does not spawn a nested astra_tool.py
subprocess: campaign_api.astra_campaign_step is an in-process coroutine (the
same one the synchronous astra_campaign_step MCP tool already awaits), so the
runner just drives it to completion in its own asyncio.run and writes the
result. No watchdog/kill loop is needed either - astra_campaign_step accepts
its own cycle_timeout_seconds, so the bound (if any) is enforced from inside
the call, not by babysitting a child process.

Writes into the SAME workspace/jobs/<job_id>/job.json schema that astra_tool.py's
_do_job already reads, so the existing astra_job MCP tool polls this without any
change on that side.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _save(meta: dict, jobdir: Path) -> None:
    meta["ts"] = time.time()
    temporary = jobdir / "job.json.tmp"
    temporary.write_text(json.dumps(meta, default=str), encoding="utf-8")
    os.replace(str(temporary), str(jobdir / "job.json"))


def main(jobdir_text: str) -> int:
    jobdir = Path(jobdir_text).resolve()
    meta = json.loads((jobdir / "job.json").read_text(encoding="utf-8"))
    request = json.loads((jobdir / "request.json").read_text(encoding="utf-8"))
    campaign_id = str(request["campaign_id"])
    root = request.get("root")
    cycle_timeout_seconds = request.get("cycle_timeout_seconds")

    started = time.time()
    meta.update(status="running", pid=os.getpid(), started_ts=started)
    _save(meta, jobdir)

    from core import campaign_api  # noqa: E402 - after sys.path fixup above

    error = None
    result = None
    try:
        result = asyncio.run(
            campaign_api.astra_campaign_step(
                campaign_id,
                root=root,
                cycle_timeout_seconds=cycle_timeout_seconds,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surfaced in the job record, not raised
        error = f"{type(exc).__name__}: {exc}"

    payload = result if error is None else {"error": error}
    (jobdir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    step = (result or {}).get("step") or {}
    decisions = step.get("decisions") or []
    meta.update(
        status="failed" if error else "done",
        finished_ts=time.time(),
        duration_s=round(time.time() - started, 2),
        error=error,
        claim_status=step.get("claim_status"),
        operation_status=step.get("operation_status"),
        goal_coverage=step.get("goal_coverage"),
        decision_action=decisions[0].get("action") if decisions else None,
    )
    _save(meta, jobdir)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
