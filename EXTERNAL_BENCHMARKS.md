# ASTRA External Benchmark Protocol

ASTRA's internal quality suite tests scientific truth, validator integrity, and
local–ASTRUM reproducibility. The external suite adds public tasks with their
native evaluators so that future results can be compared with published systems.
It deliberately does not collapse unlike tasks into one misleading score.

## Pinned public corpus

`benchmarks/external/registry.json` fixes every source to an exact commit. The
current audited cache fingerprint is
`6c4f6268fb5de13b1136f2e7f082e92754dded3cfff30c5e13fcaf36b6cfdaf2`.

| Benchmark | ASTRA cases | Native evaluation | Current evaluator state |
|---|---:|---|---|
| [SciCode](https://github.com/scicode-bench/SciCode) | 338 subproblems: 50 development, 288 test | Official HDF5 numerical tests; subproblem and main-problem resolve rates | Ready |
| [miniF2F v1](https://github.com/openai/miniF2F/tree/v1) | 488 theorems: 244 validation, 244 test | Lean 3 compilation; pass@k and refine@k | Ready on ASTRUM |
| [FrontierScience](https://huggingface.co/datasets/openai/frontierscience) | 160: 100 olympiad, 60 research | Answer equivalence for olympiad; official/expert rubric for research | Olympiad ready; research requires blind expert grading |
| [AInsteinBench](https://huggingface.co/datasets/ByteDance-Seed/AInsteinBench) | 244 repository tasks | Per-task OCI image, hidden test patch, resolve rate and points | Ready on ASTRUM; images pulled per task |

The SciCode count applies its official exclusions (`13.6`, `62.1`, `76.3`).
miniF2F uses the benchmark's Lean 3 `v1` branch, not a translated Lean 4 corpus.
With the ASTRUM oracle selected, 1,170 of the 1,230 registered cases have an
executable evaluator. The remaining 60 are FrontierScience Research cases that
intentionally require blind expert grading.

## Reproducible setup

The sources and large evaluator artifacts live in the ignored
`workspace/external_benchmarks/` cache:

```powershell
python scripts\prepare_external_benchmarks.py --download
python scripts\prepare_external_benchmarks.py --download-scicode-tests
python scripts\run_external_benchmarks.py
```

The preparation command will not overwrite an existing checkout at a different
commit. The catalog command verifies pinned commits and dataset counts before
selecting tasks.

ASTRUM's user-space evaluator can be reproduced without `sudo`:

```bash
bash remote/bootstrap_external_benchmarks.sh
```

It installs Lean 3.42.1, mathlib commit `cb2b02f…`, and uDocker 1.3.17
inside the `astrum` user's home. AInsteinBench images are large, so prepare only
the selected task:

```powershell
python scripts\run_external_benchmarks.py --benchmark ainsteinbench `
  --only ainsteinbench_MSB_pyscf_pyscf_pr2373 `
  --prepare-ainstein-image ainsteinbench_MSB_pyscf_pyscf_pr2373 `
  --timeout 3600
```

Useful inspection commands:

```powershell
python scripts\run_external_benchmarks.py --benchmark scicode --split development --list
python scripts\run_external_benchmarks.py --benchmark minif2f --limit 5 --export miniF2F_sample.jsonl
```

## ASTRA execution protocols

### SciCode

The development pilot follows the production role map:

1. Codex and agy independently design the scientific implementation.
2. Codex reconciles the plans.
3. Claude writes the function.
4. Codex audits equations, signature, domains, units, and hidden-target leakage.
5. The function runs against SciCode's official numerical targets.

```powershell
python scripts\run_external_benchmarks.py --benchmark scicode `
  --split development --only scicode_29_1 `
  --pilot-scicode scicode_29_1 --timeout 600
```

Generated code runs in a temporary subprocess with a timeout. Release-scale
evaluation should add an OS/container sandbox because model-generated code is
not intrinsically trusted.

### FrontierScience

The olympiad pilot invokes the full ASTRA cycle and requires an explicit
`FINAL ANSWER:` line. Exact or numerical answers are scored deterministically,
including normalized LaTeX units. Symbolic or rubric-dependent answers are
marked `NEEDS_EXPERT`; they are never guessed correct by a language-model judge.

```powershell
python scripts\run_external_benchmarks.py --benchmark frontierscience `
  --split olympiad `
  --only frontierscience_olympiad_bb0539ef-d9fd-4215-bf16-b0eca44a8778 `
  --pilot-frontier frontierscience_olympiad_bb0539ef-d9fd-4215-bf16-b0eca44a8778 `
  --oracle astrum --timeout 900
```

FrontierScience Research must retain its official expert rubric and blind
grading protocol. A self-judged ASTRA score would not be comparable.

### miniF2F

The model receives the exact theorem statement but not the reference proof.
Codex and agy develop independent strategies, Codex synthesizes them, Claude
writes the Lean 3 proof, and Codex audits it before the pinned compiler decides.
`sorry` and `admit` are rejected before compilation.

```powershell
python scripts\run_external_benchmarks.py --benchmark minif2f `
  --split validation --only minif2f_validation_mathd_algebra_182 `
  --pilot-minif2f minif2f_validation_mathd_algebra_182 `
  --oracle astrum --timeout 600
```

### AInsteinBench

The adapter exposes the public repository issue without its reference patch.
Codex and agy first
choose literal search terms and path hints. A bounded inspector reads only the
base repository inside the official image; it never exposes `/home/test.patch`,
the reference patch, or hidden target values. Claude then writes a patch, Codex
audits it, and the image's official `fix-run.sh` supplies the final verdict.
Claude's built-in tools and inherited MCP configuration are disabled for these
text-only phases, so it can use only the issue and bounded repository context
that ASTRA places in the prompt.

Native Docker could not be installed without an administrator password, and
Ubuntu's AppArmor policy blocks unprivileged namespaces. ASTRUM therefore uses
uDocker's PRoot P2 engine with the official OCI image and test script. The
reference patch for PySCF PR 2373 passes all 4 official tests under this runtime.
This establishes evaluator compatibility for that case, but published results
must disclose the non-native runtime and should be repeated with Docker before
claiming strict leaderboard equivalence.

```powershell
python scripts\run_external_benchmarks.py --benchmark ainsteinbench `
  --only ainsteinbench_MSB_pyscf_pyscf_pr2373 `
  --pilot-ainstein ainsteinbench_MSB_pyscf_pyscf_pr2373 `
  --oracle astrum --timeout 1200
```

## Pilot evidence — 24 July 2026

These are integration pilots, not leaderboard claims:

| Benchmark/case | Outcome | Evidence |
|---|---|---|
| SciCode development `scicode_29_1` | PASS | Codex review `APPROVED`; all 3 official numerical tests passed. Models resolved to `gpt-5.6-sol`, `gemini-3.1-pro-high`, and `claude-opus-4-8`. |
| FrontierScience olympiad `bb0539ef…` | PASS | ASTRA derived `2.31 × 10^6 K`, equal to the official reference; full cycle status `VALIDATED`, total 351.08 s using the ASTRUM oracle. |
| miniF2F validation `mathd_algebra_182` | PASS | Two independent runs produced `by ring`; the pinned Lean 3.42.1/mathlib compiler accepted both on the first compilation attempt. agy exhausted its preferred-model quota in both runs and used its recorded fallback, so these are not maximum-model runs. |
| AInsteinBench evaluator calibration `PySCF PR 2373` | PASS | The reference patch passed 4/4 image-supplied tests and scored 100 resolve points under uDocker PRoot P2. |
| AInsteinBench blind pilot `PySCF PR 2373` | PASS | Codex and agy inspected base commit `df09359…` without the reference patch; Claude's source-only patch was approved by Codex and passed 4/4 official tests on the second attempt for 100 resolve points. The first diff did not apply cleanly, and the normal repair loop corrected it. Models resolved to `gpt-5.6-sol`, `gemini-3.1-pro-high` through agy, and `claude-opus-4-8`. |

The raw local reports are written to
`workspace/external_benchmark_runs/`. They intentionally remain outside Git
because they contain verbose model traces and rapidly growing run history.

## What constitutes a publishable comparison

A defensible result needs the entire official split, fixed prompts and budgets,
declared retries, evaluator versions, failures counted in the denominator,
confidence intervals, and the native metric for each benchmark. Results should
include wall time and model-call counts, plus an equal-budget ablation against
single-model ASTRA configurations. Public development pilots demonstrate that
the plumbing works; they do not establish comparative quality.

ASTRUM can parallelize independent numerical tests, proof compilations, and
containerized repository tasks. Model CLI reasoning should remain concurrency
limited so provider quotas are not mistaken for scientific failure.

## Compact-architecture comparison

The tracked calibration manifest
`benchmarks/external/comparison_calibration_v1.json` selects one pinned public
case from each benchmark family. The checkpointed runner crosses those four
cases with:

- `full`: Codex and agy propose, Codex synthesizes, Claude authors, Codex
  reviews;
- `codex-only`;
- `claude-only`;
- `agy-only`.

The single-agent baselines receive two independent proposals, synthesis,
artifact authoring, review, and the same native evaluator. This equalizes phase
topology and nominal model-call count. It does not claim exact token or dollar
equality because the subscription CLIs do not expose consistent usage telemetry.

agy is the Google agent CLI used by ASTRA, not the retired Gemini CLI. Reports
record both `agy_cli` as the provider and the effective Gemini model selected by
that agent, including any quota fallback.

```powershell
python scripts\run_external_comparison.py

# Maximum-model table: do not permit configured fallbacks
python scripts\run_external_comparison.py --strict-primary-models

# Resume a checkpoint without rerunning completed cells
python scripts\run_external_comparison.py `
  --resume workspace\external_comparison_runs\<run>.json

# Replace only fallback-contaminated cells when primary quota is available
python scripts\run_external_comparison.py `
  --resume workspace\external_comparison_runs\<run>.json `
  --strict-primary-models --rerun-nonprimary
```

The runner writes JSON and Markdown after every cell. Native metrics remain
separate: SciCode numerical tests, miniF2F kernel compilation,
FrontierScience answer equivalence, and AInsteinBench hidden tests/resolve
points. The four-task calibration validates fairness and runtime behavior; the
next comparison tier should contain 40--60 tasks before drawing performance
conclusions.
