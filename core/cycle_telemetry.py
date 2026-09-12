"""Cycle progress and telemetry, read from ASTRA's own heartbeat/checkpoint files.

Pure standard library on purpose: this module is imported both by the MCP server
(its own venv) and by scripts/astra_progress.py, so it must not depend on the
astra_tool venv. It never writes anything.

Sources (both written by astra_tool.py):
  workspace/progress/cycle_<pid>.json           -- heartbeat, ONE file per pid,
      rewritten at every phase. Carries: stage, timings, and per-phase extras --
      during review: review_round / revision (live); several phases: budget
      (a snapshot with remaining_seconds); on done: status; on failed: phase.
  workspace/cycle_checkpoints/<key>_<pid>.json   -- full checkpoint: budget,
      code_review_history, error/failed_phase, result, architecture manifest.
      NOT updated during the review loop: it sits at translation_complete until
      review_complete or the terminal save. So live review counters must come
      from the heartbeat, and terminal detail from the checkpoint.

Terminal detection: the heartbeat's failure stage is 'failed' (only the checkpoint
carries the finer 'tool_error' / 'partial'); all of these are CLEAN finishes. A
dead process at a non-terminal stage is a kill (external timeout) -- except
'queued', where astra_tool returns BUSY (or a cache hit) without a terminal
heartbeat: that is a clean exit without a verdict, not a kill.
"""
from __future__ import annotations

import glob
import os
import statistics
import time
import json

# Stages a cycle ends on by itself. Heartbeats end on done/failed; checkpoints
# additionally record tool_error/partial (the _fail path) and code_error.
TERMINAL_CLEAN = frozenset({"done", "failed", "partial", "tool_error", "code_error"})
DECISIVE_STATUSES = frozenset({"VALIDATED", "REFUTED"})
# Clean exits that astra_tool does not mark with a terminal heartbeat: waiting
# for a cycle slot and returning BUSY, or a cache hit after 'queued'.
EXIT_WITHOUT_VERDICT = frozenset({"queued"})


def classify(stage: str | None, alive: bool) -> str:
    """Heartbeat state: 'running' | 'finished' | 'killed' | 'exited'."""
    if stage in TERMINAL_CLEAN:
        return "finished"
    if alive:
        return "running"
    if stage in EXIT_WITHOUT_VERDICT:
        return "exited"          # BUSY / cache-hit return, no verdict, not a kill
    return "killed"


def classify_checkpoint(stage: str | None) -> str:
    """Checkpoint state without liveness: 'finished' | 'incomplete'.

    A checkpoint left at conjecture_complete / translation_complete / ... never
    reached a terminal save: the cycle was killed by an external timeout or is
    still in flight. It must never be reported as a completed cycle.
    """
    return "finished" if stage in TERMINAL_CLEAN else "incomplete"


def load_json(path: str) -> dict | None:
    # Open/close as briefly as possible: astra_tool finalises checkpoints with
    # os.replace(), which fails on Windows while a reader holds the target open.
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        return json.loads(data)
    except Exception:
        return None


def load_checkpoint(path: str) -> dict | None:
    """Load a checkpoint, preferring a NEWER '<path>.tmp' sibling.

    astra_tool writes <path>.tmp and then os.replace()s it over <path>, swallowing
    any error. On Windows that replace raises PermissionError if a reader holds
    <path> open, so the fresher terminal state (e.g. tool_error + review history)
    can survive only in the .tmp while <path> stays at an earlier stage. Reading
    the newer sibling recovers the true final state.
    """
    tmp = path + ".tmp"
    candidate = path
    try:
        if os.path.exists(tmp) and os.path.getmtime(tmp) >= os.path.getmtime(path):
            candidate = tmp
    except OSError:
        candidate = path
    data = load_json(candidate)
    if data is None and candidate != path:
        data = load_json(path)
    return data


def _snippet(text, n: int = 160) -> str:
    text = str(text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 3] + "..."


def _strict_from(ckpt: dict):
    """The translator contract that produced this cycle, from its stamped manifest."""
    for block in (ckpt.get("architecture"), (ckpt.get("result") or {}).get("architecture")):
        controls = (block or {}).get("controls") if isinstance(block, dict) else None
        if isinstance(controls, dict) and "translator_strict_contract" in controls:
            return bool(controls["translator_strict_contract"])
    return None


