# Review-independence ablation, stage 1 pilot

**Run:** 2026-09-11. **Protocol:** `REVIEW_INDEPENDENCE_ABLATION.md`.
**Raw:** `workspace/quality_benchmark_runs/quality_20260911_041514.json` (arm D)
and `quality_20260911_044215.json` (live arms). **Aggregate:**
`ablation_pilot_20260911.json`. **Analysis:** `scripts/analyze_review_ablation.py`.

## Headline

The pilot did not test H1b or H1c. It established that **the existing corpus
cannot test them**, and it measured why with enough precision to size the
corpus that could. That is the outcome a pilot is for, and it is reported as a
null on the design rather than a null on the architecture.

One substantive result did come out of it, and it was not the expected one.
Against blatant defects the identity of the reviewer does not matter at all.
Every model arm caught every defective validator on every repeat.

## What ran

182 audits, 168 of them model calls, across five arms and 14 cases with three
repeats on the live arms. **Zero discards.** No arm fell back to another model
rung, no quota warning appeared, and no call returned an API or tool error, so
the pinning and isolation controls of section 6 held.

## Rates

Intervals are Wilson, except J which is bootstrapped over cases.

| Arm | Sensitivity | Specificity | Youden's J | Defect label recall |
|---|---|---|---|---|
| D deterministic guard | 0.36 [0.15, 0.65] | 1.00 [0.44, 1.00] | +0.36 | 0.17 |
| S same model, fresh context | 1.00 [0.74, 1.00] | 0.33 [0.06, 0.79] | +0.33 | 0.97 |
| W same provider, other model | 1.00 [0.74, 1.00] | 0.67 [0.21, 0.94] | +0.67 | 0.94 |
| P cross-provider, neutral prompt | 1.00 [0.74, 1.00] | 0.67 [0.21, 0.94] | +0.67 | 0.94 |
| P+ cross-provider, shipped prompt | 1.00 [0.74, 1.00] | 0.67 [0.21, 0.94] | +0.67 | 0.97 |

Cochran's Q over the 14 complete cases is 12.95 on 4 degrees of freedom,
p = 0.0115. The arms are not all equivalent, but the omnibus is carried almost
entirely by arm D, which is the sanity floor and was never in doubt.

| Pre-specified comparison | a right, b wrong | b right, a wrong | p | p Holm |
|---|---|---|---|---|
| H1a any audit beats none | 7 | 2 | 0.180 | 0.719 |
| H1b different weights beat re-reading | 2 | 1 | 1.000 | 1.000 |
| H1c different vendor beats same vendor | 1 | 1 | 1.000 | 1.000 |
| prompt identity is worth something | 0 | 0 | 1.000 | 1.000 |

Nothing survives correction. With 14 cases the discordant pairs number one or
two, and no test on one or two pairs can reach any threshold. This is a
statement about the corpus, not about the architecture.

## Why the corpus cannot answer the question

**Sensitivity is saturated.** All four model arms detected 11 of 11 defective
validators, on all three repeats, without exception. A measure on which every
arm scores perfectly carries no information. The defective stratum, which is
eleven of the fourteen cases, contributed nothing to discrimination.

**Specificity is where the arms differ, and it rests on three cases.** Every
difference in the table above comes from the three sound validators. Arm S
wrongly rejected two of three, the other model arms one of three. The intervals
overlap almost completely, and the whole apparent effect is one case changing
hands.

**All the instability is on those same three cases.** Six of the 56 live
case-by-arm cells disagreed across repeats, and every one of them is a sound
validator. Defect detection was not merely correct, it was deterministic.
Whether a correct validator gets approved is the noisy part of the task.

## The finding that is real

Reviewer identity is irrelevant for obvious defects and decisive against the
deterministic floor.

- Every model arm: 11 of 11 defects caught, and the right defect named 94% to
  97% of the time.
- The deterministic guard alone: 4 of 11 caught, right label 17% of the time.

So the model reviewer earns its place, comfortably. What the pilot cannot say
is whether a *different* model earns anything over *the same* model reading its
own output again, because on defects this blatant both are perfect.

