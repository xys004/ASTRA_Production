# ASTRA Production Readiness

Status date: 2026-07-29

Tracked evidence:
[docs/evidence/PRODUCTION_SNAPSHOT_20260726.md](docs/evidence/PRODUCTION_SNAPSHOT_20260726.md)

Bayesian-planning pilot:
[benchmarks/bayesian_optimization/PILOT_V1_RESULT.md](benchmarks/bayesian_optimization/PILOT_V1_RESULT.md)

## Release state

ASTRA Production enables Validator Repair vNext.1 and deadline-aware cycle
orchestration:

```text
ASTRA_VALIDATOR_REPAIR_VNEXT=1
ASTRA_VALIDATOR_REPAIR_STRATEGY=local-patch
ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS=1
ASTRA_MAX_CONCURRENT_CYCLES=1
```

The release changes repair cost and auditability, not the scientific acceptance
threshold. Deterministic code checks never decide whether a conjecture is true.
They only prevent operational failures or indeterminate predicates from being
misreported as scientific evidence.

## Verified gates

- Production Python 3.9 environment: 99/99 automated tests passed.
- Synchronous cycles clamp every phase to the remaining global budget, reserve
  response time, and persist phase checkpoints. Long cycles can run detached
  through `astra_cycle_submit`; a cross-process slot prevents full cycles from
  contending for the same model subscriptions.
- Runtime capacity detection reports 8 estimated physical cores and 16 logical
  CPUs on the production workstation. The default plan uses four independent
  local scientific workers while keeping one deliberative cycle in flight.
- Compact three-agent architecture contract: PASS. The browser UI, MCP and
  subprocess CLI share the same guarded cycle; required roles, primary models,
  Codex `xhigh`, AGY `high`, independent review, navigation and validator
  repair are checked fail-closed by `scripts/audit_architecture.py`.
- Client-oriented local evidence suite: 6/6 supported cases passed, including
  the pinned Lean 4/Mathlib formal case.
- Cross-oracle client replication: 8/8 evidence bundles passed across four
  paired local--ASTRUM cases, with 100% claim-verdict agreement.
- Four-worker execution smoke: 8/8 grade-A local--ASTRUM runs, 100% verdict
  accuracy and agreement, with 5.422 s P50 and 8.598 s P95 latency.
- Validator Repair vNext.1 quick gate: 4/4 targeted source patterns detected
  and safely repaired, 0/3 sound calibration scripts falsely blocked, with
  0.702 ms median and 1.913 ms P95 deterministic repair time over 300 repeats.
- The paired public-benchmark diversity canary produced greater mean proposal
  separation for heterogeneous ASTRA (0.7459 versus 0.5958), while both arms
  passed 2/4 cases. This validates the diversity manipulation, not a quality
  advantage.
- Covered local validators: Z3, SciPy, Pint, SymPy, GR_python, SageMath,
  Maxima, Cadabra, and Lean 4 with Mathlib.
- Current workstation routing audit: Z3 4.16.0 is available as a local Python
  solver; Debian/WSL2 provides SageMath 9.2, Maxima 5.44.0 and Cadabra
  2.3.6.8; Lean 4.30.0 kernel-checks against pinned Mathlib commit
  `c5ea00351…`. These five local routes are required by the production
  architecture audit. ASTRUM remains an independent formal route.
- Lean 4 routing, placeholder rejection, kernel execution, and evidence-bundle
  behavior are covered by automated tests and a local kernel-checked smoke.
- Hybrid Bayesian-planning pilot: exact symbolic reduction passed; all three
  equal-budget methods completed 25 evaluations and passed independent final
  replay. On this frozen synthetic proxy, GP expected improvement reached
  `0.01036579328`, versus `0.05512174007` for seeded random search and
  `0.06333529406` for the uniform grid. This is planner evidence, not a
  scientific-quality or general-superiority claim.
- Real hollow-core analytical-project benchmark: the exact first-mass
  elimination passed, all 75 equal-budget method evaluations were operationally
  valid, and every final source/high-precision replay passed. No local
  counterexample improved the shared analytical incumbent. The GP's best
  distinct challenger was 5.87 times closer than random search and 6.83 times
  closer than the grid, but this is local allocation evidence rather than a
  new physical construction or an optimality theorem.
