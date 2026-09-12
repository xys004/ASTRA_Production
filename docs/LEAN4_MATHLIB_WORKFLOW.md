# Lean 4 and Mathlib in ASTRA

ASTRA uses a complete, pinned Mathlib checkout for kernel-checked formal
artifacts. The pin is deliberate: changing Lean or Mathlib can change theorem
names, elaboration behavior, tactics, and generated proof terms.

## Canonical environment

The Windows workstation route is Debian under WSL2:

```text
Lean toolchain: leanprover/lean4:v4.30.0
Mathlib tag:    v4.30.0
Mathlib commit: c5ea00351c28e24afc9f0f84379aa41082b1188f
Project root:   /home/nelson/astra-benchmarks/mathlib4-v4.30.0
Lake:           /home/nelson/.elan/bin/lake
```

The same Lean and Mathlib pins are used by the ASTRUM formal oracle. The local
standalone `lean.exe` on Windows is not an ASTRA oracle unless it is explicitly
configured against this pinned Mathlib project.

To install or repair the complete workstation stack, including the compiled
Mathlib cache, run:

```powershell
.\scripts\bootstrap_wsl_scientific_stack.ps1
```

The bootstrap is idempotent and uses `lake exe cache get`; it does not require
building all of Mathlib from source when the official binary cache is
available.

## One-command verification

Run a representative kernel check through ASTRA's actual local router:

```powershell
.\scripts\check_lean4_mathlib.ps1
```

The smoke artifact imports all of `Mathlib` and exercises real algebra,
linear inequalities, positivity, finite sums, matrices, differentiation, and
Presburger arithmetic. To check the independent cluster environment instead:

```powershell
.\scripts\check_lean4_mathlib.ps1 -Oracle astrum
```

The first full `import Mathlib` check can take about two minutes on WSL. For
routine gates, use the narrowest stable imports that cover the proof; the full
library remains installed and available.

## ASTRA artifacts

An ASTRA-generated formal artifact starts with an engine marker and then
imports Mathlib:

```lean
# ASTRA_ENGINE: lean4
import Mathlib

theorem example_gate (x : ℝ) : x^2 ≥ 0 := by
  positivity
```

The router removes the marker before sending the source to Lean. A standalone
`.lean` file intended to be passed directly to Lean should omit the marker.

ASTRA rejects `sorry`, `admit`, and `axiom` before execution. Successful
type-checking means that Lean's kernel accepted the supplied proof term; it
does not establish that the theorem statement faithfully models the physical
system. Model-to-physics assumptions must therefore remain explicit in theorem
arguments and be audited independently with symbolic, constraint, numerical,
and empirical evidence as appropriate.

## Version upgrades

Do not update only one machine or one version string. A coordinated upgrade
must update the Lean toolchain, Mathlib tag and commit, workstation bootstrap,
ASTRUM bootstrap and verifier, formal-validator metadata, and regression tests.
Keep the previous pin available until the complete local/ASTRUM validation
suite passes on the new environment.
