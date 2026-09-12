# Review-independence ablation, v1

**Status:** pre-registration. Written 2026-09-11, before any arm has been run.
**Stage 1 ran the same day.** Results and the one declared pre-data amendment
are in `REVIEW_INDEPENDENCE_PILOT_20260911.md`. The pilot found the corpus
underpowered for H1b and H1c and revised the corpus plan of section 3.3
upward; the hypotheses, metric and analysis below stand as registered.
**Purpose:** measure the one claim the architecture rests on, so that
`docs/architecture/ASTRA_current_architecture_EN.tex` can replace an argument
from construction with an argument from evidence.

This document fixes the hypotheses, the arms, the metric, the sample size rule,
the analysis, and the discard rules **before** data exists. Anything decided
after seeing results is reported as exploratory and labelled as such.

---

## 1. The claim under test

ASTRA never lets the model that writes a validator be the model that approves
it. The architectural argument for that cost is:

> **H1.** A validator audited by a *different model from a different provider*
> is less likely to reach the oracle carrying a defect than one audited by the
> same model that wrote it.

H1 bundles two effects that are usually confused, so it is split:

> **H1a (second look).** Any independent audit pass beats no model audit.
> **H1b (different weights).** A different model beats the same model re-reading.
> **H1c (different vendor).** A different provider beats a different model from
> the same provider.

H1a is nearly certain and is included as a sanity floor. **H1b and H1c are the
claims that actually justify the production configuration**, and either could
fail. If H1c fails, the honest conclusion is that provider diversity is not
buying safety, only cost, and the architecture section must say so.

### What would falsify the claim

Pre-committed, so the result cannot be reinterpreted afterwards:

- **H1c is refuted** if the cross-provider arm does not exceed the
  same-provider-different-model arm on the primary metric, at the pre-specified
  test and significance level.
- **H1b is refuted** if a fresh call to the *same* model detects defects as
  well as a different model does.
- A finding that any arm rejects sound validators at a materially higher rate
  is reported as a cost of that arm, not omitted.

---

## 2. Arms

One factor is varied, the identity of the reviewer. Everything else is held
fixed: the same case, the same reviewer prompt, the same deterministic
preflight, the same budget.

| Arm | Reviewer | Isolates |
|---|---|---|
| **D** | deterministic preflight only, no model reviewer | floor |
| **S** | same model as the author, fresh call (Claude Opus reviews Claude Opus) | second look |
| **W** | same provider, different model (Claude Sonnet reviews Claude Opus) | different weights |
| **P** | different provider, production configuration (Codex reviews Claude Opus) | different vendor |
| **N** | as P, but with the neutral reviewer prompt of section 6 | prompt bias |

Pairwise tests map to hypotheses as S vs D for H1a, W vs S for H1b, and P vs W
for H1c. Arm N exists only to check that P's advantage is not an artefact of
prompt tuning.

### 2.1 How each arm is actually selected

Four of the five arms need no code at all. The runner already routes the
`validator_audit` track either to a deterministic guard or to a live review,
and reads the reviewer from the environment.

| Arm | Invocation |
|---|---|
| D | `--audit-mode guard` |
| S | `--audit-mode live`, `ASTRA_REVIEWER_PROVIDER=claude_cli`, `ASTRA_CLAUDE_MODELS=claude-opus-4-8` |
| W | `--audit-mode live`, `ASTRA_REVIEWER_PROVIDER=claude_cli`, `ASTRA_CLAUDE_MODELS=sonnet` |
| P | `--audit-mode live`, `ASTRA_REVIEWER_PROVIDER=codex_cli`, `ASTRA_CODEX_MODELS=gpt-5.6-sol` |
| N | as P, plus the neutral-prompt flag of section 6 |

Each ladder is deliberately one rung long, which is the control of section 6,
item 2.
Arm S and arm W differ only in the model rung, which is why the same-provider
comparison is available without touching the role map.

