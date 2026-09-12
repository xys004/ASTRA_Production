#!/usr/bin/env python3
"""List, and only with --apply delete, the test-suite leftovers in
workspace/progress and workspace/cycle_checkpoints.

Until 2026-09-09 the suite ran astra_tool._do_cycle against the production
workspace, deleting the checkpoint afterwards but never the heartbeat.  The
telemetry readers (core/cycle_telemetry.py, scripts/astra_progress.py
--summary, the MCP tools astra_probe / astra_telemetry) therefore aggregated
0.02 s "Test author quota failure" checkpoints and orphan heartbeats as if they
were real cycles.  tests/conftest.py now isolates the writers through
ASTRA_WORKSPACE_ROOT; this script cleans what already leaked.

Usage
  python scripts/prune_test_cycle_artifacts.py             dry run: list only
  python scripts/prune_test_cycle_artifacts.py --apply     delete the TEST class
  python scripts/prune_test_cycle_artifacts.py --all       also list KEEP files
  python scripts/prune_test_cycle_artifacts.py --workspace DIR   another pool

Classification (conservative on purpose: whatever is not proven TEST stays)

  checkpoint TEST requires ALL of
    - the pid is not alive (a live cycle's fresh 'start' checkpoint also
      reads elapsed 0 s with empty timings);
    - budget.elapsed_seconds < 1 s AND the timings total < 1 s: no real cycle
      finishes conjecture + translation + execution sub-second;
    - the intuition is one of the literal strings the suite passes to
      _do_cycle (KNOWN_TEST_INTUITIONS).  A wall budget <= 120 s (the value
      the suite used until 2026-09-05) is reported as supporting evidence but
      is not sufficient on its own: a real astra_cycle(timeout=90) killed at
      'start' would look the same.
  heartbeat TEST requires ALL of
    - the pid is not alive and the stage is terminal (done / failed);
    - a checkpoint path is recorded, and either that checkpoint is TEST
      itself, or it no longer exists (production never deletes checkpoints,
      only the suite did) while the heartbeat's timings total is < 1 s.
  AMBIGUOUS: sub-second cycles whose intuition is not a suite literal, orphan
    heartbeats with real durations, heartbeats without a checkpoint (BUSY or
    queued exits).  Listed, never deleted.
  Never touched: .tmp checkpoints, live pids, persistent or minute-long cycles.
  "Intuition starts with 'Test'" is deliberately NOT a signal: the August
  benchmark cycles ("Test the claim that curvature vanishes ...") are real,
  1500 s, minutes-long cycles.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Literal intuitions the suite passes to astra_tool._do_cycle.  Keep in step
# with tests/test_deliberative_pipeline.py, tests/test_goal_coverage.py,
# tests/test_cycle_runtime.py and tests/test_workspace_isolation.py;
# test_prune_test_cycle_artifacts.py scans the suite for "intuition": "..."
# literals next to a real _do_cycle call and reminds you to register new ones.
KNOWN_TEST_INTUITIONS = frozenset({
    "Test quality escalation.",
    "Test rejected patch regeneration.",
    "Test author quota failure during regeneration.",
    "Test author quota failure during bounded patch.",
    "Check one bounded identity.",
    "Test the deadline.",
    "Test the persistent deadline.",
    "Workspace isolation probe.",
    "Test checkpoint provenance under the strict contract.",
    "Test the review stuck detector.",
    "Test the request structurer.",
    "Test the non-decidable outcome.",
    "Test the progress window hook.",
    "Test the input request flow.",
    "A different direction, same objective.",
})
TEST_WALL_SECONDS = 120.0       # cycle_timeout_seconds the suite used until 2026-09-05
SUB_SECOND = 1.0
TERMINAL_HEARTBEAT_STAGES = frozenset({"done", "failed"})

TEST, AMBIGUOUS, KEEP = "TEST", "AMBIGUOUS", "KEEP"


def _load(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except Exception as exc:                       # unreadable => never touched
        return {"_unreadable": str(exc)}


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259                    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _timings_total(timings) -> float | None:
    if not isinstance(timings, dict):
        return None
    if isinstance(timings.get("total"), (int, float)):
        return float(timings["total"])
    values = [v for k, v in timings.items() if isinstance(v, (int, float))]
    return float(sum(values)) if values else None


def _float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def classify_checkpoint(path: str, alive=None) -> dict:
    """Return {path, kind, cls, reason, ...detail} for one checkpoint file."""
    alive = alive or _pid_alive          # resolved at call time (tests patch it)
    record = {"path": path, "kind": "checkpoint", "name": os.path.basename(path)}
    if path.endswith(".tmp"):
        return {**record, "cls": KEEP, "reason": "unfinished .tmp checkpoint, never classified"}
    data = _load(path)
    if "_unreadable" in data:
        return {**record, "cls": KEEP, "reason": f"unreadable: {data['_unreadable']}"}
    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    elapsed = _float(budget.get("elapsed_seconds"))
    wall = _float(budget.get("total_seconds"))
    timings = _timings_total(data.get("timings"))
    # A C3-structured cycle stores the composed direction as `intuition`;
    # the literal the suite passed is request.original.
    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    intuition = str(request.get("original") or data.get("intuition") or "").strip()
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    record.update({
        "stage": data.get("stage"),
        "mode": budget.get("mode"),
        "wall_s": wall,
        "elapsed_s": elapsed,
        "timings_s": timings,
        "status": result.get("status"),
        "created": _fmt_ts(data.get("created_ts")),
        "intuition": intuition[:60],
        "pid": data.get("pid"),
    })
    if alive(data.get("pid")):
        return {**record, "cls": KEEP, "reason": "pid alive"}
    sub_second = (
        elapsed is not None and elapsed < SUB_SECOND
        and (timings is None or timings < SUB_SECOND)
    )
    if not sub_second:
        return {**record, "cls": KEEP, "reason": "real duration"}
    short_wall = wall is not None and wall <= TEST_WALL_SECONDS
    if intuition in KNOWN_TEST_INTUITIONS:
        reason = "sub-second cycle; intuition is a suite literal"
        if short_wall:
            reason += f"; wall budget {wall:g} s <= {TEST_WALL_SECONDS:g} s"
        return {**record, "cls": TEST, "reason": reason}
    wall_note = f" with a {wall:g} s wall" if short_wall else ""
    return {**record, "cls": AMBIGUOUS,
            "reason": f"sub-second cycle{wall_note} but the intuition is not a suite literal"}


def classify_heartbeat(path: str, checkpoint_dir: str, test_checkpoints: set,
                       alive=None) -> dict:
    alive = alive or _pid_alive
    record = {"path": path, "kind": "heartbeat", "name": os.path.basename(path)}
    data = _load(path)
    if "_unreadable" in data:
        return {**record, "cls": KEEP, "reason": f"unreadable: {data['_unreadable']}"}
    pid = data.get("pid")
    stage = data.get("stage")
    timings = _timings_total(data.get("timings"))
    checkpoint = data.get("checkpoint")
    record.update({
        "pid": pid, "stage": stage, "status": data.get("status"),
        "phase": data.get("phase"), "timings_s": timings, "ts": _fmt_ts(data.get("ts")),
        "checkpoint": os.path.basename(checkpoint) if checkpoint else None,
    })
    if alive(pid):
        return {**record, "cls": KEEP, "reason": "pid alive"}
    if stage not in TERMINAL_HEARTBEAT_STAGES:
        return {**record, "cls": AMBIGUOUS,
                "reason": f"non-terminal stage {stage!r} (queued exit or killed cycle)"}
    if not checkpoint:
        return {**record, "cls": AMBIGUOUS, "reason": "terminal heartbeat without checkpoint"}
    local = os.path.join(checkpoint_dir, os.path.basename(checkpoint))
    if local in test_checkpoints:
        return {**record, "cls": TEST, "reason": "heartbeat of a TEST checkpoint"}
    if os.path.exists(local):
        return {**record, "cls": KEEP, "reason": "its checkpoint exists and is not TEST"}
    if timings is not None and timings < SUB_SECOND:
        return {**record, "cls": TEST,
                "reason": "orphan: checkpoint missing (only the suite deletes "
                          f"checkpoints) and timings total {timings:g} s < {SUB_SECOND:g} s"}
    return {**record, "cls": AMBIGUOUS,
            "reason": "orphan heartbeat with real or unknown duration"}


def classify_workspace(workspace: str, alive=None) -> list:
    alive = alive or _pid_alive
    checkpoint_dir = os.path.join(workspace, "cycle_checkpoints")
    progress_dir = os.path.join(workspace, "progress")
    records = []
    for path in sorted(glob.glob(os.path.join(checkpoint_dir, "*.json"))
                       + glob.glob(os.path.join(checkpoint_dir, "*.json.tmp"))):
        records.append(classify_checkpoint(path, alive))
    test_checkpoints = {r["path"] for r in records if r["cls"] == TEST}
    for path in sorted(glob.glob(os.path.join(progress_dir, "cycle_*.json"))):
        records.append(classify_heartbeat(path, checkpoint_dir, test_checkpoints, alive))
    return records


def _describe(r: dict) -> str:
    if r["kind"] == "checkpoint":
        detail = (f"stage={r.get('stage')} mode={r.get('mode')} wall={r.get('wall_s')} "
                  f"elapsed={r.get('elapsed_s')} timings={r.get('timings_s')} "
                  f"status={r.get('status')} created={r.get('created')} "
                  f"intuition={r.get('intuition')!r}")
    else:
        detail = (f"pid={r.get('pid')} stage={r.get('stage')} status={r.get('status')} "
                  f"phase={r.get('phase')} timings={r.get('timings_s')} ts={r.get('ts')} "
                  f"checkpoint={r.get('checkpoint')}")
    return f"  [{r['kind']}] {r['name']}\n      {detail}\n      -> {r['reason']}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="delete the TEST class (default is a dry run)")
    parser.add_argument("--all", action="store_true", help="also list KEEP files")
    parser.add_argument("--workspace", default=os.path.join(ROOT, "workspace"),
                        help="workspace directory holding progress/ and cycle_checkpoints/")
    args = parser.parse_args(argv)

    records = classify_workspace(args.workspace)
    groups = {cls: [r for r in records if r["cls"] == cls] for cls in (TEST, AMBIGUOUS, KEEP)}
    print(f"workspace: {args.workspace}")
    print(f"scanned: {sum(1 for r in records if r['kind'] == 'checkpoint')} checkpoints, "
          f"{sum(1 for r in records if r['kind'] == 'heartbeat')} heartbeats")
    verb = "DELETING" if args.apply else "would delete"
    print(f"\nTEST ({len(groups[TEST])}) -- {verb}:")
    for r in groups[TEST]:
        print(_describe(r))
    print(f"\nAMBIGUOUS ({len(groups[AMBIGUOUS])}) -- kept, decide by hand:")
    for r in groups[AMBIGUOUS]:
        print(_describe(r))
    if args.all:
        print(f"\nKEEP ({len(groups[KEEP])}):")
        for r in groups[KEEP]:
            print(_describe(r))
    else:
        print(f"\nKEEP ({len(groups[KEEP])}) -- real cycles, not listed (use --all)")

    if not args.apply:
        print("\nDry run: nothing deleted.  Re-run with --apply to delete the TEST class.")
        return 0
    deleted = 0
    for r in groups[TEST]:
        try:
            os.remove(r["path"])
            deleted += 1
        except OSError as exc:
            print(f"  could not delete {r['path']}: {exc}")
    print(f"\nDeleted {deleted} of {len(groups[TEST])} TEST files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
