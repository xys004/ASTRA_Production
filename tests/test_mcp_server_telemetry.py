"""astra_probe and astra_telemetry against a temp ASTRA_ROOT.

The concurrency test suite already stubs the mcp package so mcp_server.server
imports without the real SDK; this file imports the SAME already-loaded module
(sys.modules caches it) and drives its file-reading tools against a temporary
workspace, so it never touches the real production checkpoints/progress dirs.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tests.test_mcp_server_concurrency import server_module


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


class AstraTelemetryWindow(unittest.TestCase):
    def test_window_reports_truncation_when_more_files_exist_than_limit(self):
        with tempfile.TemporaryDirectory() as root:
            ckpt_dir = os.path.join(root, "workspace", "cycle_checkpoints")
            os.makedirs(ckpt_dir)
            for i in range(5):
                _write(os.path.join(ckpt_dir, f"g{i}_1.json"), {
                    "cache_key": f"g{i}", "pid": 1, "created_ts": i, "stage": "done",
                    "shared_goal": "g", "timings": {"total": 10.0}, "result": {"status": "VALIDATED"},
                })
            with patch.object(server_module, "ASTRA_ROOT", root):
                full = json.loads(server_module.astra_telemetry(limit=30))
                windowed = json.loads(server_module.astra_telemetry(limit=2))
        self.assertEqual(full["summary"]["window"], {"limit": 30, "total_checkpoints": 5, "truncated": False})
        self.assertEqual(windowed["summary"]["window"], {"limit": 2, "total_checkpoints": 5, "truncated": True})
        self.assertEqual(len(windowed["cycles"]), 2)
        # The tool description's own promise: no leftover reference to the
        # removed global metric.
        self.assertNotIn("cycles_to_first_decisive", server_module.astra_telemetry.__doc__)

    def test_strict_contract_column_reaches_the_row(self):
        with tempfile.TemporaryDirectory() as root:
            ckpt_dir = os.path.join(root, "workspace", "cycle_checkpoints")
            os.makedirs(ckpt_dir)
            _write(os.path.join(ckpt_dir, "s_1.json"), {
                "cache_key": "s", "pid": 1, "created_ts": 1, "stage": "tool_error",
                "failed_phase": "reviewer", "shared_goal": "g", "error": "rejected",
                "timings": {"total": 5.0}, "code_review_history": [{"status": "REVISE"}],
                "architecture": {"controls": {"translator_strict_contract": True}},
            })
            with patch.object(server_module, "ASTRA_ROOT", root):
                out = json.loads(server_module.astra_telemetry(limit=10))
        self.assertIs(out["cycles"][0]["strict_contract"], True)
        self.assertEqual(out["cycles"][0]["outcome"], "tool_error@reviewer")


class AstraProbeHint(unittest.TestCase):
    def _probe(self, root, alive):
        with patch.object(server_module, "ASTRA_ROOT", root), \
             patch.object(server_module, "_pid_alive", return_value=alive):
            return json.loads(server_module.astra_probe())

    def test_finished_tool_error_reads_as_terminated_cleanly_not_as_a_kill(self):
        with tempfile.TemporaryDirectory() as root:
            prog_dir = os.path.join(root, "workspace", "progress")
            ckpt_dir = os.path.join(root, "workspace", "cycle_checkpoints")
            os.makedirs(prog_dir)
            os.makedirs(ckpt_dir)
            ck = os.path.join(ckpt_dir, "k_9.json")
            _write(ck, {
                "cache_key": "k", "pid": 9, "created_ts": 1, "stage": "tool_error",
                "failed_phase": "reviewer", "shared_goal": "g",
                "error": "Independent reviewer did not approve ...",
                "timings": {"total": 900.0}, "code_review_history": [{"status": "REVISE"}] * 3,
            })
            _write(os.path.join(prog_dir, "cycle_9.json"),
                  {"pid": 9, "stage": "failed", "phase": "reviewer", "ts": 0, "checkpoint": ck})
            out = self._probe(root, alive=False)
        self.assertEqual(out["recent"][0]["state"], "finished")
        self.assertIn("TERMINO limpio", out["hint"])
        self.assertNotIn("MURIO", out["hint"])

    def test_exited_queued_hint_states_ambiguity_not_a_clean_fact(self):
        with tempfile.TemporaryDirectory() as root:
            prog_dir = os.path.join(root, "workspace", "progress")
            os.makedirs(prog_dir)
            _write(os.path.join(prog_dir, "cycle_11.json"),
                  {"pid": 11, "stage": "queued", "ts": 0})
            out = self._probe(root, alive=False)
        self.assertEqual(out["recent"][0]["state"], "exited")
        # Must not overclaim a clean exit as settled fact -- it is genuinely
        # ambiguous between a BUSY/cache-hit return and a kill while queued.
        self.assertIn("ambiguo", out["hint"])

    def test_status_on_non_terminal_heartbeat_does_not_leak_into_the_probe(self):
        with tempfile.TemporaryDirectory() as root:
            prog_dir = os.path.join(root, "workspace", "progress")
            os.makedirs(prog_dir)
            _write(os.path.join(prog_dir, "cycle_12.json"),
                  {"pid": 12, "stage": "retry", "status": "CODE_ERROR", "ts": 0})
            out = self._probe(root, alive=False)
        self.assertEqual(out["recent"][0]["state"], "killed")
        self.assertNotEqual(out["recent"][0].get("outcome"), "CODE_ERROR")


if __name__ == "__main__":
    unittest.main()
