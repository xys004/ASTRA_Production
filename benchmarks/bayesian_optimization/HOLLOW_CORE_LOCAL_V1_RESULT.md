# Hollow-Core Multishell Bayesian Search v1

Status date: 2026-07-29

## Question

In the exact static Israel-shell family implemented by
`hollow_core_energy_conditions`, can small two-parameter perturbations of an
embedded two-shell solution lower its absolute proper shell energy while
preserving the fixed central lapse, flat core, zero exterior ADM mass, and
horizon margin?

This is a real project evaluator, not the synthetic ASTRA planner proxy.

## Claim boundary

This is a finite local counterexample search in one exact four-shell family. It
is not:

- a global variational theorem;
- a smooth matter construction;
- a semiclassical negative-energy source model;
- evidence of stability or manufacturability; or
- a warp-transport result.

Failure to find a lower configuration is local numerical negative evidence,
not proof of optimality.

## Frozen source and analytical gate

- Source project: `hollow_core_energy_conditions`
- Source file: `derivations/search_multishell_lower_energy.py`
- Source SHA-256:
  `59f21ecd6825761cdfe4301dccf8b8c36359b3749f3ae0f59c1c46fb8540e2d8`
- Source loaded read-only; no files in the source project were changed.
- Radii: `[1, 3, 100, 10000]`
- Central lapse: `A_c = 0.93106939035`
- Exterior ADM mass: `0`
- Objective: absolute proper surface energy `E_abs/L`

The first intermediate mass is eliminated analytically through

```text
(1 - 2 m1/R1)/(1 - 2 m1/R2) = Q,
```

with

```text
m1 = (1-Q) / (2(1/R1-Q/R2)).
```

SymPy reduced the defining residual to exact zero before the numerical search.

The remaining two compactness variables were perturbed by

```text
c = c_incumbent + 1e-3 (u, v),    (u,v) in [-1,1]^2.
```

## Shared analytical incumbent

Every method received the same incumbent as its first evaluation:

```text
compactness variables = [0.044373776837030275, 0.0013312133051109083]
E_abs/L                = 0.13549769370379705
lapse residual         = 1.67e-16
horizon margin         = 0.8668786694889092
```

This zero-exterior-ADM configuration is sign-indefinite. The exterior surface
density is

```text
minimum sigma = -5.29674707328e-11.
```

The source evaluator's `-1e-10` tolerance labels that shell as WEC/DEC passing.
The ASTRA benchmark does not interpret that tolerance flag as positive energy:
it records strict `sigma<0` and `sigma+P<0` signs separately. The incumbent has
one strictly negative-density shell and one strictly NEC-violating shell.

## Equal-budget result

Run: `hollow_core_bayesian_20260729_150046`

Each method received 25 total objective evaluations:

- one shared analytical incumbent;
- 24 distinct challengers.

| Rank | Method | Best challenger gap above incumbent | Counterexamples | Independent replay |
|---:|---|---:|---:|---:|
| 1 | GP + expected improvement | 0.0000965189745732 | 0 | passed |
| 2 | Seeded random search | 0.000567064850975 | 0 | passed |
| 3 | Uniform local grid | 0.000658799704898 | 0 | passed |

All 75 method evaluations were operationally valid. No method found a
candidate below the analytical incumbent at the registered `1e-12`
counterexample tolerance.

The GP's best distinct challenger was:

- about `5.87` times closer to the incumbent than the random-search challenger;
- about `6.83` times closer than the grid challenger.

All best candidates and best challengers passed:

- replay through the source evaluator;
- an independent 80-digit `mpmath` implementation;
- fixed-lapse residual checks; and
- the no-horizon check.

## Interpretation

The result shows a useful analytical-numerical division of labor:

1. an exact family and lapse constraint supply the feasible manifold;
2. the analytical solution supplies a strong incumbent;
3. the GP spends the remaining budget close to the narrow low-energy basin;
4. independent equations audit the best numerical challengers; and
5. the result remains a finite null search rather than being promoted to a
   theorem.

This is evidence that Bayesian planning can improve local counterexample
allocation inside an ASTRA analytical workflow. It is not evidence that the GP
improved the physical construction: all methods retained the analytical
incumbent, and that incumbent contains a negative outer shell.

## Reproduction

From the ASTRA root:

```powershell
.\venv\Scripts\python.exe scripts\run_hollow_core_bayesian_benchmark.py `
  --budget 25 --initial-points 6 --batch-size 1 --seed 20260729
```

If the scientific project is not under the standard `Dev/warp` layout, set:

```powershell
$env:ASTRA_HOLLOW_CORE_ROOT='path\to\hollow_core_energy_conditions'
```

Detailed runtime evidence is generated under
`workspace/hollow_core_bayesian_runs/`.
