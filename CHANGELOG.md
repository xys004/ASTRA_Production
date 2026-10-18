# Changelog

The production line of ASTRA is versioned here and in the `VERSION` file at
the checkout root; `core/astra_identity.py` reads that file, so every window
title, banner and report names the version actually running
(`ASTRA 1.1.0 production @<commit> <date>`). Semantic versioning: the first
number changes with the deliberative cycle or the MCP tool contract, the
second with measured capability, the third with fixes. The development line
in `ASTRA-2.0` keeps its own identity through its acceptance gate and is not
covered by this file. Dates are the day the change reached `main`.

## 1.1.23 (2026-10-16)

Effort where it pays, and Luna for the judges of simple claims.

- Recommended Codex ladders drop from ultra/max to high (analyst xhigh):
  on a 14 October benchmark of 16 claims, Sol's ultra reasoning never bought
  a verdict that high did not reach, and
  Luna re-checked every revision without a miss. MAX mode still pins ultra.
- `ASTRA_SIMPLE_CODEX_TIER=1`: when the planner classes a claim simple, the
  reviewer and the analyst run on `ASTRA_REVIEWER_MODELS_SIMPLE` /
  `ASTRA_ANALYST_MODELS_SIMPLE` (default Luna at high, Sol as fallback). The
  conjecture, which runs before the plan, keeps its ladder; MAX mode ignores
  the tier. The result carries `codex_tier`. Off by default.

## 1.1.22 (2026-10-14)

The code author is sized to the problem, and MAX mode stops overthinking.

- Measured on the hard claims of 2026-10-14: the computation itself took 7
  to 26 s, while writing the validator took 900 to 2200 s. Sonnet, first on
  the author ladder, ran out of its 720 s on two of them and Opus then
  started from scratch; in MAX mode Opus at "max" used the full 1800 s
  without producing a script.
- The planner now ends its plan with `COMPLEXITY: simple | moderate | hard`.
  A moderate or hard plan starts the author on `ASTRA_AUTHOR_MODELS_MODERATE`
  / `ASTRA_AUTHOR_MODELS_HARD` (default `claude-opus-5-5@high,sonnet@high`,
  Sonnet only as a quota fallback) with a ceiling of at least
  `ASTRA_TRANSLATOR_TIMEOUT_MODERATE` (1200 s) / `_HARD` (1500 s), still
  bounded by the cycle budget. Simple or unclassified plans keep the
  configured ladder. The result carries `complexity`.
- MAX mode pins the author (and the Claude repairer) to Opus at "high"
  instead of "max", and clears `ASTRA_REVIEWER_FOLLOWUP_MODELS` so a MAX
  cycle never steps the reviewer down.

## 1.1.21 (2026-10-14)

The agreement gate of 1.1.20 asks whether the proposers read the request the
same way, not whether they chose the same method.

- DIFFERENT now means only: different objects, definitions or conventions;
  a different proposition (weaker, stronger or shifted); or a route that
  does not decide the requested proposition (numerical where exact was
  asked, a special case instead of the general one). Two distinct exact
  routes to the same proposition count as SAME, and the merge keeps both as
  legs without dropping the structural derivation in favour of case-by-case
  evaluation. Measured on Tr(sigma_a sigma_b) = 2 delta_ab, where 1.1.20
  answered DIFFERENT only because one proposal evaluated the nine traces and
  the other derived them from the product identity.

## 1.1.20 (2026-10-13)

The conjecture shortcut of 1.1.18 now keeps the cross-critique whenever the
proposers actually disagree.

- On a posed request the synthesizer first states, on one line, whether the
  proposals agree on objects and definitions, on the proposition and on the
  decisive route (`AGREEMENT: SAME` or `AGREEMENT: DIFFERENT - reason`).
  Only SAME skips the critique round; DIFFERENT, or a missing or unreadable
  line, runs the full round and a normal merge. Agreement costs no extra
  call; disagreement costs the gated merge on top of the old round.
- The deliberation trace records `agreement_gate` (verdict and reason), and
  `critique_skipped = "posed_request_agreed"` only when the round was skipped.

## 1.1.19 (2026-10-13)

