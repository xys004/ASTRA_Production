"""core/cycle_telemetry: terminal classification, per-cycle rows, aggregates.

Fixtures mirror what astra_tool ACTUALLY writes. The heartbeat's failure stage is
'failed' (only the checkpoint carries the finer 'tool_error'/'partial'); the
checkpoint is not updated during the review loop (live round/budget live in the
heartbeat); a checkpoint stuck at an intermediate stage is a killed/in-flight
cycle, not a completed one; and cycles-to-result must be counted per goal.
"""
import json
import os
import tempfile
import time
import unittest

from core import cycle_telemetry as ct

GOAL_A = "Referee claim A: the vacuum-subtracted variance is negative for every t>0 in the free quench"
GOAL_B = "Referee claim B: totally unrelated objective about a different paper"
# Two goals sharing an 87-char prefix but differing later (snippet keying would merge them).
GOAL_C1 = GOAL_A + " -- variant one"
GOAL_C2 = GOAL_A + " -- variant two"


def _done(key="k1", pid=1, created=100.0, total=1200.0, rounds=1, status="VALIDATED",
          goal=GOAL_A, strict=None):
    d = {
        "cache_key": key, "pid": pid, "created_ts": created, "updated_ts": created + total,
        "stage": "done", "shared_goal": goal,
        "timings": {"conjecture": 300.0, "translate": 400.0, "review": 500.0, "total": total},
        "budget": {"total_seconds": 3600.0, "remaining_seconds": 3600.0 - total},
        "code_review_history": [{"status": "APPROVED"}] * rounds,
        "result": {"status": status},
    }
    if strict is not None:
        d["architecture"] = {"controls": {"translator_strict_contract": strict}}
    return d


def _tool_error(key="k2", pid=2, created=200.0, total=2000.0, rounds=3, goal=GOAL_A, strict=None):
    d = {
        "cache_key": key, "pid": pid, "created_ts": created, "updated_ts": created + total,
        "stage": "tool_error", "failed_phase": "reviewer", "shared_goal": goal,
        "error": "Independent reviewer did not approve the validation strategy after 2 model revision(s): ...",
        "timings": {"conjecture": 415.0, "translate": 431.0, "review": 561.0, "total": total},
        "budget": {"total_seconds": 3600.0, "remaining_seconds": 3600.0 - total},
        "code_review_history": [{"status": "REVISE"}] * rounds,
    }
    if strict is not None:
        d["architecture"] = {"controls": {"translator_strict_contract": strict}}
    return d


def _killed(key="k3", pid=3, created=300.0, goal=GOAL_A, strict=None):
    # Killed by the MCP timeout during review: checkpoint frozen at translation_complete,
    # no error, no result, no timings.total, no review history.
    d = {
        "cache_key": key, "pid": pid, "created_ts": created, "updated_ts": created + 900,
        "stage": "translation_complete", "shared_goal": goal,
        "timings": {"conjecture": 400.0, "translate": 500.0},
        "budget": {"total_seconds": 3600.0, "remaining_seconds": 2700.0},
    }
    if strict is not None:
        d["architecture"] = {"controls": {"translator_strict_contract": strict}}
    return d


class HeartbeatClassify(unittest.TestCase):
    def test_real_failure_heartbeat_stage_is_finished(self):
        # astra_tool's _fail writes the heartbeat with stage 'failed'.
        self.assertEqual(ct.classify("failed", alive=False), "finished")
        self.assertEqual(ct.classify("done", alive=False), "finished")

    def test_checkpoint_only_terminal_stages_are_also_finished(self):
        for st in ("partial", "tool_error", "code_error"):
            self.assertEqual(ct.classify(st, alive=False), "finished", st)

    def test_dead_process_before_terminal_is_killed(self):
        for st in ("start", "conjecture", "review", "translate_patch"):
            self.assertEqual(ct.classify(st, alive=False), "killed", st)

    def test_queued_then_dead_is_a_clean_exit_not_a_kill(self):
        # BUSY return after waiting for a slot (or a cache hit) leaves 'queued'.
        self.assertEqual(ct.classify("queued", alive=False), "exited")
        self.assertEqual(ct.classify("queued", alive=True), "running")

    def test_alive_nonterminal_is_running(self):
        self.assertEqual(ct.classify("review", alive=True), "running")