def cycle_record(ckpt: dict) -> dict:
    """Normalise one checkpoint into a flat telemetry row."""
    timings = dict(ckpt.get("timings") or {})
    budget = dict(ckpt.get("budget") or {})
    result = ckpt.get("result") or {}
    status = result.get("status") if result else None
    failed_phase = ckpt.get("failed_phase")
    stage = ckpt.get("stage")
    state = classify_checkpoint(stage)
    if state == "finished":
        if status:
            outcome = str(status)
        elif failed_phase:
            outcome = f"{stage}@{failed_phase}"
        else:
            outcome = str(stage)
        stop_cause = _snippet(ckpt.get("error")) if ckpt.get("error") else "completed"
    else:
        outcome = f"incomplete@{stage}"
        stop_cause = "no terminal stage: killed by an external timeout, or still in flight"
    goal_full = str(ckpt.get("shared_goal") or "")
    return {
        "cache_key": ckpt.get("cache_key"),
        "pid": ckpt.get("pid"),
        "created_ts": ckpt.get("created_ts"),
        "updated_ts": ckpt.get("updated_ts"),
        "stage": stage,
        "state": state,
        "outcome": outcome,
        "decisive": state == "finished" and status in DECISIVE_STATUSES,
        "failed_phase": failed_phase,
        "stop_cause": stop_cause,
        "duration_s": timings.get("total") if state == "finished" else None,
        "phases_s": {k: v for k, v in timings.items() if k != "total"},
        "review_rounds": len(ckpt.get("code_review_history") or []),
        "budget_total_s": budget.get("total_seconds"),
        "budget_remaining_s": budget.get("remaining_seconds"),
        "max_mode": bool(ckpt.get("max_mode")),
        "strict_contract": _strict_from(ckpt),
        "goal_key": goal_full,            # identity: full text, never a snippet
        "goal": _snippet(goal_full, 90),  # display only
    }


def enrich_progress(progress: dict, alive: bool) -> dict:
    """Add state and detail to one heartbeat, preferring the heartbeat's own
    LIVE fields over the (possibly lagging) checkpoint."""
    out = dict(progress)
    stage = progress.get("stage")
    out["age_s"] = round(max(0.0, time.time() - float(progress.get("ts") or 0)), 1)
    out["alive"] = alive
    out["state"] = classify(stage, alive)

    ckpt_path = progress.get("checkpoint")
    ckpt = load_checkpoint(ckpt_path) if ckpt_path else None
    rec = cycle_record(ckpt) if ckpt else None

    # Review counters: the heartbeat carries the live round during the review
    # loop, when the checkpoint still has no history. After the loop the
    # heartbeat is overwritten by later phases and the checkpoint has the total.
    if "review_round" in progress:
        out["review_rounds"] = progress.get("review_round")
        out["revision"] = progress.get("revision")
    else:
        out["review_rounds"] = rec["review_rounds"] if rec else 0

    # Budget: heartbeat snapshot (fresh) beats the checkpoint's frozen copy.
    hb_budget = progress.get("budget") or {}
    if isinstance(hb_budget, dict) and hb_budget.get("remaining_seconds") is not None:
        out["budget_remaining_s"] = hb_budget.get("remaining_seconds")
        out["budget_total_s"] = hb_budget.get("total_seconds")
    elif rec:
        out["budget_remaining_s"] = rec["budget_remaining_s"]
        out["budget_total_s"] = rec["budget_total_s"]

    # Outcome: the finished checkpoint is the most specific source
    # (tool_error@reviewer beats the heartbeat's plain 'failed'); when the
    # checkpoint is missing or lagging, the heartbeat's own status/phase fields
    # still carry the verdict -- but ONLY on the heartbeat's own terminal stages
    # (done -> status, failed -> phase). astra_tool also writes a 'status' key
    # on two NON-terminal heartbeats (the post-oracle 'retry' and
    # 'quality_escalation', carrying the analyst's CODE_ERROR/WEAK_PASS verdict
    # for that attempt, not the cycle's). Ungated, a still-running or killed
    # cycle sitting at one of those stages was reported as a completed cycle
    # with that verdict -- reintroducing on the heartbeat side the exact
    # mislabel defect C removed on the checkpoint side.
    if rec and rec["state"] == "finished":
        out["outcome"] = rec["outcome"]
        out["stop_cause"] = rec["stop_cause"]
        out["failed_phase"] = rec["failed_phase"]
    elif stage == "done" and progress.get("status"):
        out["outcome"] = str(progress["status"])
        out["stop_cause"] = "completed"
    elif stage == "failed" and progress.get("phase"):
        out["outcome"] = f"failed@{progress['phase']}"
        out["failed_phase"] = progress.get("phase")
        out["stop_cause"] = f"failed in phase {progress['phase']}"
    if rec:
        out["cache_key"] = rec["cache_key"]
        out["strict_contract"] = rec["strict_contract"]
    return out