- `git diff --check` reports no whitespace errors.
- No high-confidence private-key/API-token patterns were found outside ignored
  runtime environments and workspaces.

The local client run is recorded in the ignored runtime report:

```text
workspace/client_validation_runs/client_validation_20260726_061211.json
workspace/client_validation_runs/client_validation_20260726_061211.md
workspace/client_validation_runs/client_validation_20260726_062631.json
workspace/client_validation_runs/client_validation_20260726_062631.md
workspace/quick_evidence/validator_repair_quick_20260726_062852.json
workspace/quick_evidence/validator_repair_quick_20260726_062852.md
workspace/quick_evidence/validator_repair_quick_20260726_065805.json
workspace/quick_evidence/validator_repair_quick_20260726_065805.md
workspace/quality_benchmark_runs/quality_20260726_064413.json
workspace/quality_benchmark_runs/quality_20260726_064413.md
workspace/research_trajectory_runs/research_trajectory_20260726_062455/checkpoint.json
workspace/research_trajectory_runs/research_trajectory_20260726_062455/checkpoint.md
workspace/bayesian_optimization_runs/bayesian_pilot_20260729_144552.json
workspace/bayesian_optimization_runs/bayesian_pilot_20260729_144552.md
workspace/hollow_core_bayesian_runs/hollow_core_bayesian_20260729_150046.json
workspace/hollow_core_bayesian_runs/hollow_core_bayesian_20260729_150046.md
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
7. A dedicated SymPy tensor all-zero helper now canonicalizes exact
   trigonometric identities before deciding whether a component is nonzero.

## Honest limits

- The frozen vNext.0 trajectory canary produced no conversion uplift over the
  baseline (0% versus 0%). That negative result motivated vNext.1.
- The maximum-model vNext.1 one-cell diagnostic completed with a reviewer
  timeout after 1,451 seconds and therefore produced no admitted evidence. An
  explicitly unreviewed ASTRUM diagnostic exposed one symbolic-normalization
  false negative; the new deterministic repair made all 12 validator checks
  pass in 0.476 seconds. This is repair evidence, not scientific acceptance.
- vNext.1 has passed deterministic, integration, client, and cross-oracle
  gates, but its comparative research-trajectory canary has not yet completed.
  No claim of scientific-quality or conversion-rate improvement should be made
  until the same frozen cases, seeds, budgets, and oracle are rerun.
- The four paired local--ASTRUM cases do not exercise the ASTRUM-only Lean
  theorem. Lean routing remains covered by automated tests, not by this paired
  client snapshot.
- The quick repair gate measures only exact deterministic source patterns. It
  is not evidence of scientific-quality improvement; the frozen long-horizon
  canary remains the appropriate conversion test.
- The Bayesian pilot uses one synthetic two-dimensional proxy after exact
  symbolic reduction. Its favorable equal-budget result does not establish
  performance on physics workloads, high-dimensional spaces, proof search, or
  other objective families.
- The hollow-core Bayesian benchmark is confined to `1e-3` compactness
  perturbations around one sign-indefinite, zero-exterior-ADM Israel-shell
  incumbent. Its negative result is not a global bound and does not remove the
  incumbent's strictly negative outer shell.
- A refused patch is an intentional abstention, not a scientific failure.

## Reproduction

```powershell
.\venv\Scripts\python.exe scripts\audit_architecture.py

.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

.\venv\Scripts\python.exe scripts\run_client_validation.py `
  --oracle local --timeout 180

.\venv\Scripts\python.exe scripts\run_client_validation.py `
  --only client_capacity_policy_refutation,client_control_response,client_fluid_pressure_scaling,client_formula_regression `
  --oracle both --timeout 180

.\venv\Scripts\python.exe scripts\benchmark_validator_repair.py --repeats 300

.\venv\Scripts\python.exe scripts\run_research_trajectory_benchmarks.py `
  --tier canary --config full-vnext1 --seeds 11 --max-cycles 2 `
  --oracle local --strict-primary-models
```

For the historical repair implementation, use `full-vnext0`. For a classic
baseline with no structured repair, use `full`.