The progress window uses colour for what the user reads first.

- The current stage is yellow: the model line marked "<- now", the phase
  in "Phase" and its entry in "Phases". The outcome and the new "Claim P"
  line (the verdict on the original claim, `original_claim_verdict`) are
  green when supported or validated, red when refuted or failed, yellow
  otherwise. Causes of failure are red, a model fallback is magenta, the
  progress bar cyan, the objective bold.
- Colour is added only when printing to a console; the views stay plain
  text. `NO_COLOR` or `ASTRA_PROGRESS_COLOR=0` turns it off.

## 1.1.18 (2026-10-13)

The conjecture phase is shorter when the request is already well posed.

- With `ASTRA_CONJECTURE_SKIP_CRITIQUE_WHEN_POSED=1`, a request of at least
  200 characters that carries a line starting with "Claim:" (the form
  AGENTS.md asks for) skips the cross-critique round: both proposers still
  propose and the synthesizer merges both proposals, without the two
  critique calls. The deliberation trace records `critique_skipped`.
  Vague requests keep the full round. Off by default.

## 1.1.17 (2026-10-13)

Codex calls carry less fixed context.

- `ASTRA_CODEX_LEAN=1` starts every Codex call with its agent tools and
  environment notes switched off (`CODEX_LEAN_OVERRIDES` in
  `core/cli_backend.py`): shell, patching, plan, web search, image viewing,
  permission and environment instructions, project docs. ASTRA only asks
  Codex for text. A one-word call went from 17.5k input tokens (5.2k
  uncached) to 10.3k (2.4k uncached). Off by default.

## 1.1.16 (2026-10-13)

Tokens are counted per role, and strong models plan while lighter ones write
and re-check.

- Every answered CLI call records its tokens (input, cached, output,
  reasoning): Codex through `exec --json`, Claude from its JSON `usage`.
  Agy reports none. Results carry `cli_usage` per role plus `total`, and
  each telemetry row carries `tokens`.
- `ASTRA_AUTHOR_SPLIT=1` adds a "plan" phase before code authoring: the
  planner ladder (`ASTRA_PLANNER_MODELS`, contract requires Opus or Fable
  first) writes a numbered validation plan of at most 450 words, which is
  appended to the author's input. The author ladder may then start at
  Sonnet. A failed plan is a warning, not a failed cycle. Off by default.
- `ASTRA_REVIEWER_FOLLOWUP_MODELS`: the second and later model reviews in a
  cycle use this ladder; the first review keeps `ASTRA_REVIEWER_MODELS`.
- The progress window shows the "plan" phase when it runs.

## 1.1.15 (2026-10-13)

The progress window shows which model, at which effort, serves each stage.

- Every heartbeat (`workspace/progress/cycle_<pid>.json`) carries `models`:
  per role, the CLI, the planned `model@effort` (the rung's own effort, or the
  CLI-wide one) and the model that actually answered. With two proposers the
  conjecture lists both.
- `scripts/astra_progress.py --follow` prints a "Models" block under
  "Phases": one line per stage, the current one marked "<- now", and
  "-> answered by ... (fallback)" when a quota or timeout made a lower rung
  answer.

## 1.1.14 (2026-10-13)

Two full cycles may now run at once, so two chats can work without waiting
on each other. The slots already existed: machine-wide locks in
`core/runtime_resources.acquire_cycle_slot`, sized by
`ASTRA_MAX_CONCURRENT_CYCLES`. Only the contract pinned them to one.

- The contract check `deliberative_cycle_serialization` accepts 1 to
  `MAX_SHARED_ACCOUNT_CYCLES` (2) full cycles on one model-account set, and
  still fails above that. A third cycle waits for a slot
  (`wait_for_cycle_slot_seconds`) or returns BUSY, as before.
- Both cycles draw on the same Codex, Claude and Gemini subscriptions, so
  quota burns about twice as fast; each falls back down its own ladder when
  a quota runs out. `.env.example` keeps 1 for collaborators.

## 1.1.13 (2026-10-13)

Merges two changes another session published to the company repository the
same day, on top of 1.1.12. Not measured on the research corpus.

