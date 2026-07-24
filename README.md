# ASTRA

**Autonomous Symbolic Theorem Reasoning Architecture**

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
| Co-conjecture, cross-critique, research navigation | Antigravity `agy` CLI — `gemini-3.1-pro-high` |
| Formal translation and code revision | Claude Code CLI — `claude-opus-4-8` |

ASTRA is designed for theoretical physics, GR, quantum systems, fluid mechanics, symbolic calculus, differential equations, and mathematical model checking.

---

## Windows 11 Installation (Recommended)

No Anaconda or preinstalled packages required — just Python 3.9+ and PowerShell.

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
- Check for Python 3.9+
- Create a local virtual environment (`venv/`)
- Install all Python packages from `requirements.txt`
- Create a desktop shortcut **ASTRA Production** that launches the web interface and opens your browser automatically

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

External CAS (optional, via WSL on Windows):

```python
# ASTRA_ENGINE: sage      # SageMath
# ASTRA_ENGINE: maxima    # Maxima CAS
# ASTRA_ENGINE: cadabra   # Cadabra (tensor algebra)
# ASTRA_ENGINE: lean      # Lean 4 + Mathlib (formal proofs)
```

If an optional CAS is missing, the oracle returns a clear failure instead of misclassifying as validated.

ASTRA can also validate through any installed Python package, including project-specific
research libraries. A generated script may import the package normally, compute independent
checks, print the evidence, and end with `VERDICT: PASS` or `VERDICT: FAIL`.

For Wolfram Language and Mathematica notebooks, an agent can use the optional
[`mathematica-agent-bridge`](https://github.com/xys004/mathematica-agent-bridge) alongside
ASTRA. This lets the agent write and execute Wolfram Language, compare expressions,
inspect notebooks, and use Mathematica as an independent cross-validation oracle.

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

ASTRA includes a golden benchmark suite for calibrating providers and engines.

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
python scripts\run_benchmarks.py
```

---

## Reading Results

Cycle reports are saved to `workspace/reports/` as HTML and Markdown. The web interface links to each report. When a Research Loop session ends, the reports folder opens automatically.

Status values:

| Status | Meaning |
|---|---|
| `VALIDATED` | Hypothesis confirmed by the oracle — awaits human approval |
| `REFUTED` | Hypothesis disproved — reasoning added to Axiomatic Base |
| `CODE_ERROR` | Validation script failed after retries |
| `API_ERROR` | Provider quota or network error — cycle skipped, retried |
