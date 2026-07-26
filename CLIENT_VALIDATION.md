# ASTRA Minimum Client Validation

This package is the smallest validation that ASTRA should present to a client
interested in applications. It demonstrates a complete chain:

1. a concrete claim or operational objective;
2. an executable artifact;
3. deterministic routing to an appropriate validator;
4. an explicit claim verdict;
5. a reproducible evidence bundle with assumptions and limitations.

It is intentionally different from a leaderboard. Public benchmarks measure
general task-solving ability; this package shows how ASTRA would support a
client decision.

## Validator router

| Artifact | Primary validator | Independent alternatives |
|---|---|---|
| Formal invariant | Lean 4 kernel + pinned Mathlib | Manual formal review |
| Logical constraints | Z3 | Lean 4, policy review |
| Symbolic formula | SymPy | Mathematica bridge, SageMath |
| Numerical model | SciPy residuals and invariants | Mathematica bridge, domain simulator |
| Engineering units | Pint | Mathematica bridge, units audit |
| Scientific package | Package public API + scientific invariants | SymPy, Mathematica bridge |

The router does not claim that one validator is appropriate for every
scientific question. Lean proves consequences of formalized assumptions;
numerical and domain validators establish the premises that come from a model,
measurement or software package.

## Minimum application set

Six cases are tracked under `benchmarks/client_validation/`:

| Case | Application | Expected claim |
|---|---|---|
| `client_capacity_policy_refutation` | Capacity constraints | REFUTED |
| `client_control_response` | Numerical control model | VALIDATED |
| `client_fluid_pressure_scaling` | Units and engineering scaling | VALIDATED |
| `client_formula_regression` | Symbolic regression | VALIDATED |
| `client_grpython_flat_spacetime` | GR_python package assurance | VALIDATED |
| `client_grpython_zero_trace_formal` | Formal aggregation invariant | VALIDATED |

The negative capacity case is deliberate. A useful assurance system must reject
a false client promise, not only approve true examples.

## GR_python vertical demonstration

The two `grpython` cases form one linked demonstration:

- GR_python computes the Christoffel symbols, Riemann tensor, Ricci tensor and
  Ricci scalar for Minkowski spacetime in spherical coordinates.
- The connection must be nonzero because the coordinates are curvilinear,
  while the curvature tensors must vanish.
- Lean 4 kernel-checks the separate logical implication that a four-component
  pointwise-zero Ricci diagonal has zero finite trace.

This split is important. Lean certifies the aggregation logic; it does not
silently replace or bless the tensor calculation performed by GR_python.

## Pinned formal environment

New product formalizations use:

- Lean `4.30.0`;
- toolchain `leanprover/lean4:v4.30.0`;
- Mathlib commit `c5ea00351c28e24afc9f0f84379aa41082b1188f`.

The project follows [Lean's project/toolchain
model](https://lean-lang.org/install/manual/) and uses [Mathlib's compiled
cache](https://github.com/leanprover-community/mathlib4). Lean 3.42.1 remains
installed separately only for the miniF2F v1 benchmark.

Prepare ASTRUM without administrator privileges:

```powershell
python scripts\run_client_validation.py --prepare-lean4 --timeout 3600
```

## Running the package

List routes without executing:

```powershell
python scripts\run_client_validation.py --list --oracle both
```

Run the complete local/ASTRUM matrix:

```powershell
python scripts\run_client_validation.py --oracle both --timeout 300
```

Run one application case:

```powershell
python scripts\run_client_validation.py `
  --only client_grpython_flat_spacetime --oracle local
```

From Codex or another agent connected to ASTRA's MCP, call:

```text
astra_client_validate(
  case_id="client_grpython_flat_spacetime",
  oracle="local"
)
```

Reports are written to the ignored
`workspace/client_validation_runs/` directory. Every JSON evidence bundle
contains:

- artifact path, SHA-256 and byte count;
- route decision and alternatives;
- executable and claim verdicts;
- structured scientific evidence;
- oracle, duration and runtime metadata;
- ASTRA and project-package Git commits;
- assumptions, limitations and an exact reproduction command.

## Verified result — 24 July 2026

The complete `--oracle both` matrix produced:

| Metric | Result |
|---|---:|
| Registered/executed cases | 6/6 |
| Passing evidence bundles | 10/10 |
| Passing cases | 6/6 |
| Cases reproduced locally and on ASTRUM | 4 |
| Cross-oracle claim agreement | 1.0 |

Selected evidence:

- Z3 returned `unsat` for the deliberately false capacity promise on both
  oracles.
- The numerical control response had maximum error
  `1.93 × 10^-12` and ODE residual `2.78 × 10^-17`.
- Doubling pipe radius produced pressure-drop ratio `0.25` with pressure
  dimensionality.
- SymPy reduced the formula-regression residual to exactly zero.
- GR_python commit `8f449aa5…` produced 9 nonzero Christoffel components, zero
  nonzero Riemann components, zero nonzero Ricci components and Ricci scalar
  zero.
- Lean 4.30.0 kernel-checked the linked zero-trace theorem against Mathlib
  commit `c5ea00351…`.

The raw report is
`workspace/client_validation_runs/client_validation_20260724_102428.json`.

## Acceptance rule

A bundle passes only when all of the following are true:

1. the validator process succeeds;
2. the artifact prints or produces an explicit successful execution verdict;
3. the claim verdict matches the registered expected verdict;
4. every required evidence field is present;
5. no formal placeholder such as `sorry`, `admit` or a new `axiom` is used.

When a portable case runs locally and on ASTRUM, both claim verdicts must agree.

## Commercial scope

Passing this package establishes a reproducible minimum capability, not
regulatory certification or universal scientific correctness. A client pilot
should replace or supplement these seed cases with 5–10 private cases from the
client's own workflow, including at least one expected refutation and one
failure caused by bad assumptions or bad data.

The seed artifacts are curated deterministic validators. They test routing,
execution and evidence integrity; the earlier AInsteinBench pilot covers blind
agent generation and repair. A commercial pilot should combine both layers:
ASTRA generates the client artifact, then this evidence contract decides
whether it is acceptable.

The optional `mathematica-agent-bridge` remains an independent cross-validator
for symbolic expressions, notebooks and tensor calculations when a Mathematica
kernel is running. It is an alternative validator, not a hidden dependency of
the minimum package.
