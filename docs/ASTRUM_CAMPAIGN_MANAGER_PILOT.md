# Reversible ASTRUM campaign-manager pilot

This experiment adds campaign semantics above the existing ASTRUM scheduler.
It does **not** modify `remote/astra_cluster_manager.py`, install a daemon,
contact ASTRUM, or submit remote work.

The manifest contract provides:

- an immutable `campaign_id` plus canonical manifest SHA-256;
- per-campaign `max_concurrency`;
- unique task `idempotency_key` values;
- `afterok` and `afterany` dependencies with cycle rejection;
- an attempt ledger with parent-attempt lineage;
- retries only when the executor reports an operational failure class that the
  immutable manifest preregistered;
- terminal first-attempt treatment of every scientific failure, even when the
  task declares more than one possible attempt.

The executable example is
`docs/ASTRUM_CAMPAIGN_MANAGER_PILOT.json`.  It contains four independent small
tasks and one `afterany` aggregator.  One small task fails once with the
preregistered `transient_transport` class and succeeds on its second attempt.
Another returns a scientific `FAIL`; it is attempted exactly once.  The
aggregator still runs, but the campaign finishes as `completed_with_failures`,
so `afterany` cannot launder a failed scientific gate into campaign success.

Tests use a temporary SQLite database and a fake executor.  The production
scheduler remains the sole authority for ASTRUM CPU, GPU and memory admission.

## Risks before a real adapter

- Concurrency is currently enforced only inside one experimental campaign;
  global admission must continue to be delegated to ASTRUM.
- There is no crash-resume lease protocol yet.  A production adapter needs to
  reconcile persisted attempts with `astra_cluster_job` before resubmitting.
- Operational failure taxonomy must be narrow and immutable.  Scientific
  `FAIL`, nonzero physical gates, and ambiguous verdicts must never be mapped to
  retryable transport classes.
- Idempotency currently has campaign scope.  A production adapter should bind
  it to the submitted code/payload digest and the returned ASTRUM job ID.
- Backoff is implemented for the synchronous pilot; a persistent service would
  need wake-up scheduling rather than sleeping a manager process.

The next reversible step, if approved, is an adapter fake for the existing MCP
contract followed by a four-no-op remote smoke campaign.  It must not replace
or bypass the shared scheduler.

## Local scheduler adapter

`core/experimental_astrum_campaign_adapter.py` implements that first adapter
step without performing a deployment.  It speaks the existing scheduler's
`submit`/`job` RPC schema, binds each campaign/task/attempt tuple to exactly one
scheduler job ID and request digest, and can reconcile a persisted running
attempt after the local manager restarts.  Its real `ClusterRpcGateway` is
opt-in; tests use a fake gateway and never contact ASTRUM.

The terminal mapping is deliberately conservative.  A scheduler result with
`VERDICT: FAIL` is a scientific failure even if its process exited nonzero, and
is never retried.  A zero-exit `succeeded` job without an unambiguous `PASS` is
also a terminal scientific failure.  Only known operational states can reach
the manifest allowlist.  Cancellation, missing bindings, ambiguous submission,
protocol errors and local poll exhaustion are hard non-retry classes because a
blind resubmission could duplicate work.

A transient error while polling an already bound job is not treated as job
failure: the adapter retains the original scheduler job ID and reconciles that
same job until a terminal state is observed.

The scheduler and adapter now also support an optional caller-supplied native
idempotency key.  The scheduler stores that key, scoped to the normalized client
identity, together with a SHA-256 digest of the normalized request.  An exact
replay returns the original job ID after an RPC response loss or process
restart; reuse with different code, resources, engine, project or timeout is
rejected.  Callers that omit the key retain the previous submit-always-creates
behavior.  The adapter derives one stable scheduler key per
campaign/task/attempt, retries only that exact request, and can recover a job
accepted before its local binding transaction committed.

## Local CLI and preregistered smoke

`scripts/astrum_campaign.py` exposes four explicit operations:

```powershell
python scripts\astrum_campaign.py preflight --manifest docs\ASTRUM_CAMPAIGN_REMOTE_SMOKE_V1.json
python scripts\astrum_campaign.py register --manifest docs\ASTRUM_CAMPAIGN_REMOTE_SMOKE_V1.json --db output\campaign-smoke.sqlite3
python scripts\astrum_campaign.py status --campaign-id astrum-remote-smoke-v1 --db output\campaign-smoke.sqlite3
python scripts\astrum_campaign.py resume --campaign-id astrum-remote-smoke-v1 --db output\campaign-smoke.sqlite3 --execute-remote
```

Only `resume --execute-remote` constructs the SSH gateway.  Preflight validates
both the immutable campaign graph and every scheduler payload; register is
idempotent for the exact manifest; status is read-only.  The preregistered
smoke contains four one-CPU/128-MiB Python no-ops and one `afterany` aggregator,
with concurrency two and no warp-science payloads.  It is evidence for campaign
plumbing only and has not been submitted to ASTRUM.
