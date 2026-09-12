#!/usr/bin/env bash
# install_company_pkgs.sh — instala los paquetes de cálculo propios en el clúster.
#
# Se ejecuta EN Astrum, tras haber subido ~/pkgs_src.tar.gz.
#
# Env propio `pkgs`: no se toca ~/astra-worker/venv (oráculo de ASTRA, py3.14 con
# pines delicados) ni los envs sci/sage/cadabra. Estos paquetes traen sus propias
# restricciones de versión y merecen su espacio.
#
# Dos clases de paquete:
#   - con pyproject/setup.py -> `pip install -e` (grthermo, protoespacio,
#     metric-engine, warp_nn, pyWarpFactory, QuantumTransportEOM)
#   - sin empaquetar pero importables -> se añaden por .pth (TELAR expone `telar/`,
#     natario y mobius son scripts sueltos que importan grthermo)
set -uo pipefail

E=~/miniforge3/envs/pkgs
M=~/miniforge3/bin/mamba
SRC=~/pkgs

echo "=== [1/5] env pkgs (python 3.12) ==="
[ -d "$E" ] || $M create -y -q -p "$E" python=3.12 pip 2>&1 | tail -2

echo "=== [2/5] dependencias comunes ==="
"$E/bin/pip" install -q --no-input \
  "numpy>=2.0" "scipy>=1.12" "sympy>=1.13" "matplotlib>=3.8" "pandas>=2.2" \
  "networkx>=3" "pyyaml>=6" "z3-solver>=4.13" "threadpoolctl>=3" \
  pytest pytest-timeout 2>&1 | tail -2

echo "=== [3/5] jax con CUDA (warp_nn es PINN/GPU) ==="
"$E/bin/pip" install -q --no-input "jax[cuda12]" optax jaxopt 2>&1 | tail -2 \
  || { echo "  jax[cuda12] falló -> cayendo a jax CPU"; \
       "$E/bin/pip" install -q --no-input jax optax jaxopt 2>&1 | tail -1; }

echo "=== [4/5] instalando los paquetes propios ==="
declare -A EDITABLE=(
  [gr/grthermo]=grthermo
  [physics/protoespacio]=protoespacio
  [metric-engine]=metric-engine
  [warp/warp_nn]=warp_nn
  [warp/pyWarpFactory_push]=pyWarpFactory
  [quantum/QuantumTransportEOM]=QuantumTransportEOM
)
for path in "${!EDITABLE[@]}"; do
  name="${EDITABLE[$path]}"
  if [ -d "$SRC/$path" ]; then
    printf "  %-24s " "$name"
    if "$E/bin/pip" install -q --no-input --no-deps -e "$SRC/$path" 2>/dev/null; then
      echo "OK"
    else
      echo "FALLO (ver log)"
      "$E/bin/pip" install --no-input --no-deps -e "$SRC/$path" 2>&1 | tail -3 | sed 's/^/      /'
    fi
  fi
done

echo "  --- no empaquetados, vía .pth ---"
SITE=$("$E/bin/python" -c "import site; print(site.getsitepackages()[0])")
: > "$SITE/astrum_company_pkgs.pth"
for path in warp/TELAR warp/natario_energy_bound physics/rectification_design_map \
            quantum/mobius_cylinder_rsoc; do
  [ -d "$SRC/$path" ] && { echo "$SRC/$path" >> "$SITE/astrum_company_pkgs.pth"; \
                           printf "  %-24s en PYTHONPATH\n" "$(basename $path)"; }
done

echo "=== [5/5] verificación por IMPORT ==="
"$E/bin/python" - <<'PY'
import importlib
mods = ["grthermo", "telar", "numpy", "scipy", "sympy", "z3", "jax"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", "")
        print(f"  {m:22} OK {v}")
    except Exception as e:
        print(f"  {m:22} FALLA  {type(e).__name__}: {str(e)[:60]}")
try:
    import jax
    print(f"  jax devices            {jax.devices()}")
except Exception as e:
    print(f"  jax devices            n/a ({type(e).__name__})")
PY
echo "=== PKGS DONE ==="