- ASTRUM engine `blender`: headless Blender 4.2.23 LTS (official build,
  SHA-256 checked) under `~/opt`, for renders and animations through the job
  queue (`# ASTRA_ENGINE: blender`). Runs with `-b --factory-startup
  --python-exit-code 1`; managed and ASTRUM-only like `sci` and `pkgs` in the
  client router, the remote worker and the queue (4 CPU slots by default).

- Verdict from legs: `# ASTRA_CERTIFIED: verdict` (pure Python; `arb`
  includes it) loads the vetted `leg`/`run_leg`/`decide()` helper
  (`core/certified/verdict_prelude.py`). FAIL comes only from a decisive leg
  that is False; an undecided decisive leg (exit 5) or a corroborative
  disagreement (exit 6, CORROBORATION_MISMATCH) ends without a verdict, so
  quadrature and sampling can no longer refute an asymptotic claim. The
  verdict guard accepts the helper's FAIL path and flags a decisive leg
  with a literal True; the analyst cannot return VALIDATED or REFUTED on
  UNDECIDED or CORROBORATION_MISMATCH; author rule 8 (the conjecture fence of 1.1.11 becomes rule 9), reviewer rule 11
  audits roles instead of the aggregation. Motivated by three review
  rejections of 9 October for one `all(checks)` mixing proof and sampling.

## 1.1.12 (2026-10-13)

The campaign layer is reconciled with ASTRA 2.0, which is now archived as a
laboratory. Production copied the layer from 2.0 on 22 August (`a40fefd`).
After that, each line changed it separately, in different places, so the
patches applied without conflicts. The layer stays off by default
(`ASTRA_CAMPAIGN_TOOLS`).

- From 2.0 `80f3334`: a closed branch keeps what it learned. Exhausted method
  families carry notes saying why each one closed and the regime where it
  still holds, and the portfolio context passes them to the next proposal.
  Every approximation must state its bound (`ApproximationSpec`).
- From 2.0 `4f0faaa`: the reviewer-declined versus broken distinction moves
  to `core/review_outcome.py`, and the trajectory metrics reuse it. A review
  that refused to certify is not counted as a broken tool.
- From 2.0: campaign trajectory metrics (`core/campaign_trajectory_metrics.py`).
- Kept from production: NON_DECIDABLE in the campaign executor (`7798526`) and
  the job runner that survives a reader holding `job.json` open (`ddffa8d`).

## 1.1.11 (2026-10-13)

The ASTRA 2.0 line stopped on 7 September with twelve cycle-engine fixes that
production never received. A content-level comparison found them
(`docs/architecture/ASTRA2_INVENTORY_20261013.md`). This release ports them,
each with its 2.0 test adapted or a new one. Not measured on the research
corpus, hence a patch release.

- A1. The request and every local oracle capture are decoded as UTF-8: Python,
  CAS, WSL, Lean, SciCode and both SSH transports. Python children run with
  `PYTHONUTF8`. On Windows a `∀` or an accent used to arrive corrupted.
- A2. One retry on the next model rung after a timeout, for every phase,
  sized to what the cycle can still grant. `call_cli` only descended on quota,
  so GPT-6.1 Sol at `ultra` timing out never let GPT-6 Luna answer.
- A3, A4. Lean runs a declared `main`, so a kernel-checked proof prints its
  verdict; the `sorry`/`admit`/`axiom` scan ignores comments. Verified on
  ASTRUM: a valid proof whose comment says "no sorry" printed
  `VERDICT: PASS`, and a false theorem failed.
- A5. The WSL engine probe waits 60 s for a cold boot instead of 10 s, which
  had reported an installed Sage as missing.
- A6. A transient CLI launch failure (WinError 5, sharing violation) is
  retried up to `ASTRA_CLI_LAUNCH_ATTEMPTS` (3); a missing command is
  terminal.
- A7. A failed patch on a WEAK_PASS keeps the validator and finalizes
  WEAK_PASS instead of TOOL_ERROR. A CODE_ERROR without `corrected_code` over
  a clean `VERDICT: PASS` is reconciled to VALIDATED, keeping the raw label
  (never for NON_DECIDABLE).
