# ASTRA + ASTRUM on macOS

This is the supported onboarding path for a collaborator's Mac. The Mac runs
ASTRA, the three authenticated model CLIs, the MCP server, and the lightweight
validation stack. Specialized and heavy validation runs on the centrally
maintained ASTRUM worker through Tailscale and SSH.

No API keys, CLI login tokens, Tailscale state, or SSH private keys are shared.
Each collaborator authenticates their own subscriptions and receives an
individual ASTRUM SSH key authorization.

## 1. Supported layout

| Layer | Runs on the Mac | Runs on ASTRUM |
|---|---:|---:|
| Antigravity desktop agent and ASTRA MCP | Yes | No |
| Codex, Claude Code, and `agy` subscription CLIs | Yes | No |
| Python, SymPy, Z3, NumPy/SciPy, mpmath, Pint, QuTiP | Yes | Yes |
| SageMath, Maxima, Cadabra, pinned Lean 4 + Mathlib | Optional | Authoritative |
| GPU/scientific environments | No | Yes |
| Company packages such as GR_python and pyWarpFactory | Optional clone | Authoritative maintained copies |

Antigravity is the human-facing instructor and operator. It does not replace
the `agy` CLI: ASTRA itself invokes `agy` as its independent co-conjecture and
research-navigation model.

## 2. Mac prerequisites

The current Antigravity desktop app requires Apple Silicon and macOS 12 or
newer. Install Homebrew if it is not already present, then:

```bash
brew install git python@3.12 node maxima
```

Maxima is optional locally; the ASTRUM copy remains available. Install the
standalone Tailscale macOS client, sign in to the company's tailnet, and enable
its command-line integration so `tailscale` is on `PATH`.

Install the three model CLIs from their official distributions:

```bash
npm install -g @openai/codex
npm install -g @anthropic-ai/claude-code
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

If `agy` is not found after installation, add its directory to the shell path:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Authenticate each CLI interactively with the collaborator's own account:

```bash
codex login
claude
agy
```

Do not paste those login tokens into `.env`; ASTRA uses the CLIs' own secure
credential stores.

## 3. Clone and install ASTRA

```bash
mkdir -p ~/Dev
cd ~/Dev
git clone https://github.com/AstrumDrive/ASTRA.git
cd ASTRA
bash install_macos.sh
```

The installer creates `venv/`, installs the full Python validation stack and
MCP SDK, creates a non-secret `.env`, and writes a workspace-scoped
`.agents/mcp_config.json` for Antigravity. Existing `.env` and MCP configuration
are preserved. It looks for Python 3.12 before older versions and reports the
selected path, version, and architecture. If `venv/` belongs to another Python
version or architecture, it is preserved as `venv.backup.*` and replaced.
Numba and llvmlite are installed from binary wheels compatible with both Intel
and Apple Silicon Macs, so normal onboarding does not require CMake or LLVM.

To select Homebrew Python explicitly without hard-coding the Intel or Apple
Silicon Homebrew prefix:

```bash
ASTRA_INSTALL_PYTHON="$(command -v python3.12)" bash install_macos.sh
```

If `command -v python3.12` prints no path, run `brew install python@3.12` first
and open a new terminal.

## 4. Give this Mac individual ASTRUM access

Create a dedicated key on the collaborator's Mac:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/astra_astrum_ed25519 -C "astra-collaborator"
cat ~/.ssh/astra_astrum_ed25519.pub
```

Send only the `.pub` contents to the ASTRUM administrator. Never send the file
without `.pub`. The administrator adds the public key to the collaborator's
authorized ASTRUM account and communicates the SSH username and Tailscale host
out of band.

Add a host alias to `~/.ssh/config`:

```sshconfig
Host astrum
    HostName YOUR_TAILSCALE_HOST
    User YOUR_ASTRUM_USER
    IdentityFile ~/.ssh/astra_astrum_ed25519
    IdentitiesOnly yes
    ProxyCommand tailscale nc %h %p
```

