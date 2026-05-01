#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.astra-wsl-venv"

echo "========================================="
echo "    ASTRA WSL bootstrap"
echo "========================================="

if ! command -v sudo >/dev/null 2>&1; then
  echo "ERROR: sudo is required inside WSL." >&2
  exit 1
fi

echo
echo "[1/5] Updating apt metadata"
sudo apt-get update

echo
echo "[2/5] Installing system packages"
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  gfortran \
  pkg-config \
  sagemath \
  maxima

echo
echo "[3/5] Installing Cadabra if available"
if apt-cache show cadabra2 >/dev/null 2>&1; then
  sudo apt-get install -y cadabra2
else
  echo "WARN: cadabra2 is not available in this Ubuntu apt repository."
  echo "      ASTRA will still install; Cadabra checks will show as optional WARN."
fi

echo
echo "[4/5] Creating Python virtual environment"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip wheel setuptools

echo
echo "[5/5] Installing Python requirements"
python -m pip install -r "$PROJECT_ROOT/requirements.txt"

echo
echo "Installed engine versions:"
python --version
sage --version || true
maxima --version || true
cadabra2 --version || true

echo
echo "ASTRA WSL bootstrap complete."
