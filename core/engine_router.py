from __future__ import annotations

import errno
import ntpath
import os
import re
import shutil
import subprocess
import sys
import uuid


ENGINE_MARKER = re.compile(
    r"^\s*#\s*ASTRA_ENGINE:\s*"
    r"(python|sympy|sage|maxima|cadabra|lean|lean4|sci|pkgs)\s*$",
    re.I | re.M,
)

# Consola oculta para hijos de consola (wsl/ssh/engines) cuando el padre no
# tiene consola: evita ventanas visibles vacias por cada ejecucion.
# (os.name directo: _is_windows() se define mas abajo y esto corre al importar.)
_NT_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _is_windows() -> bool:
    return sys.platform == "win32"


def _win_to_wsl_path(path: str) -> str:
    # Use Windows path semantics even when the test suite is running on macOS
    # or Linux. os.path follows the host OS and would otherwise turn
    # C:\\work\\file into <cwd>/C:/work/file on POSIX.
    normalized = ntpath.abspath(path).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        return f"/mnt/{normalized[0].lower()}/{normalized[2:].lstrip('/')}"
    return normalized


def _wsl_prefix() -> list[str]:
    distro = os.environ.get("ASTRA_WSL_DISTRO", "").strip().strip("'\"")
    prefix = ["wsl"]
    if distro:
        prefix.extend(["-d", distro])
    prefix.append("--")
    return prefix


def _wsl_which(command: str) -> bool:
    if not _is_windows() or shutil.which("wsl") is None:
        return False
    try:
        result = subprocess.run(
            [*_wsl_prefix(), "which", command],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NT_NO_WINDOW,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _wsl_test(flag: str, path: str) -> bool:
    if not _is_windows() or shutil.which("wsl") is None or not path:
        return False
    try:
        result = subprocess.run(
            [*_wsl_prefix(), "test", flag, path],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NT_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def _configured_wsl_lean4() -> str | None:
    root = os.environ.get("ASTRA_LOCAL_LEAN4_WSL_ROOT", "").strip().strip("'\"")
    lake = (
        os.environ.get("ASTRA_LOCAL_LEAN4_WSL_LAKE_BIN", "")
        .strip()
        .strip("'\"")
    )
    if _wsl_test("-d", root) and _wsl_test("-x", lake):
        return " ".join([*_wsl_prefix(), lake, "@", root])
    return None


def _native_or_wsl(command: str) -> str | None:
    native = shutil.which(command)
    if native:
        return native
    if _wsl_which(command):
        return " ".join([*_wsl_prefix(), command])
    return None


def wsl_probe_state(distro: str | None = None) -> dict:
    """Tell a RESTRICTED-CONTEXT WSL denial apart from WSL being absent.

    ``available_cas`` routes sage/maxima/cadabra/lean4 through ``wsl -d
    Debian`` and returns None when the probe fails -- but None conflates two
    very different things: the engine is genuinely not installed, versus this
    process cannot reach WSL at all. The Codex sandbox is the second case
    (``wsl`` returns ``Wsl/Service/E_ACCESSDENIED``): the engines are installed
    and fine, the restricted token just cannot talk to the VM. Reporting that
    as a missing engine sends the reader off to reinstall something that works.

    Returns ``{"state": "ok"|"denied"|"absent"|"error", "detail": str}``.
    """
    if not _is_windows():
        return {"state": "ok", "detail": "not Windows; native engines used"}
    if shutil.which("wsl") is None and shutil.which("wsl.exe") is None:
        return {"state": "absent", "detail": "wsl.exe not on PATH"}
    prefix = ["wsl"]
    d = (distro if distro is not None
         else os.environ.get("ASTRA_WSL_DISTRO", "")).strip().strip("'\"")
    if d:
        prefix.extend(["-d", d])
    prefix.append("--")
    try:
        result = subprocess.run(
            [*prefix, "true"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NT_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        # A cold WSL VM boot or a wedged distro is NOT a permission denial;
        # calling it "denied" would misdiagnose the very thing this probe exists
        # to separate. It is an unhealthy-but-present state.
        return {"state": "error", "detail": "wsl did not respond within 15s"}
    except FileNotFoundError:
        return {"state": "absent", "detail": "wsl.exe disappeared between checks"}
    except OSError as exc:
        access_denied = (
            getattr(exc, "winerror", None) == 5
            or getattr(exc, "errno", None) == errno.EACCES
        )
        return {
            "state": "denied" if access_denied else "error",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    if result.returncode == 0:
        return {"state": "ok", "detail": f"wsl -d {d or '(default)'} reachable"}
    # wsl.exe can emit UTF-16LE on stderr; with text=True a mismatched codec
    # leaves interleaved NULs (E\x00_\x00A...). Strip them before matching so a
    # real denial is not silently downgraded to "error".
    err = (result.stderr or result.stdout or "").replace("\x00", "").strip()
    low = err.lower()
    if ("e_accessdenied" in low or "access is denied" in low
            or "0x80070005" in low):
        return {"state": "denied", "detail": err[-200:] or "access denied"}
    return {"state": "error", "detail": err[-200:] or f"wsl exit {result.returncode}"}


def available_cas() -> dict[str, str | None]:
    return {
        "sage": _native_or_wsl("sage"),
        "maxima": _native_or_wsl("maxima"),
        "cadabra": _native_or_wsl("cadabra2"),
        "lean4": (
            _configured_wsl_lean4()
            or _native_or_wsl("lake")
            or _native_or_wsl("lean")
        ),
    }


def detect_engine(code: str) -> str:
    marker = ENGINE_MARKER.search(code)
    if marker:
        engine = marker.group(1).lower()
        if engine == "sympy":
            return "python"
        return "lean4" if engine == "lean" else engine

    if re.search(r"^\s*(from\s+sage|import\s+sage)", code, re.M):
        return "sage"
    if any(token in code for token in ("PolynomialRing(", "Manifold(", "RiemannianManifold(", "GF(", "ZZ[", "QQ[")):
        return "sage"
    if "/* maxima */" in code.lower() or re.search(r"^\s*(load|depends|gradef|ode2|ratsimp)\s*\(", code, re.M):
        return "maxima"
    if "/* cadabra */" in code.lower() or re.search(r"::\s*(Indices|Metric|AntiSymmetric|Symmetric|Derivative|Depends)", code):
        return "cadabra"
    if "import Mathlib" in code or re.search(r"^\s*(theorem|lemma|example)\s+.*:=", code, re.M):
        return "lean4"
    return "python"


def _strip_engine_marker(code: str) -> str:
    return ENGINE_MARKER.sub("", code).lstrip()


def _run(cmd: list[str], timeout: int) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                creationflags=_NT_NO_WINDOW)
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
            return [
                *_wsl_prefix(),
                "maxima",
                "--very-quiet",
                f"--batch={wsl_path}",
            ]
        return [*_wsl_prefix(), command, wsl_path]

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
            "stderr": (
                f"{engine} is not available. Install it natively; on Windows "
                "you may also configure WSL, or route validation through ASTRUM."
            ),
            "exit_code": -2,
            "engine": engine,
        }

    result = _run(cmd, timeout)
    result["engine"] = engine
    return result
