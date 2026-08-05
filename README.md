# ASTRA

**Autonomous Symbolic Theorem Reasoning Architecture**

Created by **Nelson Bolívar** and maintained by **Astrum Drive**.

ASTRA is a goal-driven, multi-model epistemological research engine. It turns
scientific intuition into falsifiable conjectures, executable evidence, explicit
refutations, and new research directions. Its design follows the
generation–verification–revision spirit of research agents such as
[Aletheia](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/),
but ASTRA uses three independent subscription CLIs instead of Gemini Deep Think.

## What It Does

1. **Shared Objective** — every model receives the same final scientific goal and
   the current research direction.
2. **Parallel Conjecture** — GPT‑5.6 Sol and agy independently explore hypotheses,
   then cross-criticize them; GPT‑5.6 Sol synthesizes a falsifiable consensus.
3. **Formal Translation** — Claude Opus 4.8 converts the consensus into a runnable
   Python, SageMath, Maxima, Cadabra, or Lean 4 validator.
4. **Independent Code Review** — GPT‑5.6 Sol audits whether Claude's program can
   actually prove or refute the decisive claims. Claude revises when required.
5. **Validation Oracle** — local or ASTRUM execution captures reproducible evidence.
6. **Refutation Analysis** — GPT‑5.6 Sol reads the code and the execution evidence;
   a printed `PASS` is not accepted as authority.
7. **Research Navigation** — agy relates the result back to the shared objective,
   proposes the next direction, and preserves independent branches.
8. **Human Approval** — a human decides whether validated results join the
   Axiomatic Base.

The production role map is:

| Role | Backend |
|---|---|
| Primary conjecture, synthesis, code review, final analysis | Codex CLI — `gpt-5.6-sol`, `xhigh` |
| Co-conjecture, cross-critique, research navigation | Antigravity `agy` CLI — `gemini-3.1-pro-high`, effort `high` |
| Formal translation and code revision | Claude Code CLI — `claude-opus-4-8` |

The browser UI, MCP server, and subprocess CLI all dispatch the same canonical
guarded cycle. Run the non-secret architecture contract whenever providers,
models, or orchestration are changed:

```powershell
.\venv\Scripts\python.exe scripts\audit_architecture.py
```

The audit fails closed on production role/model drift and reports optional
project integrations separately.

ASTRA is designed for theoretical physics, GR, quantum systems, fluid mechanics, symbolic calculus, differential equations, and mathematical model checking.

---

## macOS collaborator installation

ASTRA supports an Apple Silicon Mac as a full agent workstation: Codex, Claude
Code, and Antigravity `agy` run locally under the collaborator's own
subscriptions; Python/SymPy/Z3 validation runs locally; and the maintained
SageMath, Maxima, Cadabra, Lean, GPU, and company-package environments remain on
ASTRUM behind individual Tailscale/SSH access.

```bash
git clone https://github.com/AstrumDrive/ASTRA.git
cd ASTRA
bash install_macos.sh
```

The installer also registers ASTRA's MCP server for the Antigravity workspace.
See [`docs/onboarding/ASTRA_MACOS_INSTALL_EN.md`](docs/onboarding/ASTRA_MACOS_INSTALL_EN.md)
for prerequisites, per-user SSH authorization, verification, and the
Antigravity instructor workflow. A Spanish operational summary is available at
[`docs/onboarding/ASTRA_MACOS_INSTALL_ES.md`](docs/onboarding/ASTRA_MACOS_INSTALL_ES.md).

---

## Windows 11 Installation (Recommended)

No Anaconda or preinstalled packages are required. Use CPython 3.12 and
PowerShell. ASTRA's supported workstation range is Python 3.10-3.12; 3.12 is
the reproducible baseline used for collaborator installations.

### Step 1 — Download

Download or clone this repository:

```powershell
git clone https://github.com/AstrumDrive/ASTRA.git
cd ASTRA
```

Or download the ZIP from GitHub and extract it anywhere.

### Step 2 — Run the installer

Right-click `install.ps1` → **Run with PowerShell**.

The installer will:

- Prefer Python 3.12 and report the selected interpreter and architecture
- Preserve an incompatible existing environment as `venv.backup.*`
- Create the canonical local virtual environment (`venv/`)
- Install the shared workstation stack from `requirements-workstation.txt`
- Register the workspace-scoped ASTRA MCP entry for Antigravity
- Create a desktop shortcut **ASTRA** that launches the web interface

