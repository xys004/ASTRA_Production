#!/usr/bin/env bash
set -euo pipefail

WORKER_DIR="${ASTRA_WORKER_DIR:-$HOME/astra-worker}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

sudo apt-get update
sudo apt-get install -y \
  curl git openssh-server build-essential gfortran pkg-config \
  python3 python3-venv python3-pip \
  libopenblas-dev liblapack-dev \
  maxima

sudo systemctl enable --now ssh

mkdir -p "$WORKER_DIR/workspace"
"$PYTHON_BIN" -m venv "$WORKER_DIR/venv"
source "$WORKER_DIR/venv/bin/activate"
python -m pip install --upgrade pip setuptools wheel

if [[ -f "$WORKER_DIR/requirements.txt" ]]; then
  python -m pip install -r "$WORKER_DIR/requirements.txt"
else
  python -m pip install \
    sympy z3-solver qutip numpy scipy mpmath einsteinpy fluids pint \
    numba matplotlib networkx PyYAML
fi

cat <<EOF
ASTRA remote worker is ready.

Worker dir: $WORKER_DIR
Python:     $WORKER_DIR/venv/bin/python
SSH:        $(systemctl is-active ssh)

Optional heavy CAS packages:
  sudo apt-get install -y sagemath cadabra2
EOF