**Note on what "self-review" means here.** ASTRA's reviewer always receives a
fresh call carrying the objective, the conjecture and the code, with no memory
of having authored anything. Arm S is therefore same weights with clean
context, which is the *strongest* form of self-review, not the weakest. If arm S
performs as well as arm P, the case for cross-provider review collapses, and
that is the point of including it.

---

## 3. Corpus

### 3.1 What exists

`benchmarks/quality/validator_audit/adversarial_validators.json` holds 14
labelled cases, each with `objective`, `intuition`, `code`, an `expected`
review outcome, `expected_defects`, and a `severity`.

| Property | Current value |
|---|---|
| Cases | 14 |
| Defective (`expected` REVISE) | 11 |
| Sound (`expected` APPROVED) | 3 |
| Mean validator length | 238 characters |

### 3.2 Why it is not sufficient as it stands

Three problems, in order of how much they threaten the conclusion:

1. **Length.** A real ASTRA validator runs to roughly 200 lines. These average
   238 characters. Spotting a hardcoded pass in a ten-line snippet is a
   different task from spotting one buried in a 200-line script, and it is
   exactly the kind of difference on which reviewers separate. Results on toy
   code do not transfer without an explicit length stratum.
2. **Only 3 sound cases.** False-alarm rate cannot be estimated from 3 trials.
   Without it a reviewer that rejects everything scores a perfect detection
   rate, so the primary metric must be balanced and specificity must be
   measurable.
3. **Seeded defects may be easier than natural ones.** A defect written to be
   an example announces itself. Naturally occurring defects are the target.

### 3.3 Required extension

Target **60 cases**, stratified, keeping the existing 14 inside it:

| Stratum | Cases | Source |
|---|---|---|
| Short defective | 15 | existing corpus plus new, under 40 lines |
| Long defective, seeded | 15 | defects injected into sound validators of 150 to 250 lines |
| Long defective, natural | 10 | validators the reviewer genuinely rejected in production, re-labelled by hand against the recorded reason |
| Sound short | 10 | correct validators, under 40 lines |
| Sound long | 10 | correct validators, 150 to 250 lines |

Defect classes are drawn from the two label sets ASTRA already recognises in
`core/review_defects.py`, covering an assumed bound, an undecidable positivity
claim, a link asserted only in a comment, a proxy substituted for the quantity
of interest, a missing domain restriction, sampling presented as proof, an
unreachable failure branch, unknown treated as pass, a swallowed exception, an
engine mismatch, a wrong tolerance, wrong units, and an unsimplified symbolic
zero. Each defective case carries exactly one primary seeded class so that
attribution can be scored.

**Publishability constraint.** Cases destined for any public artefact are built
from public mathematics and physics only. Natural-defect cases drawn from the
production pool are used for the internal report and are either rewritten onto
public problems or excluded before publication, per `PUBLICATION_POLICY.md`.

---

## 4. Metrics

`core/quality_metrics.py` already computes the four rates this experiment
needs, so no new measurement code is required:

| Metric | Meaning |
|---|---|
| `defect_detection_recall` | fraction of defective validators the arm rejected, the sensitivity |
| `sound_validator_false_alarm_rate` | fraction of sound validators the arm wrongly rejected |
| `defect_label_recall` | fraction of seeded defect labels the arm actually named |
| `critical_defect_recall` | sensitivity restricted to critical severity |

**Primary metric: Youden's J**, defined as sensitivity plus specificity minus
one, with specificity being one minus the false-alarm rate. A single rate is
not admissible as primary, because an arm that rejects everything maximises
sensitivity while being useless.

**Primary comparison: arm P against arm W on J.** Every other comparison is
secondary and reported with its own interval.

`defect_label_recall` carries the qualitative claim and is reported alongside
J. An arm that rejects a defective validator while naming the wrong defect
protected the oracle by accident, and its rejection is counted in sensitivity
but not in attribution. The gap between the two is itself a result.

---

## 5. Design, statistics, and sample size

**Paired design.** Every case passes through every arm, so arms are compared
within case and case difficulty cancels out.

