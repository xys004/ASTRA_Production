"""The doctor must tell a restricted-context WSL denial apart from a missing engine.

Sage, Maxima and Cadabra live in Debian WSL on this workstation. From a normal
shell they route and the doctor shows them PASS. From a restricted context (the
Codex sandbox, whose token cannot reach WSL) available_cas() returns None for
all of them and the architecture contract fails closed -- correct as a gate,
but it must NOT read as "the engines are not installed". These tests pin the two
renderings so a future refactor cannot quietly collapse them back together.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import astra_doctor  # noqa: E402


def _run_doctor():
    with patch.object(sys, "argv", ["astra_doctor.py", "--json"]):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            astra_doctor.main()
    report = json.loads(buffer.getvalue())
    return {check["name"]: check for check in report["checks"]}


class AstraDoctorWslAwarenessTests(unittest.TestCase):
    def test_denied_wsl_is_reported_as_a_context_not_a_missing_engine(self):
        denied = {"state": "denied", "detail": "Wsl/Service/E_ACCESSDENIED"}
        cas_none = {"sage": None, "maxima": None, "cadabra": None, "lean4": None}
        arch_fail = {
            "status": "FAIL",
            "required_failures": [
                "scientific_engine_sage",
                "scientific_engine_maxima",
                "scientific_engine_cadabra",
            ],
        }
        with patch("platform.system", return_value="Windows"), patch(
            "core.engine_router.wsl_probe_state", return_value=denied
        ), patch(
            "core.engine_router.available_cas", return_value=cas_none
        ), patch(
            "astra_doctor.audit_production_architecture", return_value=arch_fail
        ), patch("astra_doctor._cli_available", return_value=True):
            checks = _run_doctor()

        self.assertEqual(checks["wsl_bridge"]["status"], "OPTIONAL_MISSING")
        self.assertIn("DENIED in this context", checks["wsl_bridge"]["detail"])
        for engine in ("optional:sage", "optional:maxima", "optional:cadabra2"):
            self.assertIn("denied via WSL", checks[engine]["detail"])
            self.assertIn("not missing", checks[engine]["detail"])
        # The contract still fails closed, but the human-facing line says why.
        self.assertIn("WSL-routed engines", checks["architecture_contract"]["detail"])
        self.assertIn(
            "engines are installed", checks["architecture_contract"]["detail"]
        )

    def test_reachable_wsl_reports_the_routed_engines_as_present(self):
        ok = {"state": "ok", "detail": "wsl -d Debian reachable"}
        cas_ok = {
            "sage": "wsl -d Debian -- sage",
            "maxima": "wsl -d Debian -- maxima",
            "cadabra": "wsl -d Debian -- cadabra2",
            "lean4": None,
        }
        arch_pass = {"status": "PASS", "required_failures": []}
        with patch("platform.system", return_value="Windows"), patch(
            "core.engine_router.wsl_probe_state", return_value=ok
        ), patch(
            "core.engine_router.available_cas", return_value=cas_ok
        ), patch(
            "astra_doctor.audit_production_architecture", return_value=arch_pass
        ), patch("astra_doctor._cli_available", return_value=True):
            checks = _run_doctor()

        self.assertEqual(checks["wsl_bridge"]["status"], "PASS")
        for engine in ("optional:sage", "optional:maxima", "optional:cadabra2"):
            self.assertEqual(checks[engine]["status"], "PASS")
            self.assertIn("wsl -d Debian", checks[engine]["detail"])


if __name__ == "__main__":
    unittest.main()
