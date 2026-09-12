# ASTRA Hybrid Bayesian-Optimization Pilot v1

Status date: 2026-07-29

## Claim boundary

This is a synthetic hybrid-planning result. It demonstrates budget accounting,
exact symbolic reduction, GP-driven numerical selection, baseline comparison,
and independent replay. It is not a physics result, a formal proof, or a claim
that Bayesian optimization generally outperforms other search methods.

## Frozen configuration

- Script: `scripts/run_bayesian_optimization_pilot.py`
- Seed: `20260729`
- Independent variables: `x`, `y`
- Bounds: `[-0.9, 0.9]` for both variables
- Exact constraint: `x**2 + y**2 + z - 1 = 0`
- Symbolically derived relation: `z = 1 - x**2 - y**2`
- Reduced symbolic residual: `0`
- Equal evaluation budget: 25 per compared method
- GP initial design: 6 Latin-hypercube points
- GP kernel: Matérn 5/2
- Acquisition: expected improvement
- Batch size: 1

## Result

Run: `bayesian_pilot_20260729_144552`

| Rank | Method | Evaluations | Best value | Regret to reference | Final replay |
|---:|---|---:|---:|---:|---:|
| 1 | GP + expected improvement | 25 | 0.01036579328 | 0.00004787486 | passed |
| 2 | Seeded random search | 25 | 0.05512174007 | 0.04480382165 | passed |
| 3 | Uniform grid | 25 | 0.06333529406 | 0.05301737564 | passed |

The independent differential-evolution reference reached
`0.01031791842` after 1,293 evaluations. It was not budget matched and was
used only to estimate regret.

All three final candidates passed:

- the reconstructed exact-constraint residual check;
- direct deterministic replay; and
- an independent 60-digit `mpmath` replay.

## Interpretation

On this one frozen proxy, the GP used 25 evaluations to reach a value within
`4.79e-05` of the independent reference and outperformed the two equal-budget
baselines. The result supports continuing development of the planner. It does
not establish scientific or cross-domain superiority.

The important architectural result is the order of operations:

```text
exact symbolic reduction
    -> budgeted numerical search
    -> independent replay
    -> domain/formal/human validation when used scientifically
```

## Reproduction

```powershell
.\venv\Scripts\python.exe scripts\run_bayesian_optimization_pilot.py `
  --budget 25 --initial-points 6 --batch-size 1 --seed 20260729
```

The detailed JSON and Markdown reports are generated under
`workspace/bayesian_optimization_runs/` and remain local runtime evidence.
