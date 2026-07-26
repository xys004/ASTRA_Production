# ASTRA Diversity Benchmark Protocol v1

Status: frozen before execution on 2026-07-24.

Manifest: `diversity_frozen_v1.json`
Suite SHA-256: `a9b5d43bc6aba4e59359d80b6f5a142c0e2a5ae7c01d64cedd1f05c5a17ee96c`

## Question

Does a heterogeneous pair of initial scientific perspectives improve final,
natively evaluated problem solving when compared with a homogeneous pair under
the same downstream roles and phase topology?

The experiment tests for an advantage; it does not assume one. Cases, order,
metrics, exclusions, and the decision rule are fixed before observing results.

## Matched architectures

| Phase | Heterogeneous ASTRA (`full`) | Matched homogeneous control |
|---|---|---|
| Proposal 1 | Codex | Codex |
| Proposal 2 | AGY/Gemini | Codex |
| Synthesis | Codex | Codex |
| Artifact author | Claude | Claude |
| Independent review | Codex | Codex |
| Repair | Claude | Claude |

The only causal change is the identity of proposal 2. The number and order of
calls, prompts by phase, evaluator, retry limits, and downstream roles remain
matched.

This design complements the broader `codex-only` ablation. That ablation asks
whether the complete specialist team beats a single-model team; it cannot by
itself attribute a difference specifically to diverse initial perspectives.

## Frozen suite

The suite contains 40 public cases and 80 paired cells:

- 12 SciCode development cases from 12 distinct scientific problems, using the
  first subproblem to avoid selecting on later-step dependency complexity.
- 12 miniF2F validation theorems, one from each available theorem-name stratum.
- 12 FrontierScience olympiad cases: 6 physics, 5 chemistry, and 1 biology.
- 4 AInsteinBench repository tasks from four repositories not used during
  calibration.

The four calibration cases are excluded. Selection uses the fixed seed
`ASTRA-diversity-v1-20260724`; every prompt and hidden reference has a recorded
SHA-256 digest. Dataset revisions and their aggregate fingerprint are embedded
in the manifest.

Execution is paired by case. Case order is deterministically shuffled, and
which architecture runs first is balanced exactly 20/20 to reduce temporal,
quota-window, and warm-cache bias.

## Preregistered endpoints

Primary endpoint:

- Paired native `PASS`, using each benchmark's own evaluator.

Primary analysis:

- Pass-rate difference, heterogeneous minus homogeneous.
- Exact paired McNemar test.
- Deterministic 5,000-resample paired bootstrap 95% interval.

Mechanism measurements:

- Unigram and bigram Jaccard distance between the two initial proposals.
- Numeric disagreement when both proposals contain numbers.
- Fraction of proposal vocabulary retained by the synthesis.
- Retention of the less represented proposal.
- Cross-critique count where the pilot exposes critique traces.
- Independent-review intervention rate.
- Repair lift: initial evaluated failure converted to final `PASS`.

Lexical distance is a process measurement, not a quality score. Scientific
quality is determined only by the native evaluator.

## Decision rule

The diversity hypothesis is *supported* only if:

1. the paired pass-rate difference is positive; and
2. the one-sided exact McNemar p-value is below 0.05.

A positive difference without that threshold is reported as directional
evidence. Zero or negative differences are reported as null or adverse
evidence. Cases will not be exchanged after seeing outcomes.

Operational errors, authentication failures, empty CLI output, and timeouts are
reported separately and excluded from scientific pass rates. They remain in
the report as reliability evidence. Model fallback is forbidden in the primary
run.

## Canary and stopping policy

Four frozen canary cases—one per benchmark—run first:

- `scicode_49_1`
- `minif2f_validation_amc12_2000_p5`
- `frontierscience_olympiad_af36a1cb-5949-4385-93a0-1f875500c34a`
- `ainsteinbench_MSB_Qiskit_qiskit_pr14096`

The canary may reveal infrastructure defects, but it cannot change the suite,
hypotheses, metrics, or architecture. Code defects may be fixed transparently;
affected cells must then be rerun and their prior attempts retained.

The full run is stopped only for:

- source fingerprint mismatch;
- evaluator corruption;
- repeated authentication/quota failure that prevents primary-model execution;
- a discovered protocol implementation defect affecting fairness.

## Reproduction

Verify the frozen artifact:

```powershell
.\venv\Scripts\python.exe scripts\freeze_diversity_suite.py
```

Initialize the complete 80-cell checkpoint without executing it:

```powershell
.\venv\Scripts\python.exe scripts\run_external_comparison.py `
  --suite benchmarks\external\diversity_frozen_v1.json `
  --strict-primary-models --dry-run
```

Resume the generated checkpoint with the four canary cases first, then resume
without `--only` for the remaining paired blocks.

## Methodological basis

The generator–verifier–reviser structure follows the scientific workflow
described for [Aletheia and Gemini Deep
Think](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/).
ASTRA's additional hypothesis is that heterogeneous models can contribute
non-identical starting perspectives.

Recent controlled work reports that debate or mixture-of-agents can outperform
self-consistency at equal compute, while also warning that homogeneous debate
can preserve rather than correct errors. See
[Multi-Agent Reasoning Improves Compute
Efficiency](https://arxiv.org/abs/2605.01566) and
[Demystifying Multi-Agent Debate: The Role of Confidence and
Diversity](https://arxiv.org/abs/2601.19921). The matched control and explicit
diversity traces in this protocol are designed around those two claims.
