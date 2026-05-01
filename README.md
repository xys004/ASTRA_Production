# ASTRUM Production

**Autonomous Symbolic Theorem Reasoning for Unified Mathematics**

ASTRUM Production is a multi-agent research orchestrator for turning scientific intuition into mathematically testable hypotheses. It uses LLM providers for reasoning phases and symbolic/numerical engines for validation.

## What It Does

1. **Conjecture Engine** formalizes an intuition, note, or paper excerpt into a falsifiable mathematical hypothesis.
2. **Formal Translator** converts the hypothesis into a validation script.
3. **Validation Oracle** executes the script with Python, SageMath, Maxima, or Cadabra.
4. **Refutation Analyst** classifies the result as `VALIDATED`, `REFUTED`, or `CODE_ERROR`.
5. **Human Approval** decides whether a validated result becomes part of the axiomatic base.

ASTRUM is designed for theoretical physics, GR, quantum systems, fluids, symbolic calculus, differential equations, and mathematical model checking.

## Clean Windows Installation

Use this path for company or institution deployments. It does not require Anaconda or preinstalled Python packages.

1. Download or clone the project.
2. Right-click `install_windows_wsl.ps1`.
3. Choose **Run with PowerShell**.
4. If Windows asks to install WSL/Ubuntu or reboot, accept it, reboot, then run the installer again.
5. Launch **ASTRUM Production Wizard (WSL)** from the Desktop.

The installer prepares:

- WSL Ubuntu.
- Python 3 and `.astra-wsl-venv`.
- Python packages from `requirements.txt`.
- SageMath and Maxima through Ubuntu packages.
- Cadabra when available in the Ubuntu repository.
- A Windows Desktop shortcut that launches ASTRUM through WSL.

## API Configuration

The wizard asks for API keys and stores them in `.env`.

```env
GEMINI_API_KEY=your_gemini_key
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
```

ASTRUM can use one provider for all phases or different providers per phase.

```env
ASTRA_CONJECTURE_PROVIDER=gemini
ASTRA_TRANSLATOR_PROVIDER=anthropic
ASTRA_ANALYST_PROVIDER=openai
```

Recommended layouts:

- **One-key users:** use the same provider for all phases.
- **Two-provider users:** use Gemini or Claude for conjecture, and OpenAI or Claude for translation/analysis.
- **Three-provider users:** use Gemini for conjecture, Claude for formal translation, and OpenAI for refutation analysis.

The wizard validates only the providers selected for the run.

## Validation Engines

Python packages:

- `sympy`: symbolic algebra, calculus, identities, residuals.
- `z3-solver`: satisfiability, inequalities, counterexample search.
- `scipy`, `numpy`, `mpmath`: ODEs, numerical validation, optimization, high precision checks.
- `einsteinpy`: GR metrics, Christoffel symbols, curvature tensors, geodesics.
- `fluids`, `pint`: fluid mechanics and dimensional consistency.
- `qutip`: quantum systems, density matrices, open-system dynamics.
- `numba`, `matplotlib`, `networkx`: performance and diagnostics.

External CAS engines:

- `# ASTRA_ENGINE: sage`
- `# ASTRA_ENGINE: maxima`
- `# ASTRA_ENGINE: cadabra`

If an optional CAS is missing, the oracle returns a clear failure instead of treating the result as validated.

## Example Inputs

Paste one of these into the intuition box.

### General Relativity

```text
Test whether a static spherically symmetric metric with f(r)=1-2M/r has vanishing Ricci scalar outside r=2M, and produce a symbolic residual that can refute the claim.
```

Expected behavior: the translator should prefer `sympy`, `einsteinpy`, or `sage` and compute curvature-related residuals.

### Differential Equations

```text
Given y'' + omega^2 y = 0 with y(0)=1 and y'(0)=0, validate that the proposed solution y=cos(omega t) satisfies the equation and boundary conditions.
```

Expected behavior: the translator should use `sympy` for symbolic residuals or `scipy` for a numerical check.

### Fluid Mechanics

```text
For incompressible laminar pipe flow, test whether pressure drop is proportional to viscosity, length, and mean velocity, and inversely proportional to radius squared under the Hagen-Poiseuille assumptions.
```

Expected behavior: the translator should use symbolic dimensional checks, `fluids`, and `pint` where useful.

### Logic / Counterexample Search

```text
Check whether the claim "for all positive real x and y, x + y >= 2 sqrt(x y)" can be refuted by bounded numerical sampling or symbolic inequality reasoning.
```

Expected behavior: the translator may use `sympy`, `z3`, or numerical sampling with explicit tolerances.

### Tensor / QFT Style

```text
Test an abstract tensor identity involving antisymmetric F_ab and the Bianchi-like condition dF=0. Prefer an indexed symbolic engine if available.
```

Expected behavior: the translator should prefer Cadabra when available, otherwise return a clear missing-engine failure or use a reduced symbolic test.

## Benchmark Suite

ASTRUM includes a small golden benchmark suite for calibrating provider layouts, prompts, and validation engines before attempting novel research.

```txt
benchmarks/
  gr/
  ode/
  fluids/
  logic/
  quantum/
  symbolic/
```

List all benchmark cases:

```powershell
python scripts\list_benchmarks.py
```

Print a benchmark as a prompt:

```powershell
python scripts\list_benchmarks.py --prompt gr_schwarzschild_ricci_scalar
```

Initial suite:

- GR: Schwarzschild Ricci scalar, Minkowski flat curvature.
- ODE: harmonic oscillator solution, logistic equilibrium stability.
- Fluids: Hagen-Poiseuille scaling, Reynolds dimensionless check.
- Logic: AM-GM inequality, false square claim.
- Quantum: Pauli commutator, trace preservation under unitary evolution.
- Symbolic CAS: polynomial factorization, false antiderivative check.

Recommended use:

1. Run the same benchmark with one-provider and three-provider layouts.
2. Compare `VALIDATED`, `REFUTED`, `CODE_ERROR`, and false-positive rates.
3. Inspect generated reports in `workspace/reports/`.
4. Add new domain-specific benchmarks before using ASTRUM on unknown research problems.

## Reading Results

The UI displays:

- Current system status.
- Phase logs.
- Current conjecture.
- Last generated validation code.
- Axiomatic base.
- Approval controls when a theorem is validated.

Validation is conservative. A result should only be approved when the evidence is mathematically meaningful and the script did not merely pass trivially.

## Packaging A Release

Create a compact source ZIP:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1 -Version v0.1.0
```

The ZIP excludes virtual environments, workspace outputs, `.env`, git metadata, caches, and local artifacts. Publish that ZIP through GitHub Releases or distribute it internally.

## Legacy Local Windows Install

`install.ps1` and `setup.bat` are retained for local experiments. They are not recommended for clean institutional distribution because SageMath, Maxima, and Cadabra are not normal Windows `pip install` dependencies.
