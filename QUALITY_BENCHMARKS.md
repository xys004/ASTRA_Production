# ASTRA Quality Benchmark v1

This benchmark measures whether ASTRA produces trustworthy scientific evidence,
not merely plausible prose or a script that prints `PASS`.

## What is measured

The suite has three independent tracks:

1. **Scientific truth (`cycle`)** runs the complete production architecture:
   shared objective, Codex+agy conjecture deliberation, Codex synthesis, Claude
   translation, Codex code review and result analysis, executable oracle, and
   agy research navigation. The public seed set is balanced: 11 claims expected
   `VALIDATED` and 12 expected `REFUTED`.
2. **Validator audit (`validator_audit`)** gives the reviewer deliberately flawed
   and sound programs. Defects include hard-coded success, unreachable failures,
   self-comparison, sampling presented as universal proof, wrong domains or
   tolerances, solver `UNKNOWN` treated as success, swallowed exceptions, and
   missing assumptions.
3. **Execution reproducibility (`execution`)** runs deterministic evidence on
   local and ASTRUM oracles and checks verdict agreement.

The machine-readable case schema and reports live under:

```text
benchmarks/quality/
workspace/quality_benchmark_runs/
```

## Metrics and release vetoes

The runner reports:

- strict and balanced scientific accuracy with a 95% Wilson interval;
- **false acceptance rate**: false claims reported as `VALIDATED`;
- false rejection and operational-failure rates;
- defect-detection, critical-defect, and normalized defect-label recall;
- false alarms on sound validators;
- repeat/oracle agreement and local–ASTRUM execution agreement;
- P50/P95 wall-clock latency and evidence grades.

False acceptance is a veto metric. A high aggregate accuracy cannot compensate
for accepting a false theorem. Proposed initial release gates, to be calibrated
with a larger private holdout, are:

| Gate | Initial target |
|---|---:|
| False acceptance rate | 0 |
| Balanced scientific accuracy | >= 0.85 |
| Critical validator-defect recall | >= 0.95 |
| Sound-validator false-alarm rate | <= 0.10 |
| Operational failure rate | <= 0.05 |
| Repeated/cross-oracle agreement | >= 0.95 |

These are targets, not claims about current ASTRA performance.

## Tiers

```powershell
# Fast infrastructure check; no model calls
python scripts\run_quality_benchmarks.py --tier smoke `
  --tracks execution --oracle both --jobs 4

# Live Codex audit of adversarial and sound validators
python scripts\run_quality_benchmarks.py --tier smoke `
  --tracks validator_audit --audit-mode live --jobs 2

# One pass over the full public suite
python scripts\run_quality_benchmarks.py --tier standard `
  --oracle local --jobs 4 --cycle-jobs 1

# Release-quality repetitions and architecture ablations
python scripts\run_quality_benchmarks.py --tier release --repeats 3 `
  --config full,no-review,no-ensemble --oracle both `
  --jobs 4 --cycle-jobs 1
```

`release` defaults to three repetitions if `--repeats` is omitted. Cycle cache
is disabled automatically, so repetitions are independent observations.

The supported ablations are `full`, `no-review`, `no-ensemble`, `codex-only`,
`claude-only`, and `agy-only`. A fair comparison should publish both:

- an **equal-budget** table with the same cases, repetitions, time limits, and
  allowed retries; and
- a **maximum-quality** table using each architecture's best declared settings.

The report records the Git commit, Python/platform information, configured
providers/models, resolved per-run model details, phase timings, evidence, and
sanitized failures. Subscription CLIs do not expose a reliable per-call dollar
cost, so wall time and call/configuration metadata are the auditable budget
proxies until provider telemetry is available.

For public-benchmark architecture comparisons, the single-agent configurations
receive two independent proposals and the same synthesis/author/review phase
topology as `full`. See `scripts/run_external_comparison.py`. agy is recorded as
the agent provider (`agy_cli`) together with the effective Gemini model selected
by the Google agent.

## ASTRUM acceleration

ASTRUM is currently one Linux workstation with 16 CPU cores / 32 threads and one
RTX 3080, not a multi-node scheduler. The useful split is:

- keep model CLI reasoning and synthesis local, where authentication is already
  configured;
- send independent validation programs, CAS/Z3 jobs, parameter sweeps, PDE
  grids, optimization, and reproducibility checks to ASTRUM;
- use `--jobs 4` initially for CPU/mixed oracle work, increasing only after
  measuring memory and load;
- use `--jobs 1` for separate GPU-saturating programs unless one program itself
  batches the GPU workload;
- keep `--cycle-jobs 1` by default to avoid confusing CLI quotas with scientific
  failures.

The external evaluator catalog currently marks 1,170/1,230 cases executable on
ASTRUM. Lean 3.42.1 with pinned mathlib handles miniF2F, while official
AInsteinBench OCI images run on demand through uDocker PRoot. The 60 deliberately
blocked cases are FrontierScience Research tasks that require blind expert
grading rather than an automated self-judge.

Small jobs can be slower remotely because SSH and interpreter startup dominate.
ASTRUM should be judged on compute-heavy cases and throughput, not a trivial
one-line identity.

## Hidden holdout

Public cases are useful for regression but can be overfit. A release evaluation
should add a private, expert-reviewed holdout with paired true/false variants,
perturbed assumptions, and unseen validator defects:

```powershell
python scripts\run_quality_benchmarks.py --tier release --repeats 3 `
  --case-root C:\secure\astra_holdout --no-legacy `
  --oracle both --jobs 4 --cycle-jobs 1
```

Publish the schema, scoring code, commit, aggregate metrics, and selected
redacted examples; keep the holdout prompts private until the evaluation round
is retired.

## Relationship to external benchmarks

ASTRA's generation–verification–revision loop is closest in spirit to
[Aletheia / Gemini Deep Think](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/),
which combines generation, natural-language verification, revision, tool use,
and human expert grading. Direct score comparisons require running both systems
on the same prompts and expert rubric.

Implemented external adapters are:

- [SciCode](https://arxiv.org/abs/2407.13168) for scientist-curated scientific
  coding problems and official numerical evaluation;
- [miniF2F](https://arxiv.org/abs/2109.00110) for Lean 3 theorem proving;
- [FrontierScience](https://arxiv.org/abs/2601.21165) for olympiad and
  expert-graded research science;
- [AInsteinBench](https://arxiv.org/abs/2512.21373) for repository-level
  scientific agent tasks in pinned Docker environments.

Those datasets must remain separate from the ASTRA-specific adversarial audit:
task-solving ability and validator integrity are related but different claims.
See [EXTERNAL_BENCHMARKS.md](EXTERNAL_BENCHMARKS.md) for pinned sources,
native metrics, setup, evaluator readiness, and pilot evidence.

For a smaller application-facing assurance package, see
[CLIENT_VALIDATION.md](CLIENT_VALIDATION.md). That suite produces per-case
evidence bundles and includes a linked GR_python + Lean 4 demonstration; it is
intended for client pilots rather than leaderboard comparison.
