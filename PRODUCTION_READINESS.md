# ASTRA Production Readiness

Status date: 2026-07-26

## Release state

ASTRA Production enables Validator Repair vNext.1:

```text
ASTRA_VALIDATOR_REPAIR_VNEXT=1
ASTRA_VALIDATOR_REPAIR_STRATEGY=local-patch
ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS=1
```

The release changes repair cost and auditability, not the scientific acceptance
threshold. Deterministic code checks never decide whether a conjecture is true.
They only prevent operational failures or indeterminate predicates from being
misreported as scientific evidence.

## Verified gates

- Production Python 3.9 environment: 66/66 automated tests passed.
- Client-oriented local evidence suite: 5/5 supported cases passed.
- Covered local validators: Z3, SciPy, Pint, SymPy, and GR_python.
- Lean 4 routing, placeholder rejection, and evidence-bundle behavior are
  covered by automated tests.
- `git diff --check` reports no whitespace errors.
- No high-confidence private-key/API-token patterns were found outside ignored
  runtime environments and workspaces.

The local client run is recorded in the ignored runtime report:

```text
workspace/client_validation_runs/client_validation_20260726_061211.json
workspace/client_validation_runs/client_validation_20260726_061211.md
```

## What vNext.1 improves

1. Safe deterministic repairs happen before any model call.
2. Broad exceptions inside legitimate numerical retry helpers are no longer
   rejected merely because the script contains a later `VERDICT: FAIL`.
3. Python compile and import-discoverability facts reach the independent
   reviewer before it speculates about APIs.
4. Claude may return one bounded JSON exact-edit patch; ASTRA rejects ambiguous,
   overlapping, oversized, or whole-script replacements.
5. Scripts above the 24,000-character patch context stop with an explicit
   request to split the scientific obligation instead of consuming another
   long generation.
6. Benchmark metrics separately count deterministic edits, model patch attempts,
   accepted model patches, model review calls, and repair acceptance rate.

## Honest limits

- The frozen vNext.0 trajectory canary produced no conversion uplift over the
  baseline (0% versus 0%). That negative result motivated vNext.1.
- vNext.1 has passed deterministic, integration, and client evidence gates, but
  its comparative research-trajectory canary has not yet completed. No claim of
  scientific-quality or conversion-rate improvement should be made until the
  same frozen cases, seeds, budgets, and oracle are rerun.
- The local client run does not exercise the ASTRUM-only Lean theorem or measure
  cross-oracle agreement.
- A refused patch is an intentional abstention, not a scientific failure.

## Reproduction

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

.\venv\Scripts\python.exe scripts\run_client_validation.py `
  --oracle local --timeout 180

.\venv\Scripts\python.exe scripts\run_research_trajectory_benchmarks.py `
  --tier canary --config full-vnext1 --seeds 11 --max-cycles 2 `
  --oracle local --strict-primary-models
```

For the historical repair implementation, use `full-vnext0`. For a classic
baseline with no structured repair, use `full`.
