# ASTRA production evidence snapshot — 26 July 2026

This tracked snapshot separates measured release evidence from claims that still
require a frozen comparative run. It is not a frontier-model leaderboard.

| Evidence gate | Result | What it supports |
|---|---:|---|
| Automated production suite | 68/68 passed | Current routing, repair, benchmark and assurance code is regression-tested. |
| Client local–ASTRUM replication | 8/8 bundles; 100% agreement | Four application claims reproduced across Windows and the ASTRUM Linux worker. |
| Four-worker execution smoke | 8/8 grade A; 100% accuracy/agreement | Independent deterministic work can fan out across local and remote oracles. |
| Validator Repair vNext.1 | 4/4 patterns repaired; 0/3 sound false blocks | The exact local repairs claimed by vNext.1 work on the frozen regression set. |
| Paired diversity canary | 2/4 passes in both arms | Heterogeneous proposals were more separated (0.7459 vs 0.5958), without a pass-rate win. |
| Historical vNext.0 trajectory | 0/4 credible cycles | The first repair strategy was a valid null result. |
| vNext.1 maximum-model one-cell diagnostic | Reviewer timeout; 0 admitted cycles | The remaining end-to-end bottleneck is the sequential maximum-model path. |
| Unreviewed diagnostic salvage | 12/12 repaired checks passed on ASTRUM | The new symbolic-zero repair fixes the observed validator false negative; it is not scientific admission. |

## Latest repair learned from the canary

The generated curvature validator contained a dedicated `all_zero` helper that
used raw SymPy equality on tensor entries. One exact trigonometric identity
remained noncanonical, so the remote script printed `FAIL` even though its
Cartan and numerical legs passed. The production preflight now detects that
specific structure and applies:

```python
sp.trigsimp(entry, method="fu") == 0
```

The production repair changed the same canary artifact locally, passed
postflight, and produced 12/12 successful checks on ASTRUM in 0.476 seconds.
Because the independent Codex reviewer timed out before approving the original
artifact, this result remains explicitly `NOT_ADMITTED`.

## Cost and comparison boundary

The one-cell maximum-model trajectory consumed eight observable model calls and
1,453.5 wall seconds without accepted evidence. The quick deterministic gate
has 0.702 ms median and 1.913 ms P95 repair latency over 300 repeats. These
figures support a product strategy of cheap deterministic gates before expensive
model review. They do not establish lower cost per scientific discovery than
frontier research systems, whose comparable per-discovery economics are not
publicly available.

The full frozen Research Trajectory comparison, larger public-benchmark subsets,
blinded expert scoring, and design-partner economics remain required before
claiming scientific-quality or cost superiority.