- A8. Reviewer rules 17-18: the burden is the decisive question, not a
  redundant or stronger companion, and rule 17 never opens the gate.
- A9. The conjecture reaches the validator author inside a
  `<<<CONJECTURE ... CONJECTURE>>>` fence, as data; author rule 9 since 1.1.13.
- A10. Prose is told apart from a broken script (`not_code_at_all`) and
  regenerated from a clean slate. `file://` plan-artifact pointers are
  stripped from CLI answers, and announced. Not ported: 2.0's 58000-token
  Claude thinking cap, sized on the August Opus before `--effort` existed.
- A11. Passing validators complete naturally, without `sys.exit(0)`, which
  Sage reports as a nonzero exit (author contract clause 7).
- A12. Dimensional check (`# ASTRA_UNITS`, `# ASTRA_DIMENSION`, checked with
  pint) in the verdict guard, behind `ASTRA_DIMENSIONAL_GUARD`. The default
  `record` audits without touching the verdict, so it can be measured; `1`
  enforces it as 2.0 did.

## 1.1.10 (2026-10-12)

With 1.1.9 in place, agy answered in seconds from its isolated home, but
inside ASTRA it still returned nothing. On a one-line question, `--mode plan`
(agy 1.3.1) tried a terminal command; headless mode auto-denied it and agy
printed no text. Default mode answers, but it wrote files anywhere on disk in
a test, so it cannot simply replace plan mode.

- An agy home whose `.gemini/antigravity-cli/settings.json` hard-denies every
  tool now runs in default mode. The deny list is `write_file(*)`,
  `read_file(*)`, `command(*)`, `unsandboxed(*)`, `read_url(*)`,
  `execute_url(*)` and `mcp(*)`. With it, the same file-writing prompt was
  refused and a plain question was answered in 15 s.
- Any other home keeps `--mode plan`, so an installation that has not been
  locked down is never given write access.

## 1.1.9 (2026-10-12)

Every model rung can now carry its reasoning effort, so each task gets the
model and the amount of inference it needs. The ladders were checked against
the CLIs on the day: Codex offers GPT-6.1 Sol (effort up to `ultra`), Claude
Code takes `--effort` and runs Fable 5.1, and agy no longer offers any Gemini
Pro. Gemini 3.1 Pro, the first agy rung, had been retired: every agy phase
failed on it at once, and because that is not a quota error the ladder never
fell back. Not measured on the research corpus; adopted for in-house use and
measured as it runs, hence a patch release.

- `model@effort` rungs (`gpt-6.1-sol@ultra`, `claude-fable-5-1@max`,
  `gemini-3.8-flash@high`) for every CLI. The rung's effort wins over the
  CLI-wide variable. An effort the CLI refuses is dropped, never sent. Claude
  Code gets `--effort` for the first time (`ASTRA_CLAUDE_EFFORT` or the
  rung). agy gets `--effort` only when the model id does not already carry
  one, because the CLI refuses both together.
- Contract primaries: `gpt-6.1-sol`, `claude-opus-5-5`, `gemini-3.8-flash`.
  The contract compares model names and ignores the effort.
- MAX mode: GPT-6.1 Sol at `ultra` for every Codex phase, Opus 5.5 at `max`
  for the code author, Gemini 3.8 Flash at `high`. MAX now also pins the
  phase ladders, which otherwise win over the CLI-wide ones.
- In-house production ladders (`.env.example`): every Codex phase at
  `ultra` except review at `max`, writing code on Opus at `high`, with quota
  fallbacks to GPT-6 Luna and Sonnet.
- agy isolation. Run agy for ASTRA from its own home (account registry,
  provider `agy`, `home` = an empty directory such as `~/.agy-astra`; on
  Windows ASTRA sets `USERPROFILE`). From the user's home, agy loads the
  Antigravity IDE's MCP servers, among them ASTRA itself, and waits about two
  minutes for each batch that never connects. One word took 244 s that way and
  9 s from the isolated home, on the same account (the token lives in the OS
  keyring). This is the slowness measured on 30 September (246 s per call)
  that moved production off the ensemble.
