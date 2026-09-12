#!/usr/bin/env bash
set -euo pipefail

cd "${ASTRA_WORKER_DIR:-$HOME/astra-worker}"

if [[ ! -x venv/bin/python ]]; then
  echo "Missing worker venv at $(pwd)/venv. Run install_worker_python.sh first." >&2
  exit 1
fi

source venv/bin/activate

python -m pip install --upgrade pip wheel

# CuPy uses the NVIDIA CUDA runtime libraries installed by the following
# PyTorch/JAX CUDA packages. Install all three before running the smoke test.
python -m pip install --upgrade cupy-cuda12x
python -m pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu128
python -m pip install --upgrade "jax[cuda12]"

python - <<'PY'
import cupy as cp
import jax
import jax.numpy as jnp
import torch

print("cupy", cp.__version__, "devices", cp.cuda.runtime.getDeviceCount())
x = cp.ones((1024, 1024), dtype=cp.float32)
print("cupy_sum", float((x @ x)[0, 0]))

print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.version.cuda)
print("torch_device", torch.cuda.get_device_name(0))
a = torch.ones((1024, 1024), device="cuda")
print("torch_sum", float((a @ a)[0, 0]))

print("jax", jax.__version__, "devices", jax.devices())
b = jnp.ones((1024, 1024), dtype=jnp.float32)
print("jax_sum", float((b @ b)[0, 0]))
PY
