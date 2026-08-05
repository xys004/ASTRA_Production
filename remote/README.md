# ASTRA Remote Oracle

ASTRA runs on a collaborator workstation and sends validation code to a managed
Linux worker through SSH, normally over a private Tailscale network.

Never commit the real host, username, private key, tailnet details, or `.env`.
Each collaborator must use an individually authorized SSH public key.

## Deploy the worker

From Windows PowerShell:

```powershell
.\remote\deploy_worker.ps1 -Remote user@tailscale-host
```

From macOS/Linux, copy the tracked worker and bootstrap scripts with the user's
normal `scp`/`ssh` configuration. The default worker directory is
`~/astra-worker`.

## Workstation configuration

```dotenv
ASTRA_ORACLE_MODE=remote
ASTRA_ORACLE_TIMEOUT=600
ASTRA_REMOTE_HOST=astrum
ASTRA_REMOTE_PYTHON=~/astra-worker/venv/bin/python
ASTRA_REMOTE_WORKER=~/astra-worker/astra_remote_worker.py
ASTRA_REMOTE_WORKDIR=~/astra-worker/workspace
ASTRA_REMOTE_ENGINE_RUNNER=~/astra-worker/astra_engine.sh
ASTRA_REMOTE_CONNECT_TIMEOUT=15
ASTRA_REMOTE_SSH_OPTIONS=
```

Here `astrum` is a machine-local alias in `~/.ssh/config`; it is not a public
hostname. A Tailscale proxy can be configured in that SSH alias:

```sshconfig
Host astrum
    HostName YOUR_TAILSCALE_HOST
    User YOUR_REMOTE_USER
    IdentityFile ~/.ssh/astra_astrum_ed25519
    IdentitiesOnly yes
    ProxyCommand tailscale nc %h %p
```

## Managed engines

The cluster registry is authoritative:

```bash
~/astra-worker/astra_engine.sh list
```

Engines live in separate managed environments and may not appear in the login
shell PATH. ASTRA exposes the same registry through the `astra_engines` MCP
tool. `# ASTRA_ENGINE: pkgs` selects company packages and
`# ASTRA_ENGINE: sci` selects the specialized scientific environment.

## Verification

Windows:

```powershell
.\remote\check_remote_oracle.ps1
```

macOS/Linux:

```bash
./remote/check_remote_oracle.sh
```

Both checks force remote mode and fail if `ASTRA_REMOTE_HOST` is not configured.
They cover Python, SymPy/SciPy, Maxima, SageMath, Cadabra, and the managed
company-package environment.
