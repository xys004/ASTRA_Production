"""One console per cycle: the launcher's guards and the follower's estimates.

The follower (scripts/astra_progress.py --follow) is exercised on synthetic
heartbeat/checkpoint files in a temp workspace; the launcher never spawns a
real console here (Popen is injected).
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import progress_window as pw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import astra_progress as ap  # noqa: E402


class Launcher(unittest.TestCase):
    def test_env_switch_and_test_runner_guard(self):
        self.assertFalse(pw.window_enabled({"ASTRA_PROGRESS_WINDOW": "0"}))
        self.assertFalse(pw.window_enabled({"ASTRA_PROGRESS_WINDOW": " off "}))
        self.assertTrue(pw.window_enabled({"ASTRA_PROGRESS_WINDOW": "1"}))
        # Absent under pytest: the runner guard wins (pytest is in sys.modules).
        self.assertFalse(pw.window_enabled({}))
        with patch.object(pw, "_under_test_runner", return_value=False):
            self.assertTrue(pw.window_enabled({}))

    def test_command_targets_the_follower_with_pid_linger_workspace_and_checkpoint(self):
        cmd = pw.follower_command(4242, workspace_root=r"C:\tmp\ws",
                                 env={"ASTRA_PROGRESS_WINDOW_LINGER": "'30'"}, python="py.exe",
                                 checkpoint=r"C:\tmp\ws\cycle_checkpoints\k_4242.json")
        self.assertEqual(cmd[0], "py.exe")
        self.assertTrue(cmd[1].endswith("astra_progress.py"))
        self.assertEqual(cmd[2:], ["--follow", "4242", "--linger", "30", "--workspace", r"C:\tmp\ws",
                                   "--checkpoint", r"C:\tmp\ws\cycle_checkpoints\k_4242.json"])
        # A bad linger value must not become an argparse error flashing in the window.
        self.assertEqual(pw.linger_seconds({"ASTRA_PROGRESS_WINDOW_LINGER": "soon"}), 120)
        self.assertEqual(pw.linger_seconds({"ASTRA_PROGRESS_WINDOW_LINGER": "-5"}), -1)

    def test_open_goes_through_a_hidden_start_trampoline_only_when_enabled(self):
        calls = []

        def fake_popen(args, **kwargs):
            calls.append((args, kwargs))
            return type("P", (), {"pid": 777})()

        with patch.object(os, "name", "nt"):
            self.assertIsNone(pw.open_progress_window(1, env={"ASTRA_PROGRESS_WINDOW": "0"}, popen=fake_popen))
            self.assertEqual(calls, [])
            pid = pw.open_progress_window(4242, workspace_root="ws", env={"ASTRA_PROGRESS_WINDOW": "1"},
                                          popen=fake_popen, checkpoint="ck.json")
        self.assertEqual(pid, 777)
        args, kwargs = calls[0]
        # cmd /c start "<title>" /D <root> <python> <follower> --follow 4242 ...: the
        # follower is not a child of the cycle, so taskkill /T cannot take it down.
        self.assertEqual(args[:3], ["cmd.exe", "/c", "start"])
        self.assertEqual(args[3], pw.WINDOW_TITLE)
        self.assertEqual(args[4:6], ["/D", str(pw.ROOT)])
        self.assertIn("--follow", args)
        self.assertIn("4242", args)
        self.assertEqual(args[args.index("--checkpoint") + 1], "ck.json")
        self.assertTrue(kwargs["creationflags"] & 0x08000000)     # CREATE_NO_WINDOW for cmd
        self.assertFalse(kwargs["creationflags"] & 0x00000010)    # the console comes from start
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[stream], pw.subprocess.DEVNULL)
        with patch.object(os, "name", "posix"):
            self.assertIsNone(pw.open_progress_window(1, env={"ASTRA_PROGRESS_WINDOW": "1"}, popen=fake_popen))

    def test_spawn_failure_never_raises(self):
        def broken(*_a, **_k):
            raise OSError("no console")

        with patch.object(os, "name", "nt"):
            self.assertIsNone(pw.open_progress_window(1, env={"ASTRA_PROGRESS_WINDOW": "1"}, popen=broken))


MEDIANS = {"structure": 100.0, "conjecture": 300.0, "translate": 200.0, "review": 300.0,
           "execute": 60.0, "analyze": 200.0, "navigate": 40.0}


class Estimates(unittest.TestCase):
    def test_progress_grows_through_the_phases_and_eta_shrinks(self):
        t0 = 1_000_000.0
        ckpt = {"created_ts": t0, "budget": {"remaining_seconds": 1400.0}}
        start = ap.estimate_progress({"stage": "start", "ts": t0}, ckpt, MEDIANS, t0 + 1)
        translate = ap.estimate_progress(
            {"stage": "translate", "ts": t0 + 300, "timings": {"conjecture": 300.0}}, ckpt, MEDIANS, t0 + 350)
        analyze = ap.estimate_progress(
            {"stage": "analyze", "ts": t0 + 900,
             "timings": {"conjecture": 300.0, "translate": 200.0, "review": 300.0, "execute": 60.0}},
            ckpt, MEDIANS, t0 + 950)
        self.assertLess(start["fraction"], translate["fraction"])
        self.assertLess(translate["fraction"], analyze["fraction"])
        self.assertGreater(start["remaining_s"], translate["remaining_s"])
        self.assertGreater(translate["remaining_s"], analyze["remaining_s"])
        self.assertEqual(start["phase"], "conjecture")
        self.assertEqual(translate["phases_done"], ["conjecture"])
        self.assertNotIn("structure", translate["order"])             # not seen in timings
        self.assertIn("navigate", translate["order"])                  # real median > 0
        self.assertFalse(translate["terminal"])
        self.assertAlmostEqual(translate["eta_ts"], t0 + 350 + translate["remaining_s"], places=0)

    def test_eta_is_capped_by_the_budget_and_never_reaches_100_before_the_end(self):
        t0 = 1_000_000.0
        ckpt = {"created_ts": t0, "budget": {"remaining_seconds": 100.0}}
        est = ap.estimate_progress({"stage": "conjecture", "ts": t0}, ckpt, MEDIANS, t0 + 10)
        self.assertLessEqual(est["remaining_s"], 90.0 + 1e-6)
        self.assertLess(est["fraction"], 1.0)
        long_running = ap.estimate_progress({"stage": "conjecture", "ts": t0}, {"created_ts": t0},
                                            MEDIANS, t0 + 5000)
        self.assertLessEqual(long_running["fraction"], 0.99)

    def test_unknown_stage_and_bad_timestamps_do_not_crash_or_claim_99_percent(self):
        t0 = 1_000_000.0
        est = ap.estimate_progress({"stage": "some_future_stage", "ts": t0 + 100,
                                    "timings": {"conjecture": 100.0}},
                                   {"created_ts": "not-a-number"}, MEDIANS, t0 + 150)
        self.assertFalse(est["terminal"])
        self.assertGreater(est["remaining_s"], 0.0)
        self.assertLess(est["fraction"], 0.9)
        self.assertIsNone(est["phase"])

    def test_terminal_and_killed(self):
        t0 = 1_000_000.0
        done = ap.estimate_progress({"stage": "done", "ts": t0 + 1836, "status": "VALIDATED",
                                     "timings": {"total": 1836.0}}, {"created_ts": t0}, MEDIANS, t0 + 1900)
        self.assertTrue(done["terminal"])
        self.assertEqual(done["fraction"], 1.0)
        self.assertEqual(done["elapsed_s"], 1836.0)
        killed = ap.estimate_progress({"stage": "translate", "ts": t0 + 400}, {"created_ts": t0},
                                      MEDIANS, t0 + 4000, alive=False)
        self.assertTrue(killed["terminal"])

    def test_medians_fall_back_when_the_pool_is_empty(self):
        with patch.object(ap.ct, "list_checkpoints", return_value=[]):
            medians = ap.phase_medians("nowhere")
        self.assertEqual(medians, ap.DEFAULT_MEDIANS)
        rows = [{"state": "finished", "phases_s": {"conjecture": 100.0, "translate_patch": 50.0}},
                {"state": "finished", "phases_s": {"conjecture": 300.0, "translate": 150.0}},
                {"state": "incomplete", "phases_s": {"conjecture": 9999.0}}]
        with patch.object(ap.ct, "list_checkpoints", return_value=rows):
            medians = ap.phase_medians("nowhere")
        self.assertEqual(medians["conjecture"], 200.0)
        self.assertEqual(medians["translate"], 100.0)        # translate_patch folds into translate
        self.assertEqual(medians["review"], ap.DEFAULT_MEDIANS["review"])


class FollowView(unittest.TestCase):
    def _workspace(self, tmp: Path, pid: int, heartbeat: dict, checkpoint: dict) -> tuple:
        progress = tmp / "progress"
        ckpts = tmp / "cycle_checkpoints"
        progress.mkdir()
        ckpts.mkdir()
        ckpt_path = ckpts / f"abc_{pid}.json"
        ckpt_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        heartbeat = {**heartbeat, "pid": pid, "checkpoint": str(ckpt_path)}
        (progress / f"cycle_{pid}.json").write_text(json.dumps(heartbeat), encoding="utf-8")
        return str(progress), str(ckpts)

    def test_running_view_names_the_instruction_phase_bar_and_eta(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            t0 = time.time() - 700
            progress, ckpts = self._workspace(
                tmp, 4242,
                {"stage": "review", "ts": time.time() - 100, "review_round": 1, "revision": 1,
                 "timings": {"conjecture": 400.0, "translate": 200.0}},
                {"created_ts": t0, "shared_goal": "Certify the accelerated warp fit.",
                 "intuition": "The fixed point converges once U0 is frozen.",
                 "budget": {"remaining_seconds": 3000.0}},
            )
            with patch.object(ap, "_pid_alive", return_value=True):
                text, terminal = ap.follow_view(4242, MEDIANS, progress, ckpts)
        self.assertFalse(terminal)
        self.assertIn("Objective : Certify the accelerated warp fit.", text)
        self.assertIn("Direction : The fixed point converges once U0 is frozen.", text)
        self.assertIn("Phase     : review (round 1, revision 1)", text)
        self.assertIn("ETA ~", text)
        self.assertIn("[#", text)
        self.assertIn("conjecture 6m40s", text)
        self.assertTrue(text.isascii(), text)

    def test_finished_view_shows_outcome_missing_inputs_and_stuck_class(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            t0 = time.time() - 2000
            progress, ckpts = self._workspace(
                tmp, 4243,
                {"stage": "done", "ts": time.time() - 5, "status": "NON_DECIDABLE",
                 "timings": {"conjecture": 800.0, "total": 1836.0}},
                {"created_ts": t0, "shared_goal": "g", "intuition": "i",
                 "result": {"status": "NON_DECIDABLE", "missing_inputs": ["U0", "the ansatz"]},
                 "code_review": {"stuck_diagnosis": {"stuck_classes": ["assumed_bound"]}}},
            )
            with patch.object(ap, "_pid_alive", return_value=False):
                text, terminal = ap.follow_view(4243, MEDIANS, progress, ckpts)
        self.assertTrue(terminal)
        self.assertIn("[FINISHED]", text)
        self.assertIn("Outcome   : NON_DECIDABLE", text)
        self.assertIn("Missing   : U0; the ansatz", text)
        self.assertIn("Stuck on  : assumed_bound", text)
        self.assertIn("100%", text)

    def test_view_is_bound_to_its_checkpoint_when_the_pid_moves_on(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            progress, ckpts = self._workspace(
                tmp, 4244,
                {"stage": "translate", "ts": time.time() - 10, "timings": {"conjecture": 50.0}},
                {"created_ts": time.time() - 60, "shared_goal": "next step", "intuition": "i"},
            )
            with patch.object(ap, "_pid_alive", return_value=True):
                bound, terminal = ap.follow_view(4244, MEDIANS, progress, ckpts,
                                                 expected_checkpoint=str(tmp / "cycle_checkpoints" / "abc_4244.json"))
                other, ended = ap.follow_view(4244, MEDIANS, progress, ckpts,
                                              expected_checkpoint=r"C:\elsewhere\old_4244.json")
        self.assertFalse(terminal)
        self.assertIn("Objective : next step", bound)
        self.assertTrue(ended)
        self.assertIn("has ended; the same process now runs another one", other)

    def test_checkpoint_is_read_once_per_heartbeat(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            progress, ckpts = self._workspace(
                tmp, 4245, {"stage": "review", "ts": 1_000_000.0, "timings": {}},
                {"created_ts": 999_900.0, "shared_goal": "g", "intuition": "i"},
            )
            cache = {}
            with patch.object(ap, "_pid_alive", return_value=True), patch.object(
                ap.ct, "load_checkpoint", wraps=ap.ct.load_checkpoint
            ) as loader:
                ap.follow_view(4245, MEDIANS, progress, ckpts, now=1_000_010.0, cache=cache)
                ap.follow_view(4245, MEDIANS, progress, ckpts, now=1_000_012.0, cache=cache)
        self.assertEqual(loader.call_count, 1)

    def test_no_heartbeat_yet(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ap, "_pid_alive", return_value=True):
                text, terminal = ap.follow_view(9, MEDIANS, directory, directory)
        self.assertIn("waiting for its first heartbeat", text)
        self.assertFalse(terminal)


if __name__ == "__main__":
    unittest.main()