- **Pairwise:** McNemar's exact test on the discordant pairs, for each
  pre-specified comparison.
- **Across arms:** Cochran's Q as an omnibus check before pairwise tests.
- **Intervals:** Wilson score intervals on every rate. Bootstrap over cases for
  the interval on J.
- **Multiplicity:** four pre-specified comparisons, Holm correction, family
  significance 0.05.
- **Repeats:** each case is run `k` times per arm to separate model
  nondeterminism from arm effect. Majority vote is the case outcome; the
  dispersion across repeats is reported, not hidden.

**Sample size is not asserted, it is derived.** A pilot on the existing 14
cases with `k = 3` estimates the discordant-pair rate. The full corpus size is
then set to give 0.8 power at 0.05 for the primary comparison, and the
calculation is recorded before the full run. If the pilot implies more than 120
cases are needed, the honest reading is that the effect is small, and that
conclusion is reported rather than chased with a larger corpus.

---

## 6. Controls and confounds

Each item below has bitten ASTRA before or is a standard failure of this design.

1. **Prompt bias toward the production arm.** The reviewer prompt in
   `agents/reviewer.py` was developed over months *with Codex in that role*, up
   to and including the vNEXT rules. Arm P therefore competes with a prompt
   fitted to it. Uncontrolled, this experiment would measure prompt fit and
   report it as provider independence. **Control:** arm N repeats arm P with a
   neutral prompt carrying only the task and the output contract, with no rule
   tuned on observed Codex behaviour. If P beats W but N does not, the
   advantage is prompt fit, not independence.
2. **Quota fallback contamination.** A ladder that silently descends mid-run
   changes the reviewer inside an arm. **Control:** pin each arm to a single
   model with a one-rung ladder, and discard any case whose record shows a
   fallback rung or a quota warning. Discards are counted and reported.
3. **Cache reuse.** `production_manifest()` includes the reviewer role and
   feeds the cycle cache key, so arms should not collide. **Control:** do not
   rely on it. Disable the cycle cache for the whole experiment and confirm on
   the first two arms that no case returns a cached verdict.
4. **Model drift across the run window.** Providers update models. Running arm
   P to completion and then arm W confounds arm with date. **Control:**
   interleave, cycling arms case by case, and record the resolved model id and
   timestamp on every record.
5. **Order and position effects.** **Control:** randomise case order with a
   recorded seed.
6. **The stuck detector interacts with review.** It is on by default and
   changes how many rounds a defective validator survives. **Control:** it is
   on in every arm that has a reviewer, matching production, and a sensitivity
   check repeats the primary comparison with it off.
7. **Scoring leakage.** **Control:** scoring is mechanical. Outcome comes from
   the recorded review verdict, attribution from `classify_review`, neither
   reads the arm label. No human adjudication enters the primary metric.
8. **Deterministic preflight floor.** Part of what arm D catches is also caught
   by preflight in every other arm. **Control:** report preflight catches
   separately so the model reviewer's marginal contribution is visible rather
   than inflated by the floor.
9. **Length as a giveaway.** Each defective case is a patch of its sound base,
   so the two could differ systematically in size and a reviewer could then
   discriminate on length rather than on mathematics, which would make the
   experiment measure its own construction. **Control:** measured, not assumed.
   At 48 sound and 78 defective cases the best possible classifier that reads
   only the line count scores 62.7% against a majority baseline of 61.9%. That
   edge is one case in a hundred and twenty-six and it is not evidence: the
   statistic is the maximum over every threshold evaluated on the same data, so
   it is biased upward and will sit a case or two above the baseline on pure
   noise. The paired test carries no such bias and is flat, a defective case
   being 2.12 lines shorter on average out of 206, with 28 longer and 36 shorter
   among the 64 unequal pairs, a sign test at p = 0.38. Both are recomputed at
   every corpus extension and again at the final size before stage 3 runs;
   neither has ever been typed by hand.

---

## 7. Execution plan

Staged, so the expensive step is only paid if the cheap one justifies it.

### Stage 0, harness (no model calls)

