# ASTRA Research Trajectory Benchmark v1

## Purpose

The existing ASTRA quality and external suites answer necessary but narrower
questions: whether a final claim is correct, whether a validator is trustworthy,
and whether diverse initial proposals improve native benchmark `PASS` rates.

Research Trajectory v1 tests a different product claim:

> From one human objective and a fixed compute ceiling, can ASTRA sustain a
> deeper, broader, self-correcting, evidence-producing research program than
> matched controls?

The experimental unit is a **research program**, not an isolated question.
Every architecture receives one identical brief. Later cycles are autonomous.

## Construct being measured

A strong research trajectory should:

1. generate materially different, falsifiable hypotheses;
2. choose evidence that discriminates among them;
3. update its direction when evidence changes the plausible frontier;
4. preserve useful alternatives without expanding aimlessly;
5. recover after refutation or implementation failure;
6. produce independently checkable artifacts;
7. advance the shared objective with little human steering.

Longer reasoning alone is not rewarded. A reflective cycle counts as productive
only when it produces credible executable evidence. Scientific depth, novelty,
utility, and causal cross-model uptake are not inferred from word overlap; they
are scored by architecture-blinded experts.

This construct follows the long-horizon direction of
[PaperBench](https://openai.com/index/paperbench/),
[ResearchGym](https://arxiv.org/abs/2602.15112),
[MLGym](https://arxiv.org/abs/2502.14499), and
[LifeSciBench](https://openai.com/index/introducing-life-sci-bench/), while
retaining ASTRA's generation–verification–revision structure inspired by
[Aletheia](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/).

## Matched configurations

| Configuration | Proposal team | Later roles | Direction policy |
|---|---|---|---|
| `full` | Codex + agy | Codex synthesis/review, Claude code, agy navigation | Reflective |
| `homogeneous-proposers` | Codex + Codex | Same as `full` | Reflective |
| `codex-only` | Codex + Codex | Codex in every role | Reflective |
| `full-linear` | Codex + agy | Same as `full` | Frozen, non-reactive |

`full` and `full-linear` make the same phase calls. The linear control still
produces a navigator response, but that response cannot choose the next
direction. Their first cycle starts from the identical complete brief; only
later linear directions are frozen. This isolates the causal value of
evidence-responsive iteration from the value of the role topology itself.

All configurations have the same maximum cycles, wall time, execution timeout,
resources, and one human intervention. These are equal ceilings, not forced
equal expenditure: early resolution is reported as efficiency.

## Public pilot programs

The frozen pilot contains:

- coordinate artifacts versus GR invariants;
- warp-wall shape and exotic-energy Pareto structure;
- counterexample-guided theorem repair with Lean;
- sequential discrimination of growth mechanisms;
- discrimination of partially observed quantum channels;
- failure-driven scientific optimizer repair.

The protocol and its six public briefs are frozen by
`benchmarks/research_trajectory/PROTOCOL_FINGERPRINT_V1.txt`. Every checkpoint
records this SHA-256 value and refuses to resume if the protocol changes.

The cases intentionally mix known references, open model discrimination,
formalization, package use, and computational exploration. They are public
calibration programs. A commercial or publication claim should add a private
holdout with the same schema.

## Measurements

Automatic measurements are restricted to auditable process facts:

| Metric | Operational definition |
|---|---|
| Human prompt efficiency | Credible evidence cycles per human intervention |
| Autonomous loop yield | Credible evidence cycles divided by completed cycles |
| Independent evidence rate | Cycles with multiple check legs or a formal/CAS engine |
| Hypothesis non-repetition | Distinct exact hypothesis records, used only as an anti-loop check |
| Recovery rate | Productive, changed hypothesis immediately after negative evidence or operational failure |
| Branch preservation | Unique explicit alternative branches retained in the graph |
| Traceability proxy | Observable retention of both proposal sources in synthesis; not a causal-quality score |
| Reliability | Operational failures per completed cycle |
| Efficiency | Evidence per observable model call, plus wall time |

Each cell also produces an append-only graph:

```text
objective
   └─ direction
       └─ hypothesis
           └─ executable evidence
               ├─ assessment ── next direction
               └─ preserved alternative branches
```

The graph stores hashes of code and stdout so the trajectory can be audited
without trusting prose summaries.

### Blinded expert dimensions

At least two experts score each completed cell from 0 to 4 on:

- goal advancement;
- hypothesis quality;
- research depth;
- evidence quality;
- self-correction;
- cross-perspective causal uptake;
- novelty and utility;
- artifact reproducibility.

Every case supplies a specific anchor for each dimension. Expert bundles omit
architecture, provider, model, and seed identity. A fatal validity flaw vetoes
the aggregate expert score. Architectures are unblinded only after scorecards
have been completed and validated.

Automatic and expert scores are **never collapsed into one number**. The report
shows a Pareto profile across scientific quality, autonomy, reliability, time,
and model-call cost.

## Run protocol

First verify the frozen schedule without model calls:

```powershell
python scripts\run_research_trajectory_benchmarks.py --dry-run
```

The default is a canary: two programs, one replication seed, four
configurations, and at most three autonomous cycles per cell.

```powershell
python scripts\run_research_trajectory_benchmarks.py `
  --tier canary --oracle local --strict-primary-models
```

The complete pilot is intentionally expensive: six programs, four
configurations, three replication seeds, and up to eight cycles.

```powershell
python scripts\run_research_trajectory_benchmarks.py `
  --tier pilot --oracle auto --strict-primary-models
```

Runs checkpoint after every cycle under:

```text
workspace/research_trajectory_runs/<run_id>/
```

Resume without repeating completed cycles:

```powershell
python scripts\run_research_trajectory_benchmarks.py `
  --tier pilot --resume workspace\research_trajectory_runs\<run_id>\checkpoint.json
```

For a cheaper calibration, select cases, configurations, seeds, or a lower
cycle ceiling:

```powershell
python scripts\run_research_trajectory_benchmarks.py `
  --only gr_invariant_audit,growth_model_discrimination `
  --config full,full-linear --seeds 11 --max-cycles 4
```

## Expert scoring

Give each evaluator only the directory:

```text
cells/<case>/<blind_id>/expert_bundle/
```

Each rater copies `expert_scorecard.json` to a distinct file such as
`expert_scorecard.rater-a.json`, completes every score, adds evidence-node
references, and supplies an anonymous rater id.

After at least two ratings per cell:

```powershell
python scripts\score_research_trajectory_benchmarks.py `
  --checkpoint workspace\research_trajectory_runs\<run_id>\checkpoint.json
```

The scorer validates blinding, score ranges, rater uniqueness, fatal flags, and
minimum rater counts before writing `expert_comparison.json`.

## ASTRUM and external validators

ASTRUM should accelerate parameter sweeps, bootstrap replications, Lean, CAS,
and other evidence jobs. Model cells remain sequential to avoid turning CLI
quota timing into an architectural confound. A trivial validator may be slower
remotely due to SSH startup; the cluster should be used for sufficiently heavy
or parallelizable evidence.

Project packages are declared by portable environment variables rather than
personal filesystem paths:

```text
ASTRA_GR_PYTHON_ROOT
ASTRA_PYWARPFACTORY_ROOT
ASTRA_WARPBUBBLE_OPT_ROOT
ASTRA_MATHEMATICA_BRIDGE_ROOT
ASTRA_LOCAL_LEAN4_ROOT
```

The run record must state when an optional package is unavailable. Silent
replacement with a different validator is not acceptable in the primary
comparison.

## Interpretation

The benchmark can support several distinct conclusions:

- `full` beating `full-linear` supports evidence-responsive reflection.
- `full` beating `homogeneous-proposers` supports heterogeneous perspectives
  under an otherwise matched specialist pipeline.
- `full` beating `codex-only` supports specialist model roles.
- Higher breadth without higher blinded quality indicates frontier expansion
  that was not successfully selected or converted.
- More cycles without higher autonomous loop yield indicates unproductive
  self-reflection.

The prior diversity benchmark remains a valid terminal-task result. Research
Trajectory v1 complements it; it does not reinterpret or discard it.