A qualitative pattern worth carrying into the full run, stated as an
observation and not a result, is that the arms fail on different sound cases.
Codex rejected the EinsteinPy case on all three repeats while Sonnet approved
it on all three; Sonnet rejected the symbolic-identity case on all three while
Codex mostly approved it. Each reviewer appears to have its own systematic
blind spot rather than a shared difficulty ordering. If that survives a real
corpus it is an argument for diversity that the aggregate rates hide, since
pooled specificity would understate what two disagreeing reviewers catch
together.

**The shipped prompt is worth nothing measurable.** Arms P and P+ differ only
in whether the prompt names the provider, and they produced zero discordant
pairs across 14 cases. The confound that motivated the neutral prompt appears
to be inert, at least at this difficulty. The neutral prompt stays in the
design because absence of an effect on easy cases does not establish absence on
hard ones, but it is no longer the main worry.

## What this implies for the corpus

The pre-registration planned 60 cases with 20 sound. The pilot says that is
underpowered, and says so quantitatively. Sample size needed per paired
comparison, at 0.05 and 80% power:

| True difference | Discordant 0.25 | Discordant 0.35 | Discordant 0.45 |
|---|---|---|---|
| 0.15 | 85 | 120 | 155 |
| 0.20 | 47 | 66 | 86 |
| 0.25 | 29 | 42 | 54 |
| 0.30 | 19 | 28 | 37 |

At the pilot's own point estimate, a specificity gap of 0.33, roughly 23 sound
cases would do. That estimate comes from three cases and is almost certainly
inflated by the winner's curse, so it should not be used. Planning against a
more plausible 0.20 to 0.25 gap puts the requirement at **40 to 66 sound
cases**, against the 20 originally planned.

Two changes follow.

1. **The sound stratum roughly triples**, to about 50 cases, because that is
   where the effect lives.
2. **The defective stratum must be hardened until sensitivity leaves the
   ceiling.** Cases should be built to land arms somewhere near 0.6 to 0.9
   detection rather than 1.0, which means realistic 150 to 250 line validators
   with subtle defects, not ten-line snippets with a hardcoded pass. If a
   hardened stratum still saturates, that is a publishable result on its own:
   independent review is insurance against gross error and nothing more.

Total corpus moves from 60 to roughly 100, and the dominant cost stays the
hand-construction of cases rather than quota.

## Cost actually incurred

168 model calls, about 19 seconds each, four in parallel, roughly 27 minutes of
wall time. No quota exhaustion and no fallback. The full run at the revised
corpus size and three repeats would be on the order of 1200 model calls, some
three to four hours of wall time, which remains modest next to a cycle
benchmark.

## Deviation from the pre-registration, declared

One amendment was made **before** any data was collected, for a reason found
while reading the prompt rather than the results.

The shipped reviewer prompt states "You are Codex" and names Claude as the
author. Running the self-review arm with that text would have instructed Claude
that it is Codex, so a difference between arms would have partly measured that
instruction. The three comparison arms therefore share an identity-neutral
prompt, added as `ASTRA_REVIEWER_PROMPT=neutral`, which removes both provider
names and leaves all nine audit rules, fourteen under vNext, byte for byte
unchanged. Arm N of the original design, "the production arm under a neutral
prompt", became arm P+, "the cross-provider arm under the shipped prompt",
which measures the same confound from the other direction at the same cost.
Production behaviour is unchanged when the variable is absent.

## Status of the hypotheses

| Hypothesis | Verdict after stage 1 |
|---|---|
| H1a any audit beats none | Supported in effect size, not significant. Sensitivity 1.00 against 0.36, label recall 0.95 against 0.17. |
| H1b different weights beat re-reading | Untested. The corpus has no power. |
| H1c different vendor beats same vendor | Untested. The corpus has no power. |
| Prompt identity matters | No measurable effect. Zero discordant pairs. |

Stages 2 and 3 proceed with the revised corpus. Nothing in the architecture
whitepaper changes yet, and its evaluation section continues to say that the
case rests on construction rather than measurement.
