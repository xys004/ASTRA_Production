#!/usr/bin/env bash
set -u

cd "${ASTRA_WORKER_DIR:-$HOME/astra-worker}"
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

groups=(
  "sympy z3-solver numpy scipy mpmath PyYAML"
  "matplotlib networkx fluids pint"
  "qutip"
  "einsteinpy numba"
)

for group in "${groups[@]}"; do
  echo "=== installing: $group ==="
  if ! python -m pip install $group; then
    echo "ASTRA_PIP_GROUP_FAILED: $group"
  fi
done

python - <<'PY'
import importlib

mods = [
    "sympy", "z3", "numpy", "scipy", "mpmath", "yaml",
    "matplotlib", "networkx", "fluids", "pint",
    "qutip", "einsteinpy", "numba",
]

for mod in mods:
    try:
        importlib.import_module(mod)
        print(f"OK {mod}")
    except Exception as exc:
        print(f"MISSING {mod}: {type(exc).__name__}: {exc}")
PY
