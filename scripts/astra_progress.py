#!/usr/bin/env python3
"""Watch ASTRA cycles from a terminal, and summarise cycle telemetry.

  python scripts/astra_progress.py              one-shot: in-flight + recent
  python scripts/astra_progress.py --watch 30   refresh every 30 s (Ctrl+C to stop)
  python scripts/astra_progress.py --summary    per-cycle table + per-goal aggregates
  python scripts/astra_progress.py --follow PID one cycle: instruction, phase, bar, ETA
                                                (core/progress_window.py opens one such
                                                console per cycle on Windows)

Read-only; uses the same heartbeat/checkpoint files ASTRA already writes
(core/cycle_telemetry.py). ASCII-only output on purpose so a Windows console
with a cp1252 locale never chokes on it. Reads are brief: astra_tool finalises
checkpoints with os.replace(), which a held-open target can make fail on Windows.
"""
from __future__ import annotations

import argparse
import glob
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import cycle_telemetry as ct  # noqa: E402

PROGRESS_DIR = os.path.join(ROOT, "workspace", "progress")
CKPT_DIR = os.path.join(ROOT, "workspace", "cycle_checkpoints")

# --follow: phase order and the heartbeat stages that belong to each phase.
PHASES = ("structure", "conjecture", "translate", "review", "execute", "analyze", "navigate")
STAGE_TO_PHASE = {
    "start": "conjecture", "structure": "structure", "conjecture": "conjecture",
    "conjecture_reused": "translate",     # resume_checkpoint: the conjecture is already paid for
    "translate": "translate", "translate_retry_minimal": "translate",
    "review": "review", "review_revision": "review", "model_patch": "review",
    "review_regeneration": "review", "quality_escalation": "review",
    "execute": "execute", "analyze": "analyze", "retry": "translate",
    "navigate": "navigate",
}
TERMINAL_STAGES = {"done", "failed"}
# Fallback medians (seconds) when the checkpoint pool has no finished cycles:
# rounded from the 2026-09 production pool.
DEFAULT_MEDIANS = {"structure": 120.0, "conjecture": 350.0, "translate": 300.0,
                   "review": 300.0, "execute": 60.0, "analyze": 200.0, "navigate": 40.0}


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _fmt_s(v) -> str:
    return "-" if v is None else f"{float(v):.0f}s"


def live_view(recent_n: int = 5) -> str:
    files = sorted(glob.glob(os.path.join(PROGRESS_DIR, "cycle_*.json")),
                   key=os.path.getmtime, reverse=True)[:12]
    in_flight, recent = [], []
    for f in files:
        d = ct.load_json(f)
        if not d:
            continue
        e = ct.enrich_progress(d, _pid_alive(d.get("pid")))
        (in_flight if e["state"] == "running" else recent).append(e)
    lines = [f"ASTRA cycles @ {time.strftime('%H:%M:%S')}"]
    if in_flight:
        for e in in_flight:
            ph = e.get("timings") or {}
            rev = f" revision={e['revision']}" if e.get("revision") is not None else ""
            strict = " strict" if e.get("strict_contract") else ""
            lines.append(
                f"  RUNNING pid={e.get('pid')} phase={e.get('stage')} heartbeat={e['age_s']}s ago "
                f"round={e.get('review_rounds', 0)}{rev} budget_left={_fmt_s(e.get('budget_remaining_s'))}"
                f"{strict} phases={{{', '.join(f'{k}:{_fmt_s(v)}' for k, v in ph.items() if k != 'total')}}}"
            )
    else:
        lines.append("  (no cycle in flight)")
    if recent:
        lines.append("  recent:")
        for e in recent[:recent_n]:
            tag = {"finished": "FINISHED", "exited": "EXITED", "killed": "KILLED"}.get(e["state"], e["state"])
            strict = " strict" if e.get("strict_contract") else ""
            lines.append(
                f"    {tag} pid={e.get('pid')} outcome={e.get('outcome', e.get('stage'))}"
                f" rounds={e.get('review_rounds', 0)} total={_fmt_s((e.get('timings') or {}).get('total'))}"
                f"{strict} cause={e.get('stop_cause', '-')}"
            )
    return "\n".join(lines)


def phase_medians(checkpoint_dir: str = None, limit: int = 40) -> dict:
    """Median seconds per phase over recent FINISHED cycles, with fallbacks."""
    rows = ct.list_checkpoints(checkpoint_dir or CKPT_DIR, limit=limit)
    samples = {p: [] for p in PHASES}
    for r in rows:
        if r.get("state") != "finished":
            continue
        for phase, seconds in (r.get("phases_s") or {}).items():
            key = "translate" if phase == "translate_patch" else phase
            if key in samples and isinstance(seconds, (int, float)) and seconds > 0:
                samples[key].append(float(seconds))
    return {p: (statistics.median(v) if v else DEFAULT_MEDIANS[p]) for p, v in samples.items()}


