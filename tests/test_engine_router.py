import os
import subprocess
import unittest
from unittest.mock import patch

from core.engine_router import (
    _command_for,
    _configured_wsl_lean4,
    _native_or_wsl,
    detect_engine,
    wsl_probe_state,
)


class EngineRouterTests(unittest.TestCase):
    def test_managed_astrum_engines_are_detected(self):
        self.assertEqual(
            detect_engine("# ASTRA_ENGINE: pkgs\nprint('ok')"),
            "pkgs",
        )
        self.assertEqual(
            detect_engine("# ASTRA_ENGINE: sci\nprint('ok')"),
            "sci",
        )

    @staticmethod
    def _which(command):
        return r"C:\Windows\System32\wsl.exe" if command == "wsl" else None

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which")
    @patch("core.engine_router.subprocess.run")
    def test_explicit_wsl_distro_is_used_for_detection(
        self,
        run,
        which,
        _is_windows,
    ):
        which.side_effect = self._which
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/usr/bin/sage\n",
            stderr="",
        )
        with patch.dict(os.environ, {"ASTRA_WSL_DISTRO": "Debian"}, clear=False):
            location = _native_or_wsl("sage")

        self.assertEqual(location, "wsl -d Debian -- sage")
        self.assertEqual(
            run.call_args.args[0],
            ["wsl", "-d", "Debian", "--", "which", "sage"],
        )

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which")
    @patch("core.engine_router.subprocess.run")
    def test_explicit_wsl_distro_is_used_for_execution(
        self,
        run,
        which,
        _is_windows,
    ):
        which.side_effect = self._which
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/usr/bin/sage\n",
            stderr="",
        )
        with patch.dict(os.environ, {"ASTRA_WSL_DISTRO": "Debian"}, clear=False):
            command = _command_for("sage", r"C:\work\validator.sage")

        self.assertEqual(
            command,
            [
                "wsl",
                "-d",
                "Debian",
                "--",
                "sage",
                "/mnt/c/work/validator.sage",
            ],
        )

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which")
    @patch("core.engine_router.subprocess.run")
    def test_configured_wsl_lean_project_is_detected(
        self,
        run,
        which,
        _is_windows,
    ):
        which.side_effect = self._which
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        env = {
            "ASTRA_WSL_DISTRO": "Debian",
            "ASTRA_LOCAL_LEAN4_WSL_ROOT": "/opt/mathlib4-v4.30.0",
            "ASTRA_LOCAL_LEAN4_WSL_LAKE_BIN": "/home/user/.elan/bin/lake",
        }
        with patch.dict(os.environ, env, clear=False):
            location = _configured_wsl_lean4()

        self.assertEqual(
            location,
            (
                "wsl -d Debian -- /home/user/.elan/bin/lake "
                "@ /opt/mathlib4-v4.30.0"
            ),
        )


    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=None)
    def test_wsl_state_absent_when_wsl_not_on_path(self, _which, _is_windows):
        state = wsl_probe_state()
        self.assertEqual(state["state"], "absent")

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=r"C:\Windows\wsl.exe")
    @patch("core.engine_router.subprocess.run")
    def test_wsl_state_denied_on_access_denied(self, run, _which, _is_windows):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Wsl/Service/E_ACCESSDENIED",
        )
        with patch.dict(os.environ, {"ASTRA_WSL_DISTRO": "Debian"}, clear=False):
            state = wsl_probe_state()
        self.assertEqual(state["state"], "denied")
        self.assertIn("E_ACCESSDENIED", state["detail"])

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=r"C:\Windows\wsl.exe")
    @patch("core.engine_router.subprocess.run")
    def test_wsl_state_denied_when_the_launch_raises_access_denied(
        self, run, _which, _is_windows
    ):
        err = OSError("Access is denied")
        err.winerror = 5
        run.side_effect = err
        state = wsl_probe_state()
        self.assertEqual(state["state"], "denied")

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=r"C:\Windows\wsl.exe")
    @patch("core.engine_router.subprocess.run")
    def test_wsl_state_error_not_denied_on_a_cold_boot_timeout(
        self, run, _which, _is_windows
    ):
        # A slow VM boot must NOT read as a restricted-token denial.
        run.side_effect = subprocess.TimeoutExpired(cmd="wsl", timeout=15)
        state = wsl_probe_state()
        self.assertEqual(state["state"], "error")

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=r"C:\Windows\wsl.exe")
    @patch("core.engine_router.subprocess.run")
    def test_wsl_state_denied_survives_utf16_null_interleaved_stderr(
        self, run, _which, _is_windows
    ):
        # wsl.exe UTF-16LE stderr mis-decoded leaves NULs between chars.
        garbled = "".join(ch + "\x00" for ch in "Wsl/Service/E_ACCESSDENIED")
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=garbled,
        )
        state = wsl_probe_state()
        self.assertEqual(state["state"], "denied")

    @patch("core.engine_router._is_windows", return_value=True)
    @patch("core.engine_router.shutil.which", return_value=r"C:\Windows\wsl.exe")
    @patch("core.engine_router.subprocess.run")
    def test_wsl_state_ok_when_reachable(self, run, _which, _is_windows):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch.dict(os.environ, {"ASTRA_WSL_DISTRO": "Debian"}, clear=False):
            state = wsl_probe_state()
        self.assertEqual(state["state"], "ok")


if __name__ == "__main__":
    unittest.main()
