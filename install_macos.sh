#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is intended for macOS." >&2
  exit 2
fi

PYTHON_BIN="${ASTRA_INSTALL_PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 is missing. Install Python 3.12 with Homebrew or python.org." >&2
  exit 2
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "ASTRA requires Python 3.10 or newer; Python 3.12 is recommended." >&2
  exit 2
}

echo "[1/5] Creating venv"
"$PYTHON_BIN" -m venv venv

echo "[2/5] Installing ASTRA, validation, MCP, and test dependencies"
venv/bin/python -m pip install --upgrade pip setuptools wheel
venv/bin/python -m pip install -r requirements-macos.txt

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