Most of the harness exists. `scripts/run_quality_benchmarks.py` already serves
the `validator_audit` track, honours `--repeats` and `--only`, routes
`--audit-mode guard` to a deterministic audit that needs no model, sends a live
review through `astra_tool.py action=review` with the provider taken from
`ASTRA_REVIEWER_PROVIDER`, and deposits records under
`workspace/quality_benchmark_runs/`. `core/quality_metrics.py` already computes
the four rates of section 4. What is missing is small:

- an explicit arm label written onto every record, so arms can be aggregated;
- the neutral prompt of arm N behind a flag;
- an analysis script computing J, McNemar, Cochran's Q, Wilson and bootstrap
  intervals from the deposited records.

Nothing in the measurement path has to be invented, which is the main reason
this experiment is worth running now rather than later.

### Stage 1, pilot

14 existing cases, 5 arms, `k = 3`, for 210 audits. Arm D is deterministic and
costs nothing, so the quota cost is **168 model calls**, one per live audit.
A review is a single call rather than a cycle, so this is roughly one to three
hours of wall time and a small fraction of what a cycle benchmark burns. It
yields the effect-size estimate, the discordant-pair rate, the power
calculation, and confirmation that no arm is contaminated.

**Gate.** If the pilot shows arms P and W within noise, the full run is still
worth doing, because a null on H1c is a publishable and actionable result. If
arms S and D are within noise, stop and investigate the harness, because that
would mean the reviewer is not contributing at all.

### Stage 2, corpus extension

Build the 60-case stratified corpus of section 3.3. This is hand work and is
the real cost of the experiment, measured in days rather than quota.

### Stage 3, full run

60 cases, 5 arms, `k` from the power calculation, interleaved and seeded.
At `k = 3` this is 900 audits, of which 720 are model calls. Reported in full,
including discards.

### Stage 4, end-to-end confirmation, conditional

Only if stage 3 shows an effect. Two arms, P and S, on roughly 20 public-corpus
problems run as complete cycles, scoring the final verdict against the official
tests. A cycle costs 20 to 25 minutes, so this is an overnight run on the
cluster and cannot substitute for stage 3. Its role is to show that a detection
difference measured at the review boundary survives to the verdict.

---

## 8. Deposit and reproducibility

Per `feedback_cifras_solo_desde_outputs`, no number reaches a document without a
deposited log.

- Every record keeps arm, case id, seed, repeat index, resolved model id,
  account profile, timestamp, review verdict, observed defect labels, wall
  time, and any quota warning.
- Raw records under `workspace/quality_benchmark_runs/`, which is where the
  runner already writes them, with the aggregate written as JSON alongside.
- The corpus, the analysis script and the aggregate are the reproducible
  artefact. A reader must be able to recompute every reported figure from the
  deposited records without access to ASTRA or to any model.
- The pre-registration is this file at its committed revision. Deviations are
  listed explicitly in the report.

---

## 9. Threats to validity, stated in advance

- **Construct.** Detecting a seeded defect in a fixed validator is a proxy for
  protecting a real cycle. Stage 4 exists because of this gap and does not
  fully close it.
- **External.** Results hold for the defect classes in the corpus. A class
  nobody thought to seed is not measured, and the natural-defect stratum is the
  only partial guard against that.
- **Provider asymmetry.** Codex runs at `xhigh` reasoning and Claude at its own
  default. Equal budget is enforced by call count, not by internal reasoning
  effort, which is not comparable across vendors. This is a real limitation of
  any cross-provider comparison and is stated rather than papered over.
- **Single author model.** Every arm audits validators written by Claude Opus.
  Whether the result holds when another model is the author is untested.
- **Temporal.** Model versions move. The result is dated, and the report says
  so.

---

## 10. What this feeds

On completion, the "Evaluation status" section of the architecture whitepaper
is rewritten from a statement of intent into a measured result, with its
interval and its limitations, in both language versions. If H1c is refuted, the
architecture section is revised to match, and the production configuration is
reconsidered on cost grounds.
