# ASTRA Remote Oracle

Run ASTRA locally while sending Phase 4 validation scripts to a stronger Linux
machine over Tailscale + SSH.

For a cold-start agent or model, read the global machine guide first:

`C:\Users\Nelson\REMOTE_CLUSTER_GUIDE.md`

## 1. Bootstrap the Ubuntu machine

Use the desktop only once if SSH is not available yet.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo apt-get update
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
tailscale ip
```

After `sudo tailscale up`, open the printed login URL from your Windows machine
and approve the Ubuntu machine in your tailnet.

## 2. Deploy the ASTRA worker from Windows

From this project root:

```powershell
.\remote\deploy_worker.ps1 -Remote astrum@100.66.143.117
```

Replace `astrum` if the Ubuntu username changes. The deploy script copies the worker,
copies `requirements.txt`, creates `~/astra-worker/venv`, installs Python
packages, and enables SSH.

## 3. Enable remote validation in `.env`

```env
ASTRA_ORACLE_MODE=remote
ASTRA_ORACLE_TIMEOUT=600
ASTRA_REMOTE_HOST=astrum@100.66.143.117
ASTRA_REMOTE_PYTHON=~/astra-worker/venv/bin/python
ASTRA_REMOTE_WORKER=~/astra-worker/astra_remote_worker.py
ASTRA_REMOTE_WORKDIR=~/astra-worker/workspace
ASTRA_REMOTE_SSH_OPTIONS=-i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p"
```

Restart ASTRA after changing `.env`.

## 4. SageMath and Cadabra

The base bootstrap installs Maxima. SageMath and Cadabra are heavier, so install
them with the dedicated script:

```powershell
scp -i $env:USERPROFILE\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" .\remote\install_sage_cadabra.sh astrum@100.66.143.117:~/astra-worker/
ssh -i $env:USERPROFILE\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "chmod +x ~/astra-worker/install_sage_cadabra.sh && ~/astra-worker/install_sage_cadabra.sh"
```

This installs SageMath under `~/miniforge3/envs/sage/bin/sage` and Cadabra's
headless CLI wrapper at `~/bin/cadabra2`.

## 5. GPU stack

The remote worker venv has been validated with:

- CuPy `14.1.1`
- PyTorch `2.11.0+cu128`
- JAX `0.10.2` with CUDA 12 plugin

To reinstall or repair it:

```powershell
scp -i $env:USERPROFILE\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" .\remote\install_gpu_stack.sh astrum@100.66.143.117:~/astra-worker/
ssh -i $env:USERPROFILE\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "chmod +x ~/astra-worker/install_gpu_stack.sh && ~/astra-worker/install_gpu_stack.sh"
```

## 6. Smoke tests

SSH should work without the desktop:

```powershell
ssh -i $env:USERPROFILE\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p" astrum@100.66.143.117 "hostname && nproc && free -h"
```

ASTRA preflight should report `ASTRA_ORACLE_OK` through the remote worker when
remote mode is enabled.