- In-house production returns to the `full` profile: Codex and Gemini propose
  together, Codex synthesizes, and Gemini navigates after each cycle.

## 1.1.8 (2026-10-11)

In the last 80 cycles, 27 of the 28 CODE_ERROR results never ran their
validator. All 27 came from one SSH outage to ASTRUM on 7 October: ssh exited
255 during the banner exchange. Each cycle had already paid for conjecture,
translation and review: a median of 265 s per cycle, 2.5 hours in total,
and real quota.
The retry loop then asked the models to repair a validator that had nothing
wrong with it. This release treats an unreachable ASTRUM as an operational
failure.

- Transport retries (`core/remote_transport.py`). A failure before an SSH
  session exists is retried twice, after 10 s and then 30 s, on every ASTRUM
  call. Such a failure is exit 255 with no stdout and a pre-session
  diagnostic (banner exchange, connect timeout or refusal, unresolved host).
  Nothing remote has started at that point, so a retry cannot duplicate a
  job. A connection dropped mid-session is never retried. Configure with
  `ASTRA_REMOTE_TRANSPORT_RETRIES` and `ASTRA_REMOTE_TRANSPORT_BACKOFF`.
- Oracle preflight. A cycle bound for ASTRUM (`oracle='astrum'`) opens one
  SSH session before any model phase. If it fails, the cycle returns
  TOOL_ERROR at phase `oracle_preflight` within seconds, at no quota cost.
  `ASTRA_REMOTE_PREFLIGHT=0` disables it. Local and auto cycles do not probe.
- An outage during execution ends the cycle as TOOL_ERROR at phase `execute`
  with `transport_error`, never as CODE_ERROR. The analyst and the repair
  loop are skipped. The reviewed validator is returned in `code` so it can
  be rerun with `astra_execute` once ASTRUM is back.

## 1.1.7 (2026-10-09)

Two Kondo cycles stopped at review because floats cannot certify complex
logarithm branches or a uniform remainder bound, and the 9 October
benchmark lost two cases that were decided in all but name (an unstated
convention). This release gives validators certified arithmetic, asks the
user which convention was meant, keeps partial evidence on a timeout, and
opens ASTRUM to per-person accounts. Not yet measured on the research
corpus, hence a patch release.

- Certified ball arithmetic: a Python validator that declares
  `# ASTRA_CERTIFIED: arb` gets a vetted python-flint (Arb) prelude
  (`core/certified/`): certified branch index, certain comparisons, rigorous
  sup bounds on polar sectors, declared analytic tails. Anything the balls
  cannot decide raises Undecided, never PASS or FAIL. Author rule 7,
  reviewer rule 11 (vNext rules renumbered 12-16), analyst ANALYTIC_TAIL
  rule; python-flint in `requirements.txt`, optional in the doctor.
- Convention requests: when a decided cycle leaves the claim INCONCLUSIVE or
  SUBSTITUTED only because a convention, assumption or domain is unstated,
  the analyst names the readings and `input_request` (kind `convention`)
  offers one fresh re-run per reading. `status` and
  `original_claim_verdict` never change.
- Timeout recovery: an execution deadline keeps partial stdout and stderr,
  is CODE_ERROR with the claim INCONCLUSIVE, and is never read as a
  counterexample; repair gets recovery instructions, an unchanged validator
  is not rerun, and every attempt is logged in `execution_history`.
- Complete validator code in the reviewer, correction, repair and analyst
  prompts (the 14,000-24,000-character cuts on the script and the 3,500 on
  repair instructions are removed), completing the full-context work of
  1.1.6.
- ASTRUM per-person access: accounts that reach only the job manager,
  identity taken from the SSH account, cancel-own-jobs, per-person quotas,
  `threads_per_process` for MPI jobs, `ssh astrum info`. One-paste Windows
  setup for collaborators and a Windows onboarding guide; public documents
  carry no installation-specific data.
- Meta Muse Code removed (decision of 2026-10-09: the subscription is
  cancelled; ASTRA uses only the Claude, Codex and agy CLIs). Gone: the
  `muse_cli` provider and its WSL bridge, the `muse-trial` profile and its
  overlay and scripts, the Muse entries of max mode and of the doctor. The
  production manifest no longer lists `muse_cli`, so cycle-cache keys change
  once.