Then restrict the local files and test the route:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/astra_astrum_ed25519 ~/.ssh/config
ssh astrum 'hostname; ~/astra-worker/astra_engine.sh list'
```

Edit ASTRA's `.env` and replace the two placeholder lines with:

```dotenv
ASTRA_REMOTE_HOST=astrum
ASTRA_REMOTE_SSH_OPTIONS=
```

The alias keeps machine-specific host, user, and key information out of the
repository. The `astra_engine.sh list` command is authoritative on ASTRUM;
plain `which sage` or `which cadabra2` is not, because the engines live in
separate managed environments.

## 5. Verify the installation

These checks do not call the language models and therefore do not consume model
quota:

```bash
venv/bin/python scripts/astra_doctor.py --remote
remote/check_remote_oracle.sh
venv/bin/python -m pytest -q
```

The doctor checks the binaries and production architecture but cannot prove
that each subscription has remaining quota. The final smoke test below makes a
real three-model call and should be run only after the non-model checks pass.

## 6. Connect Antigravity as the instructor

Open the cloned `ASTRA` directory as the Antigravity workspace. Go to
**Settings → Customizations → MCP Servers**, refresh the installed servers, and
confirm that `astra` appears. The installer generated this workspace entry:

```json
{
  "mcpServers": {
    "astra": {
      "command": "/absolute/path/to/ASTRA/venv/bin/python",
      "args": ["/absolute/path/to/ASTRA/mcp_server/server.py"],
      "cwd": "/absolute/path/to/ASTRA"
    }
  }
}
```

Keep MCP permission mode at **Ask** initially. After the tool list has been
reviewed, the user may allow `mcp(astra/*)` for this workspace. Paste the prompt
from `docs/onboarding/ANTIGRAVITY_INSTRUCTOR_PROMPT_EN.md` into a new task.

Ask the instructor to perform these no-quota checks first:

1. Call `astra_capacity`.
2. Call `astra_status` and confirm ASTRUM is reachable.
3. Call `astra_engines`; this is the authoritative ASTRUM engine inventory.
4. Use `astra_execute` for a short local SymPy/Z3 validator.
5. Use `astra_client_validate` for the minimum application-facing evidence
   suite when a client or project claim needs a structured artifact.

For the first actual deliberative smoke test, give ASTRA a narrow falsifiable
claim, use `astra_cycle_submit`, and poll the returned `job_id` with `astra_job`.
Do not use a broad paper audit as the first test.

## 7. How to interpret a result

The instructor must always report four separate layers:

- `job.status`: whether the background job operationally finished.
- `oracle_verdict`: whether the generated executable check printed PASS or FAIL.
- `atomic_status`: the verdict for the bounded conjecture tested in this cycle.
- `goal_coverage` and `scientific_status`: whether the wider objective was
  actually covered.

A finished job with an oracle PASS can still be only `ATOMIC_VALIDATED`; it is
not automatically evidence for an entire manuscript or research program.

## 8. Optional local integrations

If the collaborator needs to develop one company package locally, clone that
repository separately and set its `ASTRA_*_ROOT` variable in `.env`. Do not copy
another user's absolute workstation paths. Mathematica and its bridge are optional and
require a licensed local Mathematica installation; absence of Mathematica does
not weaken the standard SymPy/Sage/Maxima/Cadabra/Lean validation routes.

ASTRA can execute maintained company packages without cloning them onto the
Mac. Use `oracle="astrum"` and begin the Python validator with
`# ASTRA_ENGINE: pkgs`. For the ASTRUM materials/condensed-matter environment,
use `# ASTRA_ENGINE: sci`. The code and its evidence still travel through the
same ASTRA MCP/oracle boundary.

To launch the browser interface in addition to Antigravity:

```bash
./launch_astra.sh
```

## 9. Updating safely

```bash
cd ~/Dev/ASTRA
git pull --ff-only
bash install_macos.sh
venv/bin/python scripts/astra_doctor.py --remote
```

The installer is idempotent and preserves `.env`. If MCP code changes while
Antigravity is open, refresh its MCP servers; if the old server process remains,
restart Antigravity once.

If an earlier attempt left a Python 3.11 `venv/` and Python 3.12 is now
selected, do not delete it manually. The installer detects the mismatch and
moves the old environment to a recoverable backup before continuing.