def estimate_progress(heartbeat: dict, checkpoint: dict, medians: dict, now: float,
                      alive: bool = True) -> dict:
    """Pure: where the cycle is, how far along, and when it should end.

    Progress = elapsed / (elapsed + remaining). Remaining = what is left of the
    current phase (its median minus the time since the last heartbeat, never
    below 10% of the median) plus the medians of the phases still ahead;
    capped by the budget when the checkpoint carries one. A structure phase is
    counted only if the heartbeat shows it; navigation only if its median
    comes from real cycles (it is opt-in).
    """
    heartbeat = heartbeat or {}
    checkpoint = checkpoint or {}
    stage = str(heartbeat.get("stage") or "start")
    timings = {k: v for k, v in (heartbeat.get("timings") or {}).items()
               if isinstance(v, (int, float))}

    def _num(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    started = _num(checkpoint.get("created_ts"), _num(heartbeat.get("ts"), now))
    elapsed = max(0.0, now - started)
    beat_age = max(0.0, now - _num(heartbeat.get("ts"), now))
    terminal = stage in TERMINAL_STAGES or (not alive and stage not in ("queued",))
    if stage in TERMINAL_STAGES:
        elapsed = float(timings.get("total") or elapsed)
    phase = STAGE_TO_PHASE.get(stage)
    order = [p for p in PHASES if p != "structure" or "structure" in timings or phase == "structure"]
    if medians.get("navigate", 0) <= 0:
        order = [p for p in order if p != "navigate"]
    remaining = 0.0
    if not terminal and phase in order:
        index = order.index(phase)
        current_median = float(medians.get(phase, 0.0))
        remaining += max(current_median * 0.1, current_median - beat_age)
        remaining += sum(float(medians.get(p, 0.0)) for p in order[index + 1:])
    elif not terminal and stage == "queued":
        remaining = sum(float(medians.get(p, 0.0)) for p in order)
    elif not terminal:
        # A stage this script does not know (a newer astra_tool): estimate
        # from the phases with no time recorded yet instead of claiming 99%.
        remaining = sum(float(medians.get(p, 0.0)) for p in order if p not in timings)
    budget = dict(checkpoint.get("budget") or heartbeat.get("budget") or {})
    budget_left = budget.get("remaining_seconds")
    if isinstance(budget_left, (int, float)) and budget_left >= 0 and not terminal:
        # the checkpoint snapshot ages between saves
        budget_left = max(0.0, float(budget_left) - beat_age)
        remaining = min(remaining, budget_left) if remaining else remaining
    fraction = 1.0 if terminal else (elapsed / (elapsed + remaining) if (elapsed + remaining) > 0 else 0.0)
    fraction = min(0.99, fraction) if not terminal else 1.0
    return {
        "stage": stage,
        "phase": phase if not terminal else stage,
        "terminal": terminal,
        "elapsed_s": round(elapsed, 1),
        "remaining_s": round(remaining, 1) if not terminal else 0.0,
        "eta_ts": None if terminal else now + remaining,
        "fraction": round(fraction, 3),
        "beat_age_s": round(beat_age, 1),
        "budget_left_s": (round(float(budget_left), 1)
                          if isinstance(budget_left, (int, float)) else None),
        "phases_done": [p for p in order if p in timings and p != phase],
        "order": order,
    }


def _bar(fraction: float, width: int = 30) -> str:
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _fmt_dur(seconds) -> str:
    if seconds is None:
        return "-"
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def _one_line(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def follow_view(pid: int, medians: dict, progress_dir: str = None,
                checkpoint_dir: str = None, now: float = None,
                expected_checkpoint: str = None, cache: dict = None) -> tuple:
    """(text, terminal) for one cycle. ASCII only (cp1252 consoles).

    ``expected_checkpoint`` binds the view to ONE cycle: campaign steps run
    several cycles in the same process, so cycle_<pid>.json is rewritten by
    the next one; a heartbeat naming another checkpoint means this cycle is
    over. ``cache`` (a dict) avoids re-reading the checkpoint while the
    heartbeat has not changed: astra_tool finalises it with os.replace, which
    a reader holding it open can make fail on Windows.
    """
    now = now if now is not None else time.time()
    hb_path = os.path.join(progress_dir or PROGRESS_DIR, f"cycle_{pid}.json")
    heartbeat = ct.load_json(hb_path) or {}
    alive = _pid_alive(pid)
    if not heartbeat:
        waited = "" if alive else " (process not running)"
        return (f"ASTRA 1.0 cycle pid {pid}: waiting for its first heartbeat{waited}...", not alive)
    ckpt_path = heartbeat.get("checkpoint")
    if expected_checkpoint and ckpt_path and (
        os.path.basename(str(ckpt_path)) != os.path.basename(str(expected_checkpoint))
    ):
        return (
            f"ASTRA 1.0 cycle pid {pid}: this cycle ({os.path.basename(str(expected_checkpoint))}) "
            f"has ended; the same process now runs another one "
            f"({os.path.basename(str(ckpt_path))}).",
            True,
        )
    ckpt = {}
    if ckpt_path:
        key = (str(ckpt_path), heartbeat.get("ts"), heartbeat.get("stage"))
        if cache is not None and cache.get("key") == key:
            ckpt = cache.get("ckpt") or {}
        else:
            local = os.path.join(checkpoint_dir or CKPT_DIR, os.path.basename(str(ckpt_path)))
            ckpt = ct.load_checkpoint(local if os.path.exists(local) else str(ckpt_path)) or {}
            if cache is not None:
                cache["key"] = key
                cache["ckpt"] = ckpt
    est = estimate_progress(heartbeat, ckpt, medians, now, alive)
    request = ckpt.get("request") or {}
    objective = ckpt.get("shared_goal") or "-"
    direction = request.get("original") or ckpt.get("intuition") or "-"
    result = (ckpt.get("result") or {}) if isinstance(ckpt.get("result"), dict) else {}
    state = ("FINISHED" if heartbeat.get("stage") in TERMINAL_STAGES
             else ("KILLED" if est["terminal"] else "running"))
    lines = [
        f"ASTRA 1.0 cycle  pid {pid}  started {time.strftime('%H:%M:%S', time.localtime(ckpt.get('created_ts') or heartbeat.get('ts') or now))}  [{state}]",
        f"Objective : {_one_line(objective, 96)}",
        f"Direction : {_one_line(direction, 96)}",
    ]
    if request.get("structured"):
        lines.append(f"Structured: {_one_line(request['structured'], 96)}")
    phase_note = est["phase"] or est["stage"]
    if heartbeat.get("stage") in ("review", "review_revision", "model_patch", "review_regeneration"):
        phase_note += (f" (round {heartbeat.get('review_round', 0)}"
                       f", revision {heartbeat.get('revision', 0)})")
    elif heartbeat.get("stage") == "retry":
        phase_note += f" (post-oracle retry {heartbeat.get('n', '?')}, {heartbeat.get('status', '')})"
    elif heartbeat.get("stage") == "queued":
        phase_note += f" (waiting for the cycle slot, {_fmt_dur(heartbeat.get('waited_s'))})"
    budget = f"   budget left {_fmt_dur(est['budget_left_s'])}" if est["budget_left_s"] is not None else ""
    lines.append(f"Phase     : {phase_note:<44} elapsed {_fmt_dur(est['elapsed_s'])}{budget}")
    if est["terminal"]:
        status = result.get("status") or heartbeat.get("status") or heartbeat.get("phase") or est["stage"]
        lines.append(f"Progress  : {_bar(1.0)} 100%   {state} in {_fmt_dur(est['elapsed_s'])}")
        lines.append(f"Outcome   : {status}")
        if heartbeat.get("stage") == "failed":
            lines.append(f"Failed in : {heartbeat.get('phase', '-')}")
        error = ckpt.get("error")
        if error:
            lines.append(f"Cause     : {_one_line(error, 200)}")
        missing = result.get("missing_inputs") or []
        if missing:
            lines.append("Missing   : " + "; ".join(_one_line(m, 60) for m in missing[:8]))
        stuck = ((ckpt.get("code_review") or {}).get("stuck_diagnosis") or {}).get("stuck_classes")
        if stuck:
            lines.append(f"Stuck on  : {', '.join(stuck)}")
    else:
        eta = time.strftime("%H:%M", time.localtime(est["eta_ts"])) if est["eta_ts"] else "-"
        lines.append(
            f"Progress  : {_bar(est['fraction'])} {int(est['fraction'] * 100):3d}%   "
            f"ETA ~ {eta} (about {_fmt_dur(est['remaining_s'])} more, from recent cycles' medians)"
        )
    timings = heartbeat.get("timings") or {}
    marks = []
    for p in est["order"]:
        if p == est["phase"] and not est["terminal"]:
            marks.append(f"{p} {_fmt_dur(timings.get(p))}*" if timings.get(p) else f"{p} ...")
        elif p in timings:
            marks.append(f"{p} {_fmt_dur(timings[p])}")
        else:
            marks.append(f"{p} -")
    lines.append("Phases    : " + " | ".join(marks))
    hint = "" if est["terminal"] else "   (Ctrl+C closes this window; the cycle keeps running)"
    lines.append(f"Last beat : {_fmt_dur(est['beat_age_s'])} ago{hint}")
    return ("\n".join(lines), est["terminal"])


def _set_title(text: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text[:200])
    except Exception:
        pass


def follow(pid: int, linger: int, progress_dir: str = None, checkpoint_dir: str = None,
           refresh: float = 2.0, checkpoint: str = None) -> int:
    _set_title(f"ASTRA 1.0 cycle {pid}")
    try:
        # A cp1252 console must not die on a Greek letter in the objective.
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    try:
        medians = phase_medians(checkpoint_dir)
    except Exception:
        medians = dict(DEFAULT_MEDIANS)
    cache = {}
    titled = False
    try:
        while True:
            try:
                text, terminal = follow_view(pid, medians, progress_dir, checkpoint_dir,
                                             expected_checkpoint=checkpoint, cache=cache)
            except Exception as exc:              # the window must never die on a view error
                text, terminal = (f"ASTRA 1.0 cycle pid {pid}: view error ({exc!r}); retrying...", False)
            if not titled:
                objective = _one_line((cache.get("ckpt") or {}).get("shared_goal") or "", 70)
                if objective:
                    _set_title(f"ASTRA 1.0 cycle {pid}: {objective}")
                    titled = True
            os.system("cls" if os.name == "nt" else "clear")
            print(text)
            if terminal:
                if linger < 0:
                    try:
                        input("\n(press Enter to close)")
                    except EOFError:
                        pass
                elif linger:
                    print(f"\n(closing in {linger}s)")
                    time.sleep(linger)
                return 0
            time.sleep(refresh)
    except KeyboardInterrupt:
        return 0


def summary_view(limit: int = 30) -> str:
    rows = ct.list_checkpoints(CKPT_DIR, limit=limit)
    agg = ct.summarize(rows)
    lines = [f"ASTRA cycle telemetry (last {len(rows)} cycles)", ""]
    lines.append(f"{'#':>3} {'state':<10} {'outcome':<26} {'rnd':>3} {'total':>7} {'strict':<6} stop cause")
    for i, r in enumerate(rows, start=1):
        strict = "yes" if r.get("strict_contract") else ("no" if r.get("strict_contract") is False else "-")
        lines.append(
            f"{i:>3} {r['state']:<10} {r['outcome']:<26} {r['review_rounds']:>3} "
            f"{_fmt_s(r['duration_s']):>7} {strict:<6} {r['stop_cause']}"
        )
    lines.append("")
    lines.append(
        f"cycles={agg['cycles']} finished={agg['finished_cycles']} incomplete={agg['incomplete_cycles']} "
        f"decisive={agg['decisive_cycles']} goals={agg['goals']} resolved={agg['goals_resolved']} "
        f"mean={_fmt_s(agg['mean_duration_s'])} median={_fmt_s(agg['median_duration_s'])} "
        f"review_rounds_total={agg['total_review_rounds']}"
    )
    lg = agg.get("latest_goal")
    if lg:
        lines.append(
            f"latest goal: '{lg['goal']}' -> cycles={lg['cycles']} finished={lg['finished']} "
            f"rounds={lg['rounds']} decisive={lg['decisive']} cycles_to_decisive={lg['cycles_to_decisive']}"
        )
    lines.append(f"by_outcome={agg['by_outcome']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="refresh interval; omit for one-shot")
    ap.add_argument("--summary", action="store_true", help="per-cycle telemetry table + aggregates")
    ap.add_argument("--limit", type=int, default=30, help="cycles to include in --summary")
    ap.add_argument("--follow", type=int, metavar="PID", help="follow ONE cycle: phase, bar, ETA")
    ap.add_argument("--linger", type=int, default=120,
                    help="--follow: seconds to keep the view after the cycle ends (-1 = until Enter)")
    ap.add_argument("--workspace", default=None,
                    help="workspace directory (default: <checkout>/workspace; ASTRA_WORKSPACE_ROOT cycles pass theirs)")
    ap.add_argument("--checkpoint", default=None,
                    help="--follow: bind the view to this checkpoint (a later cycle in the same pid ends it)")
    args = ap.parse_args()
    global PROGRESS_DIR, CKPT_DIR
    if args.workspace:
        PROGRESS_DIR = os.path.join(args.workspace, "progress")
        CKPT_DIR = os.path.join(args.workspace, "cycle_checkpoints")
    if args.follow:
        return follow(args.follow, args.linger, PROGRESS_DIR, CKPT_DIR, checkpoint=args.checkpoint)
    if args.summary:
        print(summary_view(args.limit))
        return 0
    if not args.watch:
        print(live_view())
        return 0
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(live_view())
            print(f"\n(refreshing every {args.watch}s; Ctrl+C to stop)")
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
