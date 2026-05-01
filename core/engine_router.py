from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid


ENGINE_MARKER = re.compile(r"^\s*#\s*ASTRA_ENGINE:\s*(python|sage|maxima|cadabra)\s*$", re.I | re.M)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _win_to_wsl_path(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        return f"/mnt/{normalized[0].lower()}/{normalized[2:].lstrip('/')}"
    return normalized


def _wsl_which(command: str) -> bool:
    if not _is_windows() or shutil.which("wsl") is None:
        return False
    try:
        result = subprocess.run(["wsl", "which", command], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _native_or_wsl(command: str) -> str | None:
    native = shutil.which(command)
    if native:
        return native
    if _wsl_which(command):
        return f"wsl {command}"
    return None


def available_cas() -> dict[str, str | None]:
    return {
        "sage": _native_or_wsl("sage"),
        "maxima": _native_or_wsl("maxima"),
        "cadabra": _native_or_wsl("cadabra2"),
    }


def detect_engine(code: str) -> str:
    marker = ENGINE_MARKER.search(code)
    if marker:
        return marker.group(1).lower()

    if re.search(r"^\s*(from\s+sage|import\s+sage)", code, re.M):
        return "sage"
    if any(token in code for token in ("PolynomialRing(", "Manifold(", "RiemannianManifold(", "GF(", "ZZ[", "QQ[")):
        return "sage"
    if "/* maxima */" in code.lower() or re.search(r"^\s*(load|depends|gradef|ode2|ratsimp)\s*\(", code, re.M):
        return "maxima"
    if "/* cadabra */" in code.lower() or re.search(r"::\s*(Indices|Metric|AntiSymmetric|Symmetric|Derivative|Depends)", code):
        return "cadabra"
    return "python"


def _strip_engine_marker(code: str) -> str:
    return ENGINE_MARKER.sub("", code).lstrip()


def _run(cmd: list[str], timeout: int) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"TimeoutError: Execution exceeded {timeout}s.", "exit_code": 124}
    except Exception as exc:
        return {"stdout": "", "stderr": f"SystemError: {exc}", "exit_code": -1}


def _command_for(engine: str, filepath: str) -> list[str] | None:
    native = shutil.which("cadabra2" if engine == "cadabra" else engine)
    command = "cadabra2" if engine == "cadabra" else engine
    if native:
        if engine == "maxima":
            return [native, "--very-quiet", f"--batch={filepath}"]
        return [native, filepath]

    if _is_windows() and _wsl_which(command):
        wsl_path = _win_to_wsl_path(filepath)
        if engine == "maxima":
            return ["wsl", "maxima", "--very-quiet", f"--batch={wsl_path}"]
        return ["wsl", command, wsl_path]

    return None


def execute_external_cas(code: str, engine: str, workspace_dir: str, timeout: int) -> dict:
    extensions = {"sage": ".sage", "maxima": ".mac", "cadabra": ".cdb"}
    os.makedirs(workspace_dir, exist_ok=True)
    filepath = os.path.join(workspace_dir, f"astra_{engine}_{uuid.uuid4().hex[:8]}{extensions[engine]}")
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(_strip_engine_marker(code))
        if engine == "maxima" and not code.rstrip().endswith("quit();"):
            handle.write("\nquit();\n")

    cmd = _command_for(engine, filepath)
    if cmd is None:
        return {
            "stdout": "",
            "stderr": f"{engine} is not available. Install it natively or in WSL and rerun the ASTRA wizard.",
            "exit_code": -2,
            "engine": engine,
        }

    result = _run(cmd, timeout)
    result["engine"] = engine
    return result
