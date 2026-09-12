import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remote.astra_remote_worker import command_for, detect_engine, run_code


class RemoteWorkerEngineTests(unittest.TestCase):
    def test_managed_markers_are_detected(self):
        self.assertEqual(detect_engine("# ASTRA_ENGINE: lean\nexample : True := by trivial"), "lean4")
        self.assertEqual(detect_engine("# ASTRA_ENGINE: sci\nprint('ok')"), "sci")
        self.assertEqual(detect_engine("# ASTRA_ENGINE: pkgs\nprint('ok')"), "pkgs")

    def test_managed_engines_use_central_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = Path(temporary) / "astra_engine.sh"
            runner.write_text("#!/bin/sh\n", encoding="utf-8")
            os.chmod(runner, 0o700)
            with patch.dict(
                os.environ,
                {"ASTRA_REMOTE_ENGINE_RUNNER": str(runner)},
                clear=False,
            ):
                command = command_for("lean4", str(Path(temporary) / "proof.lean"))
        self.assertEqual(command[0], str(runner))
        self.assertEqual(command[1], "lean")

    def test_python_still_executes_in_worker_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_code(
                "print(40 + 2)\nprint('VERDICT: PASS')",
                temporary,
                timeout=30,
            )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("42", result["stdout"])


if __name__ == "__main__":
    unittest.main()