- Tests: suite 731 passed, 5 skipped.

## 1.1.6 (2026-10-05)

A source audit (warp, felt-acceleration revision) found that the validator
author, the reviewer and the repairer were not reading the same
specification: the user's claim was cut at 3,500 characters for the author,
the reviewer saw only the conjecture, and both auditors cut their context at
2,000/5,000 characters. A review of the code for the technical reference
found five smaller defects. The first rerun of that source audit with the
fix closed VALIDATED with the claim supported and full coverage.

- Full claim context: the author receives the user's claim block uncapped;
  the reviewer and the bounded repairer receive exactly the author's input
  (objective, claim block, conjecture), prefixed by the inputs policy, with
  no truncation. Tests: `tests/test_full_claim_context.py`; negative control
  `scripts/check_claim_context_negative_control.py` reintroduces the cuts in
  memory and the tests must fail. The control now isolates its lock root
  and workspace like the suite: run beside a production cycle it used to
  hit the machine-wide cycle slot and return BUSY.
- Conjecture rule 7, fixed single claim: a proposition the user states is
  kept with its quantifiers, definitions and constants; supporting estimates
  are proof obligations; if it cannot be decided in one cycle the answer is
  INCONCLUSIVE with the open obligations, never a silent subclaim.
- The analysis phase is no longer started below its 90 s minimum (defined in
  1.1.1, never checked): the cycle returns PARTIAL with the execution
  evidence in its checkpoint, at the first analysis and in retries.
- `production_manifest` gives the `no-ensemble` profile its own role map,
  the one the contract audit expects (it fell back to `full`).
- Codex reasoning effort defaults to `xhigh` on Windows and POSIX when
  `ASTRA_CODEX_REASONING` is unset, matching the contract.
- The reviewer's vNext rules are numbered 11-15 (two rules were numbered
  10); stale comments about a 5,000-character window and a "venv 3.9" core
  are corrected.
- Tests: `tests/test_release_1_1_6.py`; suite 650 passed, 2 skipped.

## 1.1.5 (2026-10-05)

The name keeps its expansion, Autonomous Symbolic Theorem Reasoning
Architecture, and gains the tagline the team asked for: *recursive
inference in cycles*. It names what the cycle already does: inside every
cycle a failed review, a crashed validator or a missing input is fed back as
the input of the next step; in autonomous mode each verdict seeds the next
cycle's hypothesis.

- README, both architecture whitepapers (title page, recompiled PDFs in
  `output/pdf/`) and the process banner carry the expansion and the tagline.
- No behaviour change.

## 1.1.4 (2026-10-02)

Every job runner opened an empty Windows Terminal window, titled with the
venv's `python.exe`, for the whole length of its job. The runners started
with `DETACHED_PROCESS` through the venv's `python.exe`, a launcher whose
child is the real interpreter; a detached launcher has no console, so its
child got a new, visible one. Closing that window killed the runner without
a traceback while its cycle went on. This is what stopped five runners at
once at 15:18 on 2026-10-02.

