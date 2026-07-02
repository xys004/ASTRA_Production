#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ENGINE_MARKER = re.compile(r"^\s*#\s*ASTRA_ENGINE:\s*(python|sympy|sage|maxima|cadabra)\s*$", re.I | re.M)


def detect_engine(code: str) -> str:
    marker = ENGINE_MARKER.search(code)
    if marker:
        engine = marker.group(1).lower()
        return "python" if engine == "sympy" else engine
    if re.search(r"^\s*(from\s+sage|import\s+sage)", code, re.M):
        return "sage"
    if any(token in code for token in ("PolynomialRing(", "Manifold(", "RiemannianManifold(", "GF(", "ZZ[", "QQ[")):
        return "sage"
    if "/* maxima */" in code.lower() or re.search(r"^\s*(load|depends|gradef|ode2|ratsimp)\s*\(", code, re.M):
        return "maxima"
    if "/* cadabra */" in code.lower() or re.search(r"::\s*(Indices|Metric|AntiSymmetric|Symmetric|Derivative|Depends)", code):
        return "cadabra"
    return "python"


def strip_engine_marker(code: str) -> str:
    return ENGINE_MARKER.sub("", code).lstrip()


def command_for(engine: str, filepath: str) -> list[str] | None:
    if engine == "python":
        return [sys.executable, filepath]

    command = "cadabra2" if engine == "cadabra" else engine
    env_var = {"sage": "ASTRA_SAGE_BIN", "maxima": "ASTRA_MAXIMA_BIN", "cadabra": "ASTRA_CADABRA_BIN"}[engine]
    candidates = [
        os.environ.get(env_var),
        shutil.which(command),
    ]
    if engine == "sage":
        candidates.extend([
            "~/miniforge3/envs/sage/bin/sage",
            "~/mambaforge/envs/sage/bin/sage",
            "~/micromamba/envs/sage/bin/sage",
            "~/.local/bin/sage",
        ])
    elif engine == "cadabra":
        candidates.extend([
            "~/bin/cadabra2",
            "~/Applications/cadabra2",
            "~/.local/bin/cadabra2",
        ])

    binary = None
    for candidate in candidates:
        if not candidate:
            continue
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            binary = expanded
            break

    if not binary:
        return None
    if engine == "maxima":
        return [binary, "--very-quiet", f"--batch={filepath}"]
    if engine in {"sage", "cadabra"}:
        return [binary, filepath]


def run_code(code: str, workdir: str, timeout: int) -> dict:
    start = time.monotonic()
    os.makedirs(os.path.expanduser(workdir), exist_ok=True)
    workdir = os.path.abspath(os.path.expanduser(workdir))
    engine = detect_engine(code)
    suffix = {"python": ".py", "sage": ".sage", "maxima": ".mac", "cadabra": ".cdb"}[engine]
    filepath = os.path.join(workdir, f"astra_remote_{engine}_{uuid.uuid4().hex[:8]}{suffix}")

    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(strip_engine_marker(code))
        if engine == "maxima" and not code.rstrip().endswith("quit();"):
            handle.write("\nquit();\n")

    cmd = command_for(engine, filepath)
    if cmd is None:
        return {
            "stdout": "",
            "stderr": f"{engine} is not available on the remote worker.",
            "exit_code": -2,
            "engine": engine,
            "duration_s": round(time.monotonic() - start, 3),
        }

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=workdir)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "engine": engine,
            "duration_s": round(time.monotonic() - start, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"TimeoutError: Execution exceeded {timeout}s.",
            "exit_code": 124,
            "engine": engine,
            "duration_s": round(time.monotonic() - start, 3),
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": f"SystemError: {exc}",
            "exit_code": -1,
            "engine": engine,
            "duration_s": round(time.monotonic() - start, 3),
        }
    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        code = payload["code"]
        timeout = int(payload.get("timeout", 60))
        workdir = payload.get("workdir", "~/astra-worker/workspace")
        response = run_code(code, workdir, timeout)
    except Exception as exc:
        response = {
            "stdout": "",
            "stderr": f"RemoteWorkerError: {exc}",
            "exit_code": -100,
            "engine": "remote",
        }
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
