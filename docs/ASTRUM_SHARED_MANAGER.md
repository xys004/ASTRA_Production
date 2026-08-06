# ASTRUM shared scientific-job manager

ASTRA deliberation remains on each researcher's workstation and uses that
researcher's authenticated Codex, Claude, and AGY CLIs. Only scientific
execution is admitted by the shared ASTRUM manager.

## Why it exists

The original `astra_submit` queue is local to one workstation. Two researchers
could therefore start valid but competing GPU/CPU workloads without seeing one
another. The shared manager adds one authoritative SQLite queue on ASTRUM with:

- stable `client_id` and project attribution;
- the submitting Tailscale/source IP for correlation with SSH key logs;
- persistent per-job directories, output, results, events, and heartbeats;
- fair rotation between clients at the same priority;
- central CPU and GPU slot admission;
- queued/running cancellation and timeout handling;
- persistence beyond the submitting SSH/MCP/laptop connection.

SQLite is stored on ASTRUM's local disk at
`~/astra-worker/cluster/state.db`. No database port or public service is opened;
all RPC traffic uses the already authenticated SSH path.

## Workstation configuration

Nelson:

```dotenv
ASTRA_CLIENT_ID=nelson
ASTRA_PROJECT_ID=general
ASTRA_REMOTE_SCHEDULER=1
ASTRA_REMOTE_CLUSTER_MANAGER=~/astra-worker/astra_cluster_manager.py
ASTRA_REMOTE_QUEUE_WAIT=300
```

Gabriel uses the same settings with `ASTRA_CLIENT_ID=gabriel`. The identifier is
an operational label, while Tailscale and each researcher's distinct SSH public
key provide the connection-level identity.

## MCP operations

- `astra_cluster_submit`: submit code with optional project, priority, CPU/GPU
  slots, memory advisory, and timeout.
- `astra_cluster_job`: inspect one job or the shared recent queue.
- `astra_cluster_cancel`: cancel a queued or running job and audit the requester.
- `astra_cluster_capacity`: inspect total, reserved, used, and available slots.

Ordinary remote `astra_execute` calls also use the scheduler when
`ASTRA_REMOTE_SCHEDULER=1`. If a synchronous call exhausts its queue-wait
budget, the returned `cluster_job_id` remains persistent and can be polled.

## ASTRUM service

The user service runs:

```bash
~/astra-worker/venv/bin/python \
  ~/astra-worker/astra_cluster_manager.py serve
```

Installed unit:

```text
~/.config/systemd/user/astra-cluster-manager.service
```

Operational checks:

```bash
systemctl --user status astra-cluster-manager.service
journalctl --user -u astra-cluster-manager.service --since today
~/astra-worker/venv/bin/python \
  ~/astra-worker/astra_cluster_manager.py rpc <<<'{"action":"capacity"}'
```

The default service reserves four logical CPUs for interactive/system work and
admits one GPU job at a time. These values are controlled by
`ASTRA_CLUSTER_CPU_RESERVE`, `ASTRA_CLUSTER_CPU_SLOTS`, and
`ASTRA_CLUSTER_GPU_SLOTS` in the unit.

If a pinned Mathlib dependency is present but not compiled, repair it without
running `lake update` at the Mathlib root:

```bash
~/astra-worker/repair_lean_mathlib.sh
```

## SSH audit

The administrator installs `remote/90-astra-audit.conf` as:

```text
/etc/ssh/sshd_config.d/90-astra-audit.conf
```

Validate before reloading:

```bash
~/astra-worker/install_ssh_audit.sh
sudo journalctl -u ssh --since today | grep 'Accepted publickey'
```

`LogLevel VERBOSE` records the accepted public-key fingerprint. It complements
the scheduler's `client_id`; it does not create separate Linux ownership while
all collaborators use the shared `astrum` account.

## Future multi-node growth

The MCP contract deliberately describes jobs and capacity rather than one
specific machine. A later release can replace the local admission backend with
Slurm or a multi-node lease table without changing how agents submit or poll
jobs.
