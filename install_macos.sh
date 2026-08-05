#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is intended for macOS." >&2
  exit 2
fi

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' \
    >/dev/null 2>&1
}

select_python() {
  local candidate

  if [ -n "${ASTRA_INSTALL_PYTHON:-}" ]; then
    candidate="$ASTRA_INSTALL_PYTHON"
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      command -v "$candidate"
      return 0
    fi
    echo "ASTRA_INSTALL_PYTHON does not name a usable Python 3.10-3.12 interpreter: $candidate" >&2
    return 1
  fi

  # A Mac may have several Python installations on PATH. Prefer the known
  # compatible 3.12 line instead of assuming `python3` is the newest one.
  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(select_python)"; then
  echo "ASTRA requires Python 3.10-3.12; Python 3.12 is recommended." >&2
  echo "Install it with: brew install python@3.12" >&2
  exit 2
fi

# Resolve symlinks through Python itself and compare both version and CPU
# architecture. Reusing a venv created by another interpreter is unsafe.
PYTHON_BIN="$("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
PYTHON_ID="$("$PYTHON_BIN" -c 'import platform, sys; print(f"{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}")')"
PYTHON_DESCRIPTION="$("$PYTHON_BIN" -c 'import platform, sys; print(f"{sys.executable} (Python {platform.python_version()}, {platform.machine()})")')"
echo "Selected interpreter: $PYTHON_DESCRIPTION"

echo "[1/5] Preparing venv"
if [ -e venv ]; then
  VENV_ID=""
  if [ -x venv/bin/python ]; then
    VENV_ID="$(venv/bin/python -c 'import platform, sys; print(f"{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}")' 2>/dev/null || true)"
  fi

  if [ "$VENV_ID" != "$PYTHON_ID" ]; then
    VENV_BACKUP="venv.backup.$(date +%Y%m%d-%H%M%S).$$"
    mv venv "$VENV_BACKUP"
    echo "Existing incompatible venv preserved as $VENV_BACKUP"
    "$PYTHON_BIN" -m venv venv
  else
    echo "Reusing compatible venv ($VENV_ID)."
  fi
else
  "$PYTHON_BIN" -m venv venv
fi

echo "[2/5] Installing ASTRA, validation, MCP, and test dependencies"
venv/bin/python -m pip install --upgrade pip setuptools wheel
# Numba accelerates EinsteinPy but must not be compiled locally during normal
# onboarding. The macOS requirements pin a wheel-backed Numba/llvmlite pair.
venv/bin/python -m pip install --only-binary=llvmlite,numba -r requirements-macos.txt

echo "[3/5] Creating the non-secret macOS configuration"
if [ ! -f .env ]; then
  cp config/macos.env.example .env
  echo "Created .env. Configure the ASTRUM host, macOS username, and SSH key path."
else
  echo "Existing .env preserved."
fi

echo "[4/5] Registering ASTRA MCP for this Antigravity workspace"
venv/bin/python scripts/configure_antigravity_mcp.py

echo "[5/5] Verifying the architecture configuration"
venv/bin/python scripts/audit_architecture.py --no-binary-check
chmod +x launch_astra.sh remote/check_remote_oracle.sh

echo
echo "ASTRA core installation is complete."
echo "Next: authenticate codex, claude, and agy; configure ASTRUM in .env; then run:"
echo "  venv/bin/python scripts/astra_doctor.py --remote"
echo "  remote/check_remote_oracle.sh"
echo "Refresh MCP Servers in Antigravity before asking it to call astra_status."
