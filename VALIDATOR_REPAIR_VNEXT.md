# ASTRA Validator Repair vNext.1

## Why it exists

The first Research Trajectory canary produced two scientifically useful
operational failures before reaching the oracle. Codex correctly refused to
approve validators that:

- allowed an unresolved universal obligation to fall back to representative
  examples;
- converted dependency/API exceptions into `VERDICT: FAIL`;
- interpreted `expr.is_zero is not True` as proof that an expression is nonzero.

The same audit also exposed a reviewer false positive: the installed EinsteinPy
`MetricTensor` accepts coordinate symbols as both a list and a tuple. A reviewer
that does not execute code must not turn an API suspicion into a blocking defect.

vNext.0 did not improve the frozen canary's primary endpoint: both baseline and
vNext.0 converted zero cycles to credible evidence. It did expose the next
bottleneck: two complete model regenerations increased wall time without
clearing the reviewer. vNext.1 addresses that operational result without
weakening the scientific gate.

## Changes

### Deterministic preflight

Before an expensive model review, ASTRA parses and compiles generated Python,
checks import discoverability, and blocks:

- module-level broad exceptions swallowed into a possible scientific `FAIL`;
- indeterminate SymPy `is_zero` predicates treated as nonzero proof;
- syntax errors.

Preflight findings contain a normalized label, severity, line number, and atomic
repair instruction. It never decides whether the conjecture is true.
Expected retry/skip exceptions inside numerical helper functions are not blocked
unless they directly emit or return a scientific verdict. Missing imports become
nonblocking runtime obligations because the selected remote oracle may have a
different package environment.

### Local code repair

Two repair layers are used in order:

1. ASTRA applies only three safe source-local transformations itself:
   `.is_zero is not True` becomes the explicit `.is_zero is False`, and a
   module-level broad exception that can contaminate the verdict is re-raised.
   A raw tensor-entry `== 0` inside a dedicated SymPy all-zero helper is
   canonicalized with `trigsimp(..., method='fu')` before the decision.
2. If the independent reviewer still finds a bounded defect, Claude receives
   the current validator and exact instructions and may return at most eight
   unique exact-snippet replacements in JSON.

ASTRA refuses ambiguous, overlapping, empty, oversized, or whole-script patches.
If a valid local repair is impossible, the cycle stops honestly instead of
spending a second long generation on an unrelated validator.

### Epistemic versus operational outcomes

`VERDICT: FAIL` is reserved for completed mathematical evidence that refutes the
conjecture. Missing engines, exceptions, timeouts, API incompatibilities, and
indeterminate symbolic results must raise or exit nonzero so ASTRA reports an
operational status.

### Reviewer calibration

Codex may list an unverified dependency/API concern under `runtime_checks`, but
may not reject code solely on that speculation. The deterministic preflight or
the oracle decides runtime compatibility.

### Auditable repair ledger

Every review and preflight attempt stores:

- revision number;
- validator SHA-256;
- source (`deterministic_preflight` or `model_reviewer`);
- defect labels;
- repair instructions;
- runtime checks.

vNext.1 additionally stores deterministic and model-patch ledgers with before
and after SHA-256 hashes, exact edit counts, patch source, and rejection reasons.
This supports repair-rate, repeated-defect, and repair-cost measurements.

## Production configuration

The production `.env.example` enables vNext.1:

```text
ASTRA_VALIDATOR_REPAIR_VNEXT=1
ASTRA_VALIDATOR_REPAIR_STRATEGY=local-patch
ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS=1
```

For a frozen classic baseline, set `ASTRA_VALIDATOR_REPAIR_VNEXT=0`. The
research runner exposes the versioned architecture as `full-vnext1`
(`full-vnext` is an alias for the current production version):

```powershell
python scripts\run_research_trajectory_benchmarks.py `
  --tier canary `
  --only gr_invariant_audit `
  --config full-vnext1 `
  --seeds 11 `
  --max-cycles 2 `
  --oracle local `
  --strict-primary-models
```

Do not run vNext.1 concurrently with its baseline comparison. Subscription-CLI
contention and quota timing would become a confound.

## Regression cases

The quality suite permanently includes:

- `audit_regression_operational_error_as_refutation`;
- `audit_regression_indeterminate_is_zero_as_nonzero`;
- `audit_regression_einsteinpy_list_symbols_supported`;
- `audit_regression_unsimplified_symbolic_tensor_zero`.

Their provenance points to the first trajectory canary. The third is a sound-code
case: flagging the list-based EinsteinPy call as an API defect is a reviewer
false alarm.

## Before/after evaluation

The baseline canary must finish unchanged. Then run `full-vnext1` on the same
case, seed, cycle ceiling, oracle, and strict primary models. Report:

- validator conversion rate;
- reviewer block rate;
- repair success after review;
- defect recurrence;
- credible and independent evidence;
- model calls and wall time.

An improvement requires more credible evidence without increased false
acceptance or weaker validator review.