> If PowerShell blocks execution, run this first:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Step 3 — Configure model access

Launch ASTRA from the desktop shortcut. The browser opens at `http://127.0.0.1:5050`.

The production configuration uses authenticated Claude Code, Codex, and
Antigravity (`agy`) CLIs. It does not use Gemini API billing. Sign in to each CLI
once, then keep the production role map from `.env.example`.

API-backed providers remain available as optional alternatives. Click
**Settings ⚙** to enter keys when you intentionally choose one.

ASTRA works with **any one of these providers**:

| Provider | Where to get a key |
|---|---|
| Gemini Flash | [aistudio.google.com](https://aistudio.google.com) (free tier available) |
| Anthropic Claude | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI GPT-4o | [platform.openai.com](https://platform.openai.com) |
| DeepSeek R1 | [platform.deepseek.com](https://platform.deepseek.com) |
| xAI Grok | [console.x.ai](https://console.x.ai) |
| Qwen2.5-Math | [dashscope.aliyun.com](https://dashscope.aliyun.com) |
| Mistral / Codestral | [console.mistral.ai](https://console.mistral.ai) |
| Groq (Llama 3.3) | [console.groq.com](https://console.groq.com) (free tier available) |

Alternatively, copy `.env.example` to `.env` and fill in your keys directly.

**Google Vertex AI** (keyless alternative): authenticate once with `gcloud auth application-default login`, then set `VERTEX_PROJECT` in Settings or `.env`.

---

## Using ASTRA

### Single Cycle mode

Enter a falsifiable scientific claim in the **Intuition Input** box (or upload a PDF/TXT), select providers, and click **Launch Cycle**. ASTRA runs all five phases and returns a report.

### Research Loop mode

Switch to **Research Loop** in the sidebar. Enter a **macro research question** — the overarching question to investigate across many cycles. ASTRA runs depth-first, with the Navigator choosing each next hypothesis based on the previous result.

- **Heartbeat** — number of cycles between human-review pauses (a pause, not a stop).
- **Autonomous Mode** — ASTRA auto-continues at every milestone and stops only when the Navigator declares the macro question resolved.
- **Max runtime** — optional time limit in minutes (empty = unlimited).
- At milestones you can: continue with the Navigator's direction, redirect with your own, or activate a saved parallel branch.

### Investigation management

- **New** (topbar) — saves the current investigation and resets ASTRA for a fresh start.
- **History** — browse, reload, or delete past investigations.

### Runtime budgets, checkpoints, and parallelism

Synchronous `astra_cycle` calls are deadline-aware. Every model/oracle phase is
clamped to the remaining whole-cycle budget, with a final response buffer. If a
complex audit cannot finish inside the client wall, ASTRA returns `PARTIAL`
with the completed conjecture/code, timings, and a checkpoint under
`workspace/cycle_checkpoints/` instead of being killed without a result.

Use `astra_cycle_submit` for a complete long audit and poll its `job_id` with
`astra_job`. The persistent route survives the calling task and waits for the
shared deliberative-cycle slot. `astra_capacity` reports the CPUs visible to the
process and the selected worker policy.

ASTRA separates four meanings that must not be conflated: `job.status` reports
operational completion, `oracle_verdict` reports executable PASS/FAIL,
`atomic_status` reports the bounded conjecture verdict, and `goal_coverage`
reports whether the shared objective itself is complete. When a cycle explicitly
defers broader work, `scientific_status` is `ATOMIC_VALIDATED` or
`ATOMIC_REFUTED`, never whole-goal `VALIDATED`/`REFUTED`.

ASTRA already runs independent proposals, cross-critiques, and evidence
analyses concurrently. Complete cycles are serialized by default because they
share the same Codex, Claude, and AGY subscriptions. Independent local
validators and benchmark cases use an auto-detected safe worker count
(`ASTRA_LOCAL_WORKERS` overrides it); dependent scientific phases remain
ordered.

---

## Validation Engines

Python (always available):

| Package | Used for |
|---|---|
| `sympy` | Symbolic algebra, calculus, identities, residuals |
| `z3-solver` | Satisfiability, inequalities, counterexample search |
| `scipy`, `numpy`, `mpmath` | ODEs, numerical checks, high-precision computation |
| `einsteinpy` | GR metrics, Christoffel symbols, curvature, geodesics |
| `fluids`, `pint` | Fluid mechanics and dimensional consistency |
| `qutip` | Quantum systems, density matrices |

External CAS (optional, via WSL on Windows). Set `ASTRA_WSL_DISTRO` to pin
the intended distribution instead of depending on the machine's WSL default:

```python
# ASTRA_ENGINE: sage      # SageMath
# ASTRA_ENGINE: maxima    # Maxima CAS
# ASTRA_ENGINE: cadabra   # Cadabra (tensor algebra)
# ASTRA_ENGINE: lean4     # Lean 4 + Mathlib (formal proofs)
```

If an optional CAS is missing, the oracle returns a clear failure instead of misclassifying as validated.
Z3 runs as a local Python module. Lean 4 uses either a pinned local
`ASTRA_LOCAL_LEAN4_ROOT`/`ASTRA_LOCAL_LAKE_BIN` environment, a pinned
`ASTRA_LOCAL_LEAN4_WSL_ROOT`/`ASTRA_LOCAL_LEAN4_WSL_LAKE_BIN` environment, or
the configured ASTRUM formal route; merely having an unrelated Lean binary is
not treated as a kernel-ready Mathlib environment.

The production workstation pins Debian/WSL2 and requires Z3, SageMath, Maxima,
Cadabra, and the local Lean 4 route. Recreate that versioned scientific stack
idempotently with:

```powershell
.\scripts\bootstrap_wsl_scientific_stack.ps1
```

`ASTRA_REQUIRED_LOCAL_ENGINES` makes the architecture audit fail closed if one
of those configured engines disappears.

ASTRA can also validate through any installed Python package, including project-specific
research libraries. A generated script may import the package normally, compute independent
checks, print the evidence, and end with `VERDICT: PASS` or `VERDICT: FAIL`.

For Wolfram Language and Mathematica notebooks, an agent can use the optional
the optional `mathematica-agent-bridge` integration alongside
ASTRA. This lets the agent write and execute Wolfram Language, compare expressions,
inspect notebooks, and use Mathematica as an independent cross-validation oracle.

### Bayesian experiment planning

ASTRA includes an optional Gaussian-process planner for expensive numerical or
hybrid symbolic-numerical searches. Symbolic analysis should first derive exact
constraints or reduce the parameter space; the planner then selects informative
numerical evaluations under a fixed budget. GP predictions never replace oracle,
formal, independent, or human validation.

Run the equal-budget symbolic-reduction pilot:

```powershell
.\venv\Scripts\python.exe scripts\run_bayesian_optimization_pilot.py
```

See [BAYESIAN_OPTIMIZATION.md](BAYESIAN_OPTIMIZATION.md) for the reusable API,
scientific acceptance boundary, ASTRUM batch strategy, and cases where a GP is
not appropriate.

When the separate `hollow_core_energy_conditions` project is available, run
the real analytical-project counterexample benchmark:

```powershell
.\venv\Scripts\python.exe scripts\run_hollow_core_bayesian_benchmark.py
```

---

## Example Inputs

### General Relativity

```text
Test whether a static spherically symmetric metric with f(r)=1-2M/r has vanishing Ricci scalar outside r=2M, and produce a symbolic residual that can refute the claim.
```

### Differential Equations

```text
Given y'' + omega^2 y = 0 with y(0)=1 and y'(0)=0, validate that the proposed solution y=cos(omega t) satisfies the equation and boundary conditions.
```

### Fluid Mechanics

```text
For incompressible laminar pipe flow, test whether pressure drop is proportional to viscosity, length, and mean velocity, and inversely proportional to radius squared under the Hagen-Poiseuille assumptions.
```

### Logic / Counterexample Search

```text
Check whether the claim "for all positive real x and y, x + y >= 2 sqrt(x y)" can be refuted by bounded numerical sampling or symbolic inequality reasoning.
```

---

## Benchmark Suite

ASTRA includes a three-track Quality Benchmark for scientific truth,
adversarial validator review, and local–ASTRUM reproducibility. The scientific
seed suite is balanced between validation and refutation; false acceptance is
reported separately as a release-veto metric.

```
benchmarks/
  gr/        ode/       fluids/
  logic/     quantum/   symbolic/
```

List all cases:

```powershell
python scripts\list_benchmarks.py
```

Run the suite:

```powershell
python scripts\run_quality_benchmarks.py --tier smoke --oracle both --jobs 4
python scripts\run_quality_benchmarks.py --tier standard --oracle local
```

Release evaluations can repeat the full architecture and its ablations:

```powershell
python scripts\run_quality_benchmarks.py --tier release --repeats 3 `
  --config full,no-review,no-ensemble --oracle both --jobs 4 --cycle-jobs 1
```

See [QUALITY_BENCHMARKS.md](QUALITY_BENCHMARKS.md) for the metrics, proposed
release gates, private-holdout protocol, external benchmark adapters, and the
safe ASTRUM parallelization strategy. See
[EXTERNAL_BENCHMARKS.md](EXTERNAL_BENCHMARKS.md) for the pinned SciCode,
miniF2F, FrontierScience, and AInsteinBench protocols and evaluator readiness.

The checkpointed public calibration compares the compact architecture with
Codex-only, Claude-only, and agy-only baselines while preserving the same phase
topology and native evaluators:

```powershell
python scripts\run_external_comparison.py
```

The tracked suite manifest is
`benchmarks/external/comparison_calibration_v1.json`; live JSON and Markdown
tables are written after every cell under
`workspace/external_comparison_runs/`.
The older `scripts/run_benchmarks.py` remains available only for
historical-result compatibility.

For an application-oriented client demonstration, ASTRA also ships a minimum
validation package with six cases, deterministic validator routing, Lean 4
formal assurance, a GR_python vertical example, and JSON evidence bundles:

```powershell
python scripts\run_client_validation.py --oracle both --timeout 300
```

The verified seed matrix currently passes 10/10 evidence bundles across six
cases, with full claim-verdict agreement for the four local–ASTRUM pairs.
See [CLIENT_VALIDATION.md](CLIENT_VALIDATION.md) for the evidence contract,
formal-environment pinning, acceptance rule, and commercial scope.

### Long-horizon research quality

The terminal-task suites are complemented by **Research Trajectory Benchmark
v1**. It starts each architecture from one human research objective and measures
the resulting autonomous hypothesis–evidence–revision trajectory. The matched
controls separate heterogeneous perspectives, specialist roles, and the causal
effect of evidence-responsive loops. Automatic metrics cover observable
process, reliability, and cost; architecture-blinded experts separately assess
depth, novelty, usefulness, and causal cross-model uptake.

Inspect the canary schedule without model calls:

```powershell
python scripts\run_research_trajectory_benchmarks.py --dry-run
```

See [RESEARCH_TRAJECTORY_BENCHMARK.md](RESEARCH_TRAJECTORY_BENCHMARK.md) for the
six-program pilot, frozen budgets, graph schema, blinded scorecards, ASTRUM
strategy, and interpretation rules.

The production [Validator Repair vNext.1](VALIDATOR_REPAIR_VNEXT.md) applies
safe deterministic fixes locally, compiles and inspects imports before model
review, and limits Claude to one auditable exact-edit patch instead of a full
validator regeneration. It preserves the distinction between scientific
refutation and operational failure. `full-vnext0` remains available only to
reproduce the first, null-result repair experiment.

Fast release evidence can be reproduced without waiting for a full trajectory:

```powershell
python scripts\benchmark_validator_repair.py --repeats 300
python scripts\run_quality_benchmarks.py --tier smoke `
  --tracks execution --oracle both --jobs 4
```

See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the tested release
state, evidence gates, reproduction commands, and explicit limitations.
The current investor, client and strategic-partner brief is available as
[source](docs/investor/ASTRA_Investor_Brief_EN.tex) and
[PDF](output/pdf/ASTRA_Investor_Brief_EN.pdf).
The measured figures and claim boundaries used by that brief are frozen in the
[26 July 2026 evidence snapshot](docs/evidence/PRODUCTION_SNAPSHOT_20260726.md).

---

## Reading Results

Cycle reports are saved to `workspace/reports/` as HTML and Markdown. The web interface links to each report. When a Research Loop session ends, the reports folder opens automatically.

Status values:

| Status | Meaning |
|---|---|
| `VALIDATED` | The bounded hypothesis was confirmed and the shared objective is fully covered — awaits human approval |
| `ATOMIC_VALIDATED` | The current bounded conjecture passed, but the broader objective still has deferred work |
| `ATOMIC_REFUTED` | The current bounded conjecture failed; this does not by itself refute the broader objective |
| `REFUTED` | Hypothesis disproved — reasoning added to Axiomatic Base |
| `CODE_ERROR` | Validation script failed after retries |
| `API_ERROR` | Provider quota or network error — cycle skipped, retried |