def list_checkpoints(checkpoint_dir: str, limit: int = 50) -> list[dict]:
    paths = glob.glob(os.path.join(checkpoint_dir, "*.json"))
    paths.sort(key=os.path.getmtime, reverse=True)
    rows = []
    for p in paths[:limit]:
        d = load_checkpoint(p)
        if d:
            rows.append(cycle_record(d))
    rows.sort(key=lambda r: r.get("created_ts") or 0)
    return rows


def count_checkpoint_files(checkpoint_dir: str) -> int:
    """Total checkpoints on disk, independent of any `limit`.

    Callers compare this against `limit` to tell whether a per-goal
    cycles_to_decisive figure can be truncated: a goal whose earlier attempts
    fell outside the `limit`-newest window undercounts. There is no per-goal
    fix for this short of scanning every checkpoint every call, so this is
    surfaced as an explicit "is the window smaller than the full history"
    signal instead.
    """
    return len(glob.glob(os.path.join(checkpoint_dir, "*.json")))


def summarize(rows: list[dict]) -> dict:
    """Aggregate telemetry, computed PER GOAL (never across unrelated goals).

    A killed/in-flight (incomplete) row IS counted toward its goal's `cycles`
    and therefore toward `cycles_to_decisive` once that goal resolves -- it is
    a cycle the goal actually cost, including the failed attempt. It is
    EXCLUDED only from `duration_s`/`mean_duration_s`/`median_duration_s` and
    from `total_review_rounds`/per-goal `rounds`, which need a real finished
    checkpoint to be meaningful.

    `rows` should come from `list_checkpoints`, whose `limit` bounds how far
    back this can see; a goal whose earlier attempts fall outside that window
    undercounts. `list_checkpoints`/`count_checkpoint_files` together let a
    caller detect and surface that (see astra_telemetry's `window` field).
    """
    finished = [r for r in rows if r.get("state") == "finished"]
    incomplete = [r for r in rows if r.get("state") != "finished"]
    durations = [r["duration_s"] for r in finished if isinstance(r.get("duration_s"), (int, float))]
    by_outcome: dict[str, int] = {}
    for r in rows:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1

    per_goal: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x.get("created_ts") or 0):
        g = per_goal.setdefault(
            r["goal_key"],
            {"goal": r["goal"], "cycles": 0, "finished": 0, "rounds": 0,
             "decisive": False, "cycles_to_decisive": None, "strict_cycles": 0,
             "last_created_ts": None},
        )
        g["cycles"] += 1
        g["last_created_ts"] = r.get("created_ts")
        if r.get("strict_contract"):
            g["strict_cycles"] += 1
        if r.get("state") == "finished":
            g["finished"] += 1
            g["rounds"] += r["review_rounds"]
            if r.get("decisive") and not g["decisive"]:
                g["decisive"] = True
                g["cycles_to_decisive"] = g["cycles"]   # cycles this goal needed
    latest = None
    if per_goal:
        key = max(per_goal, key=lambda k: per_goal[k]["last_created_ts"] or 0)
        latest = {"goal": per_goal[key]["goal"], **{k: v for k, v in per_goal[key].items() if k != "goal"}}
    return {
        "cycles": len(rows),
        "finished_cycles": len(finished),
        "incomplete_cycles": len(incomplete),
        "by_outcome": by_outcome,
        "decisive_cycles": sum(1 for r in finished if r.get("decisive")),
        "mean_duration_s": round(statistics.mean(durations), 1) if durations else None,
        "median_duration_s": round(statistics.median(durations), 1) if durations else None,
        "total_review_rounds": sum(r["review_rounds"] for r in finished),
        "goals": len(per_goal),
        "goals_resolved": sum(1 for g in per_goal.values() if g["decisive"]),
        "latest_goal": latest,
        "per_goal": per_goal,
    }
