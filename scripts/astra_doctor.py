"""Non-destructive installation audit for ASTRA workstations."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import platform
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.architecture_contract import audit_production_architecture
from core.preflight import load_project_env
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
    for command in REQUIRED_COMMANDS:
        location = shutil.which(command)
        checks.append(item(f"cli:{command}", location is not None, location or "not on PATH"))
    for command in OPTIONAL_COMMANDS:
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
    checks.append(
        item(
            "architecture_contract",
            architecture["status"] == "PASS",
            ", ".join(architecture.get("required_failures", [])) or "canonical production topology",
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
