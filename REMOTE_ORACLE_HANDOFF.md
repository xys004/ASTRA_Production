# ASTRA Remote Oracle Handoff

Date: 2026-06-17

Canonical machine guide for agents:

`C:\Users\Nelson\REMOTE_CLUSTER_GUIDE.md`

## Current State

ASTRA_Production is configured to keep the Flask/Web UI local on Windows while
sending Phase 4 validation scripts to a stronger Ubuntu machine over
Tailscale + SSH.

Local project:

`C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production`

Remote worker:

`astrum@100.66.143.117`

Remote machine observed during setup:

- Hostname: `astrum-X870E-AORUS-ELITE-WIFI7-ICE`
- OS: Ubuntu 26.04 LTS
- CPU visible to shell: 32 logical CPUs (AMD Ryzen 9 9950X3D, 16 cores / 32 threads)
- RAM visible to shell: 29 GiB
- Worker root: `~/astra-worker`
- Worker Python: `~/astra-worker/venv/bin/python`
- Worker script: `~/astra-worker/astra_remote_worker.py`
- Worker temp workspace: `~/astra-worker/workspace`
- GPU: NVIDIA RTX 3080, usable from the worker venv through CuPy, PyTorch,
  and JAX CUDA packages.

## Local ASTRA Configuration

`.env` has been updated with:

```env
ASTRA_ORACLE_MODE=remote
ASTRA_ORACLE_TIMEOUT=600
ASTRA_REMOTE_HOST=astrum@100.66.143.117
ASTRA_REMOTE_PYTHON=~/astra-worker/venv/bin/python
ASTRA_REMOTE_WORKER=~/astra-worker/astra_remote_worker.py
ASTRA_REMOTE_WORKDIR=~/astra-worker/workspace
ASTRA_REMOTE_CONNECT_TIMEOUT=15
ASTRA_REMOTE_SSH_OPTIONS=-i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p"
```

Do not print `.env`: it may contain LLM API keys.

## SSH/Tailscale

The server is reachable through Tailscale. Standard direct port 22 was not
reachable initially, but SSH through Tailscale proxy works:

```powershell
ssh -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "hostname && whoami"
```

The public key `C:\Users\Nelson\.ssh\google_compute_engine.pub` is installed in
`/home/astrum/.ssh/authorized_keys`.

The private key ACL was restricted so Windows OpenSSH accepts it:

- `NELSON\Nelson:F`
- `NT AUTHORITY\SYSTEM:F`
- `BUILTIN\Administrators:F`

## Installed Remote Engines

Python scientific stack in `~/astra-worker/venv`:

- `sympy`
- `z3-solver`
- `numpy`
- `scipy`
- `mpmath`
- `matplotlib`
- `networkx`
- `fluids`
- `pint`
- `qutip`
- `einsteinpy`
- `numba`
- `PyYAML`
- `cupy-cuda12x` `14.1.1`
- `torch` `2.11.0+cu128`
- `jax` `0.10.2` with CUDA 12 plugin

External CAS:

- Maxima from Ubuntu packages
- SageMath `10.7` from conda-forge:
  `~/miniforge3/envs/sage/bin/sage`
- Cadabra `2.5.14` from official AppImage release:
  `~/bin/cadabra2`

Cadabra note: the AppImage default entrypoint starts GTK and fails headless.
The working setup extracts the AppImage and uses a wrapper around
`cadabra2-cli` with the AppImage loader and library path.

## Code Changes

Important local files:

- `core/executor.py`: dispatches to remote execution when
  `ASTRA_ORACLE_MODE=remote`.
- `core/remote_executor.py`: local SSH client bridge that sends JSON payloads.
- `remote/astra_remote_worker.py`: remote Linux worker that detects Python,
  Sage, Maxima, and Cadabra scripts and returns JSON results.
- `remote/bootstrap_ubuntu_worker.sh`: base Ubuntu package bootstrap.
- `remote/install_worker_python.sh`: worker venv scientific Python setup.
- `remote/install_gpu_stack.sh`: optional/reproducible CuPy, PyTorch CUDA,
  and JAX CUDA setup for the worker venv.
- `remote/install_sage_cadabra.sh`: SageMath + Cadabra installation.
- `remote/cadabra2_appimage_cli_wrapper.sh`: headless Cadabra CLI wrapper.
- `remote/check_remote_oracle.ps1`: end-to-end validation script.

## Verification

Run from the local project root:

```powershell
.\remote\check_remote_oracle.ps1
```

Expected result: all engines return `exit_code=0`.

Manual smoke tests that passed during setup:

- Python: `print(123)` returned `123`
- SymPy/SciPy: integral and numerical quadrature returned expected values
- Maxima: `expand((x+1)^3)` returned expanded polynomial
- Sage: `factor(x^2 - 1)` returned `(x + 1)*(x - 1)`
- Cadabra: simple indexed expression returned `A_{a} B_{b}`
- GPU: CuPy, PyTorch, and JAX each completed a 1024x1024 GPU matrix
  multiply on the RTX 3080.

## Reinstall / Repair Commands

Copy scripts:

```powershell
scp -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" .\remote\astra_remote_worker.py .\remote\install_worker_python.sh .\remote\install_sage_cadabra.sh astrum@100.66.143.117:~/astra-worker/
```

Reinstall Python worker packages:

```powershell
ssh -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "chmod +x ~/astra-worker/install_worker_python.sh && ~/astra-worker/install_worker_python.sh"
```

Reinstall Sage/Cadabra:

```powershell
ssh -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "chmod +x ~/astra-worker/install_sage_cadabra.sh && ~/astra-worker/install_sage_cadabra.sh"
```

Reinstall GPU stack:

```powershell
scp -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" .\remote\install_gpu_stack.sh astrum@100.66.143.117:~/astra-worker/
ssh -i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "chmod +x ~/astra-worker/install_gpu_stack.sh && ~/astra-worker/install_gpu_stack.sh"
```

## Git State At Handoff

The repo had one pre-existing untracked file before this work:

- `diagnostic_plot.png`

Do not assume it belongs to the remote oracle change.