class CycleRecord(unittest.TestCase):
    def test_success_row(self):
        r = ct.cycle_record(_done(strict=True))
        self.assertEqual(r["state"], "finished")
        self.assertEqual(r["outcome"], "VALIDATED")
        self.assertTrue(r["decisive"])
        self.assertEqual(r["duration_s"], 1200.0)
        self.assertEqual(r["review_rounds"], 1)
        self.assertEqual(r["stop_cause"], "completed")
        self.assertIs(r["strict_contract"], True)
        self.assertEqual(r["goal_key"], GOAL_A)     # full identity, not the snippet

    def test_reviewer_failure_row(self):
        r = ct.cycle_record(_tool_error())
        self.assertEqual(r["state"], "finished")
        self.assertEqual(r["outcome"], "tool_error@reviewer")
        self.assertFalse(r["decisive"])
        self.assertEqual(r["review_rounds"], 3)
        self.assertTrue(r["stop_cause"].startswith("Independent reviewer did not approve"))
        # A checkpoint with genuinely no architecture block (e.g. one written
        # before this stamp existed) is unknown, not silently False.
        self.assertIsNone(r["strict_contract"])

    def test_reviewer_failure_carries_the_contract_that_produced_it(self):
        # Regression for "A not closed for failures": checkpoint_state now
        # stamps architecture at CREATION, so it survives into every save this
        # cycle makes, including the tool_error/failed/partial ones -- exactly
        # the outcomes the strict-translator overlay exists to reduce, and
        # previously the ones left unstamped.
        r = ct.cycle_record(_tool_error(strict=True))
        self.assertIs(r["strict_contract"], True)
        r2 = ct.cycle_record(_tool_error(strict=False))
        self.assertIs(r2["strict_contract"], False)

    def test_killed_checkpoint_is_incomplete_not_completed(self):
        r = ct.cycle_record(_killed())
        self.assertEqual(r["state"], "incomplete")
        self.assertEqual(r["outcome"], "incomplete@translation_complete")
        self.assertNotEqual(r["stop_cause"], "completed")
        self.assertIn("killed", r["stop_cause"])
        self.assertIsNone(r["duration_s"])
        self.assertFalse(r["decisive"])

    def test_killed_checkpoint_also_carries_the_contract_that_produced_it(self):
        # Same fix, incomplete side: a cycle killed mid-review still stamped
        # architecture at creation, so even a kill can be split by contract.
        r = ct.cycle_record(_killed(strict=True))
        self.assertIs(r["strict_contract"], True)


class Summarize(unittest.TestCase):
    def test_cycles_to_decisive_is_per_goal_not_across_goals(self):
        # The audit's scenario: goal A fails 4 times and is abandoned; goal B
        # succeeds on its first cycle. A global index would report 5.
        rows = [ct.cycle_record(_tool_error(key=f"a{i}", created=i, goal=GOAL_A)) for i in range(1, 5)]
        rows.append(ct.cycle_record(_done(key="b1", created=5, goal=GOAL_B)))
        agg = ct.summarize(rows)
        self.assertNotIn("cycles_to_first_decisive", agg)          # the misleading global is gone
        self.assertEqual(agg["per_goal"][GOAL_B]["cycles_to_decisive"], 1)
        self.assertIsNone(agg["per_goal"][GOAL_A]["cycles_to_decisive"])
        self.assertFalse(agg["per_goal"][GOAL_A]["decisive"])
        self.assertEqual(agg["goals"], 2)
        self.assertEqual(agg["goals_resolved"], 1)
        self.assertEqual(agg["latest_goal"]["goal"], ct._snippet(GOAL_B, 90))
        self.assertEqual(agg["latest_goal"]["cycles_to_decisive"], 1)

    def test_goal_that_resolves_on_third_cycle(self):
        rows = [ct.cycle_record(_tool_error(key="a1", created=1)),
                ct.cycle_record(_tool_error(key="a2", created=2)),
                ct.cycle_record(_done(key="a3", created=3))]
        agg = ct.summarize(rows)
        self.assertEqual(agg["per_goal"][GOAL_A]["cycles_to_decisive"], 3)
        self.assertEqual(agg["total_review_rounds"], 3 + 3 + 1)

    def test_incomplete_rows_are_counted_but_excluded_from_stats(self):
        rows = [ct.cycle_record(_killed(key="x", created=1)),
                ct.cycle_record(_done(key="y", created=2, total=1000.0))]
        agg = ct.summarize(rows)
        self.assertEqual(agg["cycles"], 2)
        self.assertEqual(agg["finished_cycles"], 1)
        self.assertEqual(agg["incomplete_cycles"], 1)
        self.assertEqual(agg["mean_duration_s"], 1000.0)           # killed row not averaged
        self.assertEqual(agg["by_outcome"]["incomplete@translation_complete"], 1)
        self.assertEqual(agg["per_goal"][GOAL_A]["cycles_to_decisive"], 2)  # counts the killed attempt

    def test_goals_with_shared_prefix_are_not_merged(self):
        rows = [ct.cycle_record(_done(key="c1", created=1, goal=GOAL_C1)),
                ct.cycle_record(_tool_error(key="c2", created=2, goal=GOAL_C2))]
        agg = ct.summarize(rows)
        self.assertEqual(agg["goals"], 2)
        self.assertTrue(agg["per_goal"][GOAL_C1]["decisive"])
        self.assertFalse(agg["per_goal"][GOAL_C2]["decisive"])

    def test_strict_cycles_are_countable_per_goal(self):
        rows = [ct.cycle_record(_done(key="s0", created=1, strict=False)),
                ct.cycle_record(_done(key="s1", created=2, strict=True))]
        self.assertEqual(ct.summarize(rows)["per_goal"][GOAL_A]["strict_cycles"], 1)