- The runners of `astra_submit`, `astra_cycle_submit` and the MCP campaign
  step, and the research-trajectory benchmark launcher, start with
  `CREATE_NO_WINDOW` and their own process group (breakaway from the
  caller's job is still tried first). They own a console without a window,
  so there is nothing on screen to close.
- The campaign-step change lives in `mcp_server/server.py` and takes effect
  when an MCP client restarts its server; the other launches change at once.

## 1.1.3 (2026-10-02)

Five persistent-cycle runners were terminated together, with no traceback
(cause not determined), while their cycles went on to finish; three of them
supported the user's claim. Only the runner copies a cycle's result into
`job.json`, so `astra_job` reported all five as `killed`.

- When a cycle's runner is dead, `astra_job` reads the result line the
  cycle printed to `stdout.log`. The job reads `done`, with
  `state_source: stdout.log`, `exit_code: null` (not observable) and the
  full result. The runner's own unpublished state in `job.json.tmp` still
  takes precedence. Nothing is written to the job directory.
- A cycle that outlives its runner reads `running` with
  `runner_alive: false` instead of `killed`, for at most `max_seconds`
  plus 120 s (beyond that a live process id is taken as reused).
- The runner and `astra_job` compute the summary fields with the same code
  (`core/cycle_job_result.py`).

## 1.1.2 (2026-10-02)

A `grep` poll had a job's `job.json` open when the persistent-cycle runner
renamed its heartbeat over it; Windows denied the `os.replace`, the runner
died, and `astra_job` reported the job as `killed` while the cycle went on
to finish VALIDATED with its result only in `stdout.log`.

- The cycle, job and campaign-step runners retry the rename (10 attempts,
  50-200 ms apart). A heartbeat that still fails is logged to `runner.err`
  and the runner carries on; the final save retries for about 10 s
  (`core/atomic_write.py`). The cycle checkpoint retries its rename too.
- When a dead runner's final save could not be published, `astra_job`
  reports the newer state it left in `job.json.tmp`, marked
  `state_source: job.json.tmp`. It never opens the `.tmp` while the runner
  is alive.

## 1.1.1 (2026-10-02)

A cycle launched from Codex with `timeout=900` spent three review rounds on
a normalization the user's text had stated and died before the oracle ran.

- The independent reviewer treats the "USER'S CLAIM AND DEFINITIONS" and
  FROZEN INPUTS blocks as part of the specification: a validator may rely on
  anything stated there without the conjecture restating it.
- A review round, a bounded repair or an analysis is not started when the
  remaining budget would give it less than a realistic call (120 s, 90 s,
  90 s); the cycle returns PARTIAL with its last real source instead of
  launching a call that the budget kills.
- The MCP docstring and AGENTS.md tell agents to keep `timeout` at its
  default and to use `astra_cycle_submit` for long audits.

## 1.1.0 (2026-10-02)

Measured on 50 research claims from live projects: 47 decided correctly, no
false acceptance of 21 false claims, no false refutation of 29 true ones
(`docs/evidence/RESEARCH_CLAIMS_COMPARISON_20260930.md`).

- Verdict re-anchored to the user's claim: `original_claim_verdict`
  (SUPPORTED, REFUTED, INCONCLUSIVE, SUBSTITUTED) travels beside `status`
  and is never collapsed into it; an unparseable analyst reply is asked once
  more and never certifies the claim by default.
- The validator author now receives the user's own claim text, with every
  convention, metric component, operator order and generator it names
  (`build_translation_input`); until then only the proposer and the analyst
  saw it.
- The analyst no longer files a clean refutation as CODE_ERROR: a FAIL from a
  correct script is evidence, float display of an exact value is not a
  defect, and the two verdict axes must agree (one consistency re-ask); a
  repairer that finds no defect no longer kills the cycle.
- Production profile `no-ensemble` (one Codex proposer, Claude Opus author,
  Codex reviewer and analyst, navigation off) with its own contract id;
  `single-model` baseline arm for comparisons.
- Session preflight: a cycle stops before the conjecture when a subscription
  CLI is logged out; the doctor checks CLI versions and sessions.
- Research corpus `benchmarks/quality/research` (v1.2, 50 one-proposition
  cases with measured ground truth and reference scripts); benchmark labels
  REVIEW_REJECTED and BUDGET_EXHAUSTED; cycle budget widened for heavy
  oracle runs.
- Identity: windows and banners name the line, the commit and the profile.
- Model ladders: Codex `gpt-6-luna,gpt-6-astra`, Claude `claude-opus-5-5,sonnet`,
  agy `gemini-3.1-pro-high,...`; doctor requires Codex >= 0.157 and Claude
  Code >= 2.1.280.

## 1.0 (2026-07-22)

First public release of the production line: conjecture, translation,
independent review, oracle execution and analysis over subscription CLIs,
MCP server with 15 tools, local and cluster oracles, deterministic verdict
guard, cycle cache, NON_DECIDABLE with input requests, bounded review loop
with stuck detector. Architecture described in `docs/architecture/`.
