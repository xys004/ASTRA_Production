# Bayesian Experiment Planning in ASTRA

## Scope

ASTRA's Gaussian-process Bayesian planner is an optional numerical and hybrid
research component. It is not the core analytical loop and it is not a
scientific validator.

The intended division of labor is:

1. analytical or symbolic work derives identities, constraints, admissible
   domains, invariants, or reduced parameterizations;
2. the Bayesian planner selects informative numerical evaluations inside that
   admissible space;
3. the ASTRA oracle evaluates the selected points and records reproducible
   evidence;
4. symbolic, formal, cross-oracle, and human gates decide what may be accepted.

This is most useful when each numerical evaluation is expensive and the search
space has a moderate number of continuous variables.

## Current implementation

`core/bayesian_optimization.py` provides:

- bounded continuous variables;
- Latin-hypercube initialization;
- a Matérn-5/2 Gaussian-process surrogate;
- fitted length scale, signal, and observation-noise parameters;
- expected improvement for minimization or maximization;
- diversity-aware batch suggestions;
- strict attempt budgets;
- separate recording of valid measurements and operational failures; and
- JSON-serializable state and evidence.

The implementation uses the NumPy and SciPy dependencies already present in
ASTRA. It does not require scikit-learn, BoTorch, or another optimization
framework.

Operational failures are never silently converted into unfavorable objective
values. Doing so would distort the surrogate and could make an unavailable
solver look like an unfavorable physical region.

## Hybrid symbolic-numerical pilot

The pilot first solves an exact symbolic constraint,

```text
x**2 + y**2 + z - 1 = 0
```

for the dependent variable:

```text
z = 1 - x**2 - y**2
```

Only `x` and `y` are exposed to numerical search. Bayesian optimization,
seeded random search, and a uniform grid then receive the same evaluation
budget. The best point from every method is replayed independently at high
precision.

Run the default 25-evaluation comparison:

```powershell
.\venv\Scripts\python.exe scripts\run_bayesian_optimization_pilot.py
```

Use a different fixed budget or a small heuristic batch:

```powershell
.\venv\Scripts\python.exe scripts\run_bayesian_optimization_pilot.py `
  --budget 25 --initial-points 6 --batch-size 4 --seed 20260729
```

Reports are written to:

```text
workspace/bayesian_optimization_runs/<run_id>.json
workspace/bayesian_optimization_runs/<run_id>.md
```

The objective is a synthetic multimodal proxy. The pilot tests the planner,
budget accounting, exact symbolic reduction, and replay contract; it is not a
physics result or a general claim that Bayesian optimization outperforms every
alternative.

The frozen v1 result and its precise claim boundary are recorded in
[`benchmarks/bayesian_optimization/PILOT_V1_RESULT.md`](benchmarks/bayesian_optimization/PILOT_V1_RESULT.md).

## Real analytical-project benchmark

ASTRA also includes an optional read-only adapter for the exact Israel-shell
evaluator in the separate `hollow_core_energy_conditions` project. The
benchmark analytically eliminates one mass to preserve a fixed central lapse,
uses an exact two-shell embedding as a shared incumbent, and asks GP, random,
and grid search to spend equal budgets on local four-shell counterexamples.

```powershell
.\venv\Scripts\python.exe scripts\run_hollow_core_bayesian_benchmark.py
```

The benchmark records strict surface-density and NEC signs independently of
the source evaluator's numerical WEC/DEC tolerance. Its frozen result and
physical limitations are documented in
[`benchmarks/bayesian_optimization/HOLLOW_CORE_LOCAL_V1_RESULT.md`](benchmarks/bayesian_optimization/HOLLOW_CORE_LOCAL_V1_RESULT.md).

## Reusable API

```python
from core.bayesian_optimization import (
    BayesianExperimentPlanner,
    ContinuousParameter,
    run_budgeted_search,
)

planner = BayesianExperimentPlanner(
    [
        ContinuousParameter("radius", 0.1, 10.0),
        ContinuousParameter("width", 0.01, 2.0),
    ],
    direction="minimize",
    seed=17,
    initial_points=6,
)

report = run_budgeted_search(
    planner,
    expensive_validator,
    budget=30,
    batch_size=1,
)
```

An evaluator may return either a numeric value or `(value, metadata)`.
Exceptions become explicit `ERROR` observations and are excluded from GP
fitting.

## ASTRUM execution

Bayesian optimization is sequential between updates but can propose a small
batch of candidates per iteration. Those independent evaluations may run on
ASTRUM when they are genuinely expensive or parallelizable.

The current pilot executes locally because its synthetic objective is cheap;
remote startup would dominate runtime. Production integration should connect a
batch suggestion to existing detached oracle jobs, wait for their evidence
bundles, and update the surrogate only after each result has passed the
operational evidence gate.

## Scientific acceptance boundary

A low surrogate mean or a high acquisition value is not evidence that a claim
is true. A candidate selected by the GP must still be:

- executed by the declared numerical or symbolic engine;
- checked against exact constraints and tolerances;
- replayed when consequential;
- cross-validated with an independent engine where appropriate;
- passed to Lean or another formal system when a proof obligation exists; and
- admitted only through ASTRA's human gate.

## Where a GP is not the right tool

A conventional GP becomes less suitable for:

- high-dimensional spaces without exploitable structure;
- raw source code, proof trees, or unrestricted natural-language prompts;
- strongly categorical decisions;
- discontinuous objectives dominated by solver failures; or
- symbolic derivations whose value cannot be represented by a defensible
  numerical objective.

Those cases may require theorem-prover search, rewrite systems, MCTS, program
synthesis, evolutionary methods, bandits, TPE, random forests, or
domain-specific algorithms. ASTRA should route by problem structure rather
than force every research branch into Bayesian optimization.
