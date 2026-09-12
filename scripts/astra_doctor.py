"""Non-destructive installation audit for ASTRA workstations."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.architecture_contract import audit_production_architecture
from core.preflight import PROVIDERS, _cli_available, load_project_env
from core.remote_executor import execute_remote_code


REQUIRED_MODULES = (
    "sympy",
    "z3",
    "numpy",
    "scipy",
    "mpmath",
    "qutip",
    "einsteinpy",
    "fluids",
    "pint",
    "mcp",
)
REQUIRED_COMMANDS = ("git", "ssh", "codex", "claude", "agy")
OPTIONAL_COMMANDS = ("tailscale", "maxima", "sage", "cadabra2", "lake", "lean")


def item(name: str, ok: bool, detail: str, required: bool = True) -> dict:
    return {
        "name": name,
        "status": "PASS" if ok else "FAIL" if required else "OPTIONAL_MISSING",
        "required": required,
        "detail": detail,
    }


async def remote_probe() -> dict:
    code = (
        "import platform\n"
        "print('HOST', platform.node())\n"
        "print('VERDICT: PASS')\n"
    )
    return await execute_remote_code(code, timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Also connect to ASTRUM and run a harmless Python probe.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    load_project_env()

    checks = []
    py_ok = (3, 10) <= sys.version_info[:2] <= (3, 12)
    checks.append(item("python", py_ok, sys.version.split()[0]))
    system = platform.system()
    machine = platform.machine()
    checks.append(item("platform", system in {"Darwin", "Windows"}, f"{system} {machine}"))
    # One WSL reachability probe, reused below to tell "engine denied in this
    # restricted context" apart from "engine not installed". The Codex sandbox
    # returns Wsl/Service/E_ACCESSDENIED here while the engines are perfectly
    # fine from a normal shell (verified 2026-09-10).
    from core.engine_router import wsl_probe_state
    wsl = wsl_probe_state() if system == "Windows" else {"state": "ok", "detail": "n/a"}
    if system == "Windows":
        checks.append(
            item(
                "wsl_bridge",
                wsl["state"] == "ok",
                {
                    "ok": wsl["detail"],
                    "denied": "WSL DENIED in this context (restricted token, e.g. the "
                              "Codex sandbox); engines are NOT missing -- run ASTRA via "
                              "its MCP server or a normal shell. " + wsl["detail"],
                    "absent": "WSL not installed; local Sage/Maxima/Cadabra unavailable, "
                              "ASTRUM engine covers them. " + wsl["detail"],
                    "error": "WSL present but unhealthy: " + wsl["detail"],
                }[wsl["state"]],
                required=False,
            )
        )
    if system == "Darwin":
        checks.append(
            item(
                "apple_silicon",
                machine in {"arm64", "aarch64"},
                machine + " (required by the current Antigravity desktop app)",
                required=False,
            )
        )

    for module in REQUIRED_MODULES:
        available = importlib.util.find_spec(module) is not None
        checks.append(item(f"python:{module}", available, "importable" if available else "missing"))
    muse_trial = os.environ.get("ASTRA_ARCHITECTURE_PROFILE", "").lower() == "muse-trial"
    commands = REQUIRED_COMMANDS + (("muse",) if muse_trial else ())
    for command in commands:
        if command == "muse":
            available = _cli_available(PROVIDERS["muse_cli"])
            checks.append(
                item(
                    "cli:muse",
                    available,
                    "Debian/WSL Muse Code available"
                    if available
                    else "Muse Code unavailable in the configured WSL distribution",
                )
            )
            continue
        location = shutil.which(command)
        checks.append(item(f"cli:{command}", location is not None, location or "not on PATH"))
    cas = None
    for command in OPTIONAL_COMMANDS:
        if command in {"maxima", "sage", "cadabra2"}:
            # These live in WSL on this workstation; shutil.which is always None
            # for them on Windows and would misreport a healthy install. Route
            # through available_cas() and, when it is None, say WHY.
            if cas is None:
                from core.engine_router import available_cas
                cas = available_cas()
            route = cas.get({"cadabra2": "cadabra"}.get(command, command))
            if route:
                detail = route
            elif wsl["state"] == "denied":
                detail = "denied via WSL in this context (not missing); use MCP / a normal shell"
            elif wsl["state"] == "absent":
                detail = "not in WSL and WSL absent; ASTRUM engine covers it"
            else:
                detail = "not installed natively or in WSL; ASTRUM engine covers it"
            checks.append(item(f"optional:{command}", route is not None, detail, required=False))
            continue
        location = shutil.which(command)
        checks.append(
            item(
                f"optional:{command}",
                location is not None,
                location or "use the maintained ASTRUM engine",
                required=False,
            )
        )

    architecture = audit_production_architecture(check_binaries=True)
    arch_failures = architecture.get("required_failures", [])
    arch_detail = ", ".join(arch_failures) or "canonical production topology"
    if (architecture["status"] != "PASS" and wsl["state"] == "denied"
            and arch_failures
            and all(f.startswith("scientific_engine_") for f in arch_failures)):
        # The contract can't reach the engines from a restricted context, so it
        # fails closed -- correct as a gate, misleading as a diagnosis. Say so.
        arch_detail += (
            "  [these are WSL-routed engines and WSL is DENIED in this context; "
            "the engines are installed -- audit from a normal shell / via MCP]"
        )
    checks.append(
        item(
            "architecture_contract",
            architecture["status"] == "PASS",
            arch_detail,
        )
    )

    remote = None
    if args.remote:
        remote = asyncio.run(remote_probe())
        remote_ok = (
            int(remote.get("exit_code", -1)) == 0
            and "VERDICT: PASS" in str(remote.get("stdout", ""))
        )
        checks.append(
            item(
                "astrum",
                remote_ok,
                str(remote.get("stderr") or remote.get("stdout") or "no response")[-500:],
            )
        )

    required_failures = [c["name"] for c in checks if c["required"] and c["status"] != "PASS"]
    report = {
        "status": "PASS" if not required_failures else "FAIL",
        "checks": checks,
        "required_failures": required_failures,
        "remote": remote,
        "note": (
            "This doctor verifies executables and configuration without spending model quota. "
            "Authenticate codex, claude and agy interactively before the smoke cycle."
            + (" Muse Code is also required by the active Muse trial." if muse_trial else "")
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for check in checks:
            print(f"[{check['status']:<16}] {check['name']}: {check['detail']}")
        print(f"\nASTRA DOCTOR: {report['status']}")
        if required_failures:
            print("Required failures: " + ", ".join(required_failures))
        print(report["note"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
