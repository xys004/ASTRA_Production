# ASTRA Diversity Benchmark v1 — Canary audit log

Date: 2026-07-24

Frozen suite: `diversity_frozen_v1.json`

Frozen suite SHA-256:
`a9b5d43bc6aba4e59359d80b6f5a142c0e2a5ae7c01d64cedd1f05c5a17ee96c`

Checkpoint:
`workspace/external_comparison_runs/external_comparison_20260724_131845.json`

This log distinguishes evaluator/infrastructure debugging from scientific
outcomes. The frozen cases, paired order, hypothesis, metrics, model roles, and
decision rule were not changed after observing canary outcomes.

## Final canary outcomes

| Benchmark | Case | Diverse ASTRA | Homogeneous-proposer control |
|---|---|---:|---:|
| SciCode | `scicode_49_1` | PASS | PASS |
| miniF2F | `minif2f_validation_amc12_2000_p5` | PASS | PASS |
| FrontierScience | `frontierscience_olympiad_af36a1cb-5949-4385-93a0-1f875500c34a` | ABSTAIN | ABSTAIN |
| AInsteinBench | `ainsteinbench_MSB_Qiskit_qiskit_pr14096` | REJECTED | REJECTED |

At four paired cases:

- Both configurations passed 2/4 scored cases (50%).
- Paired pass-rate difference: 0.0.
- Diverse wins / control wins / ties: 0 / 0 / 4.
- Exact one-sided McNemar p-value: 1.0.
- Mean recorded perspective-diversity score: 0.7459 for diverse ASTRA and
  0.5958 for the homogeneous-proposer control.

The canary therefore does **not** support a pass-rate advantage. It does show
the intended manipulation—a larger separation between proposal
perspectives—but the full frozen suite is required to test whether that
difference improves quality.

## Scientific interpretation

The FrontierScience candidates were rejected by ASTRA's independent reviewer
because their proposed validators were self-confirming and lacked independent
experimental evidence. They are scored as scientific abstentions, not
operational failures. Their candidate answers also failed to establish
equivalence to the frozen reference.

On AInsteinBench, the final homogeneous run never produced a complete diff
accepted by the deterministic syntax gate. The diverse run produced an
applicable-format candidate and reached the official image once, but the patch
did not apply to the pinned repository and later repairs were rejected. Both
are therefore non-passes. Reaching executable feedback is retained as a
process difference, not promoted to a quality win.

## Infrastructure incidents and remediation

### Missing official image

The first AInsteinBench pair could inspect neither configuration because the
Qiskit image was absent on ASTRUM. The image was pulled explicitly. Those
inspection errors remain in each cell's `prior_attempts`.

### Reviewer rejection classified as tool failure

An independent-review rejection in the Frontier pilot was initially labelled
`TOOL_ERROR`. The adapter now records a candidate-bearing internal-review
rejection as `ABSTAIN`; API errors, timeouts, missing candidates, and malformed
tool output remain operational errors. Existing canary records were migrated
without rerunning the expensive model calls.

### Repository inspector started outside the repository

The AInstein inspector initially ran from `/home`, while the pinned Qiskit
checkout was `/home/qiskit`. It returned success with zero source snippets.
The inspector now discovers the Git root inside each official image, changes
to that root, and fails closed if no source snippets are found.

### Bounded context omitted the navigator's target file

Broad text hits consumed the context budget before explicit path hints.
Source-file path hints are now prioritized. Test paths, test files, evaluator
scripts, and hidden patch artifacts are excluded. The corrected Qiskit
inspection used commit `ddb802506a499385caf436522b6fb277b51895c1`,
returned source snippets from `qiskit/qpy/binary_io/circuits.py`, and exposed
no test paths.

### Malformed patch text reached the remote evaluator

Narrative text, partial hunks, and trailing Markdown could pass the earlier
shape check. Candidate diffs must now have complete Git headers and hunk
headers and must parse successfully under `git apply --numstat` before any
official-image run.

## Validation and full run

After remediation:

- 41 local tests passed.
- `git diff --check` passed.
- Re-freezing reproduced the exact suite hash above.
- The four official AInsteinBench images selected by the frozen suite were
  prepared on ASTRUM before the full run.

The remaining 72 cells were launched from the same checkpoint with primary
models only. Standard output is recorded in
`workspace/external_comparison_runs/diversity_full_20260724.out.log`; standard
error is recorded beside it with the `.err.log` suffix.