class EnrichProgress(unittest.TestCase):
    def _ckpt_file(self, d, obj, name="k_1.json"):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return p

    def test_real_pairing_failed_heartbeat_with_tool_error_checkpoint(self):
        # Production emits heartbeat stage 'failed' + phase, and a checkpoint at
        # 'tool_error' with the review history. Outcome must come from the checkpoint.
        with tempfile.TemporaryDirectory() as d:
            ck = self._ckpt_file(d, _tool_error())
            prog = {"pid": 2, "stage": "failed", "phase": "reviewer", "ts": 0,
                    "checkpoint": ck, "timings": {"total": 2000.0}}
            e = ct.enrich_progress(prog, alive=False)
        self.assertEqual(e["state"], "finished")
        self.assertEqual(e["outcome"], "tool_error@reviewer")
        self.assertEqual(e["review_rounds"], 3)

    def test_live_review_round_and_budget_come_from_the_heartbeat(self):
        # During the review loop the checkpoint is frozen at translation_complete
        # with no history; the heartbeat carries the live counters.
        with tempfile.TemporaryDirectory() as d:
            ck = self._ckpt_file(d, _killed())   # shape of a mid-review checkpoint
            prog = {"pid": 3, "stage": "review", "ts": time.time(), "checkpoint": ck,
                    "review_round": 3, "revision": 2,
                    "budget": {"total_seconds": 3600.0, "remaining_seconds": 1400.0}}
            e = ct.enrich_progress(prog, alive=True)
        self.assertEqual(e["state"], "running")
        self.assertEqual(e["review_rounds"], 3)          # not 0 from the stale checkpoint
        self.assertEqual(e["revision"], 2)
        self.assertEqual(e["budget_remaining_s"], 1400.0)  # not the frozen 2700

    def test_review_revision_heartbeat_also_carries_the_live_round(self):
        # Regression for "review round regresses to 0 during review_revision":
        # astra_tool now writes review_round (and budget) on that heartbeat too,
        # not just on 'review'.
        with tempfile.TemporaryDirectory() as d:
            ck = self._ckpt_file(d, _killed())
            prog = {"pid": 3, "stage": "review_revision", "ts": time.time(), "checkpoint": ck,
                    "review_round": 2, "revision": 1,
                    "budget": {"total_seconds": 3600.0, "remaining_seconds": 1400.0}}
            e = ct.enrich_progress(prog, alive=True)
        self.assertEqual(e["review_rounds"], 2)          # not 0 from the frozen checkpoint
        self.assertEqual(e["budget_remaining_s"], 1400.0)

    def test_status_on_a_non_terminal_heartbeat_never_leaks_as_the_outcome(self):
        # Regression: astra_tool writes a 'status' field (the analyst's verdict
        # for THAT attempt, e.g. CODE_ERROR/WEAK_PASS) on the non-terminal
        # 'retry' and 'quality_escalation' heartbeats, not only on 'done'.
        # Ungated, a running or killed cycle sitting there was reported as a
        # completed cycle with that verdict -- the exact mislabel defect C
        # removed on the checkpoint side, reintroduced on the heartbeat side.
        for stage in ("retry", "quality_escalation"):
            prog = {"pid": 7, "stage": stage, "status": "CODE_ERROR", "ts": time.time()}
            running = ct.enrich_progress(prog, alive=True)
            self.assertEqual(running["state"], "running", stage)
            self.assertNotEqual(running.get("outcome"), "CODE_ERROR", stage)

            killed = ct.enrich_progress(dict(prog, ts=0), alive=False)
            self.assertEqual(killed["state"], "killed", stage)
            self.assertNotEqual(killed.get("outcome"), "CODE_ERROR", stage)
            self.assertNotEqual(killed.get("stop_cause"), "completed", stage)

    def test_status_still_reported_when_the_heartbeat_stage_really_is_done(self):
        # The gate must not overcorrect: a real 'done' heartbeat's status is
        # exactly the fallback this path exists for.
        prog = {"pid": 8, "stage": "done", "status": "VALIDATED", "ts": 0}
        e = ct.enrich_progress(prog, alive=False)
        self.assertEqual(e["outcome"], "VALIDATED")
        self.assertEqual(e["stop_cause"], "completed")

    def test_missing_checkpoint_falls_back_to_heartbeat_verdict(self):
        prog = {"pid": 9, "stage": "done", "status": "VALIDATED", "ts": 0,
                "checkpoint": "C:/nonexistent/none.json", "timings": {"total": 50.0}}
        e = ct.enrich_progress(prog, alive=False)
        self.assertEqual(e["state"], "finished")
        self.assertEqual(e["outcome"], "VALIDATED")
        prog2 = {"pid": 10, "stage": "failed", "phase": "translator", "ts": 0}
        e2 = ct.enrich_progress(prog2, alive=False)
        self.assertEqual(e2["outcome"], "failed@translator")
        self.assertEqual(e2["failed_phase"], "translator")

    def test_newer_tmp_sibling_is_preferred(self):
        # A lost os.replace leaves <path> at 'failed' with no history while the
        # true terminal state sits in a newer <path>.tmp.
        with tempfile.TemporaryDirectory() as d:
            stale = dict(_tool_error()); stale["stage"] = "failed"; stale.pop("code_review_history")
            p = self._ckpt_file(d, stale, "k_2.json")
            tmp = self._ckpt_file(d, _tool_error(), "k_2.json.tmp")
            os.utime(p, (1000, 1000)); os.utime(tmp, (2000, 2000))
            rec = ct.cycle_record(ct.load_checkpoint(p))
            rows = ct.list_checkpoints(d)
        self.assertEqual(rec["outcome"], "tool_error@reviewer")
        self.assertEqual(rec["review_rounds"], 3)
        self.assertEqual(len(rows), 1)   # the .tmp is a sibling, never a second cycle


class ListCheckpoints(unittest.TestCase):
    def test_sorts_by_created_ts(self):
        with tempfile.TemporaryDirectory() as d:
            for name, obj in (("b_2.json", _done(key="b", created=20)),
                              ("a_1.json", _tool_error(key="a", created=10))):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    json.dump(obj, fh)
            rows = ct.list_checkpoints(d)
        self.assertEqual([r["cache_key"] for r in rows], ["a", "b"])

    def test_count_checkpoint_files_reports_the_full_total_independent_of_limit(self):
        # A caller compares this against `limit` to detect a windowed,
        # possibly-undercounted per-goal cycles_to_decisive (defect D's
        # remaining half: the window truncation itself, now surfaced rather
        # than silently returned as if it were the whole history).
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                with open(os.path.join(d, f"g_{i}.json"), "w", encoding="utf-8") as fh:
                    json.dump(_done(key=f"g{i}", created=i), fh)
            self.assertEqual(ct.count_checkpoint_files(d), 5)
            self.assertEqual(len(ct.list_checkpoints(d, limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
