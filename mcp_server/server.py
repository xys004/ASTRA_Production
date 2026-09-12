"""
ASTRA MCP server — expone ASTRA como herramientas para CUALQUIER agente
(Claude Code, Codex, Gemini CLI, Claude Desktop) via Model Context Protocol.

Corre en Python 3.12 (el SDK de MCP necesita >=3.10). Habla con el core de ASTRA
(venv 3.9) por subprocess a traves de astra_tool.py -> versiones desacopladas.

La idea: tu agente favorito se vuelve tu enlace a ASTRA. El agente RAZONA
(conjetura, navega) y llama a estas tools para VERIFICAR con computo real en
ASTRUM (tu RTX 3080) o local.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time

from mcp.server.fastmcp import FastMCP

# --- Paths to the ASTRA core (portable; no user-specific locations) ---
ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_default_core_python = os.path.join(
    ASTRA_ROOT,
    "venv",
    "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python",
)
ASTRA_PY = os.environ.get("ASTRA_CORE_PYTHON", _default_core_python)
if not os.path.exists(ASTRA_PY):
    ASTRA_PY = sys.executable
ASTRA_TOOL = os.path.join(ASTRA_ROOT, "astra_tool.py")

# El host de escritorio lanza este server SIN consola; sin este flag cada hijo
# de consola (python astra_tool.py, taskkill) abre una ventana visible vacia.
# La consola del hijo queda OCULTA (sigue existiendo: los pipes no se ven
# afectados y los nietos nativos conservan stdout).
_NT_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# ASTRA_PROFILE selects the capability bundle this server exposes -- the
# "profile" of docs/architecture/ASTRA_UNIFIED_MCP_RFC.md §6, replacing what
# used to be two independently-defaulted flags (server name, campaign tools).
# Each still has its own explicit env-var override for backward compatibility;
# the profile only changes what they default to when unset. Ported from the
# 2.0 line 2026-08-22 (RFC phase 3): for THIS checkout the heuristic below
# resolves to "production" exactly as the hardcoded FastMCP("astra") did
# before, so this port changes nothing by default.
_VALID_PROFILES = {"production", "campaign", "dev"}


def _resolve_profile(root: str | None = None, env: "os._Environ | dict" = None) -> str:
    root = ASTRA_ROOT if root is None else root
    env = os.environ if env is None else env
    explicit = (env.get("ASTRA_PROFILE") or "").strip().strip("'\"").lower()
    if explicit in _VALID_PROFILES:
        return explicit
    # Default: infer from the checkout, exactly like the pre-profile heuristic.
    return "campaign" if os.path.basename(root).endswith("2.0") else "production"


def _resolve_server_name(profile: str, env: "os._Environ | dict" = None) -> str:
    # The development line runs beside production in the same clients, so it
    # must not introduce itself with production's name: a client listing two
    # servers both called "astra" gives the operator no way to tell which one
    # answered. ASTRA_MCP_SERVER_NAME overrides it for a deliberate promotion.
    env = os.environ if env is None else env
    override = (env.get("ASTRA_MCP_SERVER_NAME") or "").strip()
    return override or ("astra" if profile == "production" else "astra_dev")


PROFILE = _resolve_profile()
MCP_SERVER_NAME = _resolve_server_name(PROFILE)
mcp = FastMCP(MCP_SERVER_NAME)


def _kill_tree(pid: int) -> None:
    """Terminate the ASTRA subprocess tree on Windows, macOS, or Linux."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                creationflags=_NT_NO_WINDOW,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def _read_child_progress(pid: int):
    """Autopsia post-timeout: astra_tool escribe hitos de fase en
    workspace/progress/cycle_<pid>.json; si el kill llego antes del API_ERROR,
    ese archivo dice en QUE FASE estaba el ciclo y cuanto llevaba cada una."""
    try:
        p = os.path.join(ASTRA_ROOT, "workspace", "progress", f"cycle_{pid}.json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["age_s"] = round(max(0.0, time.time() - d.get("ts", 0)), 1)
        return d
    except Exception:
        return None


def _call_astra(req: dict, timeout: int = 300) -> dict:
    """Invoca astra_tool.py (venv 3.9) con una peticion JSON y parsea la respuesta.
    Usa Popen (no run) para conocer el PID del hijo: si hay timeout, se lee su
    archivo de progreso y el error reporta la fase donde murio el ciclo."""
    proc = subprocess.Popen(
        [ASTRA_PY, ASTRA_TOOL],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=ASTRA_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        start_new_session=os.name != "nt",
        creationflags=_NT_NO_WINDOW,
    )
    try:
        out, err = proc.communicate(input=json.dumps(req), timeout=timeout)
    except subprocess.TimeoutExpired:
        pid = proc.pid
        # Kill the full tree so timed-out model children cannot keep consuming
        # quota after the MCP caller has already returned.
        _kill_tree(pid)
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        res = {"error": f"astra_tool timeout tras {timeout}s (proceso matado)"}
        prog = _read_child_progress(pid)
        if prog:
            res["last_progress"] = prog   # fase culpable + timings parciales
            res["hint"] = (f"el ciclo murio en la fase '{prog.get('stage')}' "
                           f"(hace {prog.get('age_s')}s); sube el timeout de la tool "
                           "o revisa esa fase")
        return res
    if proc.returncode != 0:
        return {"error": f"astra_tool exit {proc.returncode}", "stderr": (err or "")[-600:]}
    lines = [l for l in (out or "").strip().splitlines() if l.strip()]
    if not lines:
        return {"error": "astra_tool no devolvio salida", "stderr": (err or "")[-600:]}
    try:
        return json.loads(lines[-1])   # ultima linea = objeto JSON
    except Exception as e:
        return {"error": f"parseo JSON fallo: {e}", "raw": (out or "")[-600:]}


@mcp.tool()
async def astra_execute(code: str, oracle: str = "local", timeout: int = 180) -> str:
    """
    Run a verification script through ASTRA's oracle and return real results.

    Use this to VERIFY a physics/math hypothesis with actual computation instead
    of trusting an LLM's judgment. Write a self-contained script (sympy, einsteinpy,
    z3, scipy, numpy, qutip, pint, in-house packages, or a Sage/Maxima/Cadabra/
    Lean script with an '# ASTRA_ENGINE: ...' marker) that prints its evidence and ends with a line
    'VERDICT: PASS' or 'VERDICT: FAIL'.

    Args:
        code: the full script to execute.
        oracle: where to run it — 'local' (this machine, default),
                'astrum' (remote GPU, opt-in), or 'auto' (the model may tag the code with
                '# ASTRA_ORACLE: remote|local'; otherwise a heuristic sends
                GPU/heavy compute to ASTRUM and light symbolic work to local).
        timeout: seconds before giving up (default 180).

    Returns a JSON string with: stdout, stderr, exit_code, verdict (PASS/FAIL/NONE),
    oracle_used, engine.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {"action": "execute", "code": code, "oracle": oracle, "timeout": timeout},
        timeout=timeout + 60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_client_validate(
    case_id: str = "",
    oracle: str = "auto",
    timeout: int = 300,
) -> str:
    """
    Run ASTRA's minimum application-facing assurance package.

    The validator router sends formal invariants to pinned Lean 4, constraints
    to Z3, symbolic formulas to SymPy, numerical models to SciPy, dimensional
    checks to Pint, and project cases to their scientific package. Every result
    includes an explicit claim verdict, artifact hash, assumptions, limitations,
    structured evidence, provenance and a reproduction command.

    Args:
        case_id: one case ID, a comma-separated list, or empty for all six cases.
        oracle: 'auto', 'local', 'astrum', or 'both'. Unsupported combinations
                are skipped rather than silently rerouted.
        timeout: per-evidence-bundle execution limit in seconds.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {
            "action": "client_validate",
            "case_id": case_id,
            "oracle": oracle,
            "timeout": timeout,
        },
        timeout=min(1740, max(600, timeout * 6 + 60)),
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cycle(intuition: str, oracle: str = "local", timeout: int = 1500,
                exec_timeout: int = 0, objective: str = "", max_mode: bool = False,
                structure_request: bool = False, inputs: str = "",
                input_policy: str = "strict", resume_checkpoint: str = "") -> str:
    """
    Run ASTRA's FULL deliberative multi-model pipeline and return a verdict.

    Codex and agy propose and cross-critique hypotheses against a shared final
    objective; Codex synthesizes the consensus. Claude writes the falsifiable
    validation program, Codex independently reviews it, the selected oracle
    executes it, Codex audits the evidence, and agy proposes the next direction.
    Use astra_execute when YOU wrote the code and only need the oracle.

    Slower than astra_execute. Compact cycles may finish in several minutes;
    adversarial scientific audits commonly require 15-30 minutes.

    Args:
        intuition: the current hypothesis or research direction (LaTeX/plain text ok).
        objective: optional overarching scientific goal shared by all three
            models. When empty, intuition is also used as the final objective.
        oracle: 'local' (default), 'astrum' (opt-in, remote GPU), or 'auto'.
        timeout: seconds for the synchronous WHOLE cycle (default 1500; the
            client wall is tool_timeout_sec=1800 in Codex). ASTRA reserves time
            to return a PARTIAL result and checkpoint instead of being killed.
            For complex audits use astra_cycle_submit, then poll astra_job.
        exec_timeout: seconds for the EXECUTION phase only (0 = .env default,
            usually 180). Raise it for legitimately heavy computation (sweeps,
            GPU runs on ASTRUM) and keep timeout > exec_timeout + 400.
        max_mode: opt-in, one cycle only. Pins every CLI to its TOP model at max
            reasoning with NO fallback to cheaper rungs, raises per-call
            timeouts so the slow top models are not killed mid-thought, and
            runs fresh (no cache). It does NOT extend this synchronous wall, so
            here it stays bounded by `timeout`; for a full MAX run submit it
            (astra_cycle_submit max_mode=True with a large max_seconds). Never
            persists -- reverts on the next cycle unless requested again.
        structure_request: opt-in (C3 of the cycle-robustness spec). A light
            pre-cycle step rewrites the raw intuition into a structured
            single-cycle direction: bounded claim, explicit hypotheses,
            decisive vs auxiliary checks, certification route, REQUIRED INPUTS
            the text does not contain, anti-patterns, deferred items. Use it
            for raw or multi-deliverable requests. The original and the
            structured request come back under `request`.
        inputs: values or frozen contents the user supplies (free text, one
            input per line: `U0 = 0.3`, a pasted table, a material class).
            They reach the conjecture engine and the validator author as an
            authoritative FROZEN INPUTS block.
        input_policy: 'strict' (default: a missing decisive input ends the
            cycle as NON_DECIDABLE with an `input_request` to put to the user)
            or 'assume' (the user approved placeholder values: the validator
            declares each one in an ASSUMED line and proceeds; the result
            carries `assumed_inputs` and the verdict is conditional on them).
        resume_checkpoint: the checkpoint path of the cycle that asked for the
            inputs (from its `input_request`); its conjecture is reused and the
            new run starts at the validator with the inputs in hand.

    When status is NON_DECIDABLE, ASK THE USER the `input_request.question`
    and re-run with the option's `rerun` fields (provide / assume / extract);
    ending without a decision is not the only exit.

    Returns JSON with separate layers: `status`/`atomic_status` for the bounded
    conjecture, `oracle_verdict` for executable PASS/FAIL, `goal_coverage` for
    the shared objective, and `scientific_status` (`VALIDATED` only for complete
    coverage, otherwise `ATOMIC_VALIDATED`/`ATOMIC_REFUTED`). `NON_DECIDABLE`
    means the validator could not be instantiated because decisive inputs are
    absent from the request: `missing_inputs` lists them and the cycle did not
    burn retries on a rewrite; supply them (frozen contents in the request or
    a narrower claim) instead of re-running. It also includes
    shared_goal, deliberation, conjecture, code_review, code, execution,
    analysis, navigation, providers, timings, and 'warnings'/'cli_models' when a
    CLI model hit its usage limit and a fallback served the phase. Internal
    calls use phase-specific caps and are additionally clamped to the remaining
    global budget. Checkpoints preserve completed work.
    """
    req = {
        "action": "cycle",
        "intuition": intuition,
        "oracle": oracle,
        "cycle_timeout_seconds": int(timeout),
        "cycle_return_buffer_seconds": 60,
    }
    if objective.strip():
        req["objective"] = objective.strip()
    if exec_timeout and exec_timeout > 0:
        req["exec_timeout"] = int(exec_timeout)
    if max_mode:
        req["max_mode"] = True
    if structure_request:
        req["structure_request"] = True
    if inputs.strip():
        req["inputs"] = inputs.strip()
    if input_policy.strip().lower() == "assume":
        req["input_policy"] = "assume"
    if resume_checkpoint.strip():
        req["resume_checkpoint"] = resume_checkpoint.strip()
    res = await asyncio.to_thread(_call_astra, req, timeout=timeout)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cycle_submit(
    intuition: str,
    oracle: str = "local",
    max_seconds: int = 7200,
    exec_timeout: int = 0,
    objective: str = "",
    max_mode: bool = False,
    structure_request: bool = False,
    inputs: str = "",
    input_policy: str = "strict",
    resume_checkpoint: str = "",
) -> str:
    """
    Queue a FULL ASTRA deliberative cycle as a persistent background job.

    This is the production route for complex scientific audits. It is not bound
    by the synchronous MCP wall, checkpoints every completed phase, waits for
    the single shared model-account slot, and survives the calling task. Poll
    the returned job_id with astra_job.

    A completed job (`status=done`) is operationally finished. Its scientific
    result must be read from `scientific_status` together with `goal_coverage`;
    an atomic oracle PASS does not certify a broader paper or research program.

    Args:
        intuition: current hypothesis or research direction.
        objective: optional shared final scientific objective.
        oracle: 'local', 'astrum', or 'auto'.
        max_seconds: hard ceiling including queue time; default 7200 (2 hours).
        exec_timeout: execution-phase ceiling; 0 uses ASTRA's configured default.
        max_mode: opt-in, this job only. Pins every CLI to its TOP model at max
            reasoning with NO fallback, raises per-call timeouts so the slow
            top models can finish, and runs fresh (no cache). This is the
            recommended route for MAX: keep max_seconds large (the models are
            slow). Never persists beyond this job.
        structure_request: opt-in (C3). Structure the raw intuition into a
            bounded single-cycle direction before the conjecture phase; the
            original and structured request are kept on the result.
        inputs / input_policy / resume_checkpoint: as in astra_cycle. A job
            that ends NON_DECIDABLE carries `input_request`: ask the user and
            resubmit with the chosen option's `rerun` fields.
    """
    req = {
        "action": "cycle_submit",
        "intuition": intuition,
        "oracle": oracle,
        "max_seconds": int(max_seconds),
    }
    if objective.strip():
        req["objective"] = objective.strip()
    if exec_timeout and exec_timeout > 0:
        req["exec_timeout"] = int(exec_timeout)
    if max_mode:
        req["max_mode"] = True
    if structure_request:
        req["structure_request"] = True
    if inputs.strip():
        req["inputs"] = inputs.strip()
    if input_policy.strip().lower() == "assume":
        req["input_policy"] = "assume"
    if resume_checkpoint.strip():
        req["resume_checkpoint"] = resume_checkpoint.strip()
    res = await asyncio.to_thread(_call_astra, req, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_submit(code: str, oracle: str = "local", max_seconds: int = 86400) -> str:
    """
    Submit a LONG computation as a DETACHED background job; returns immediately.

    Use this instead of astra_execute when the run may exceed ~10 minutes (the
    MCP client's synchronous wall): large parameter sweeps, GPU runs on ASTRUM,
    dense scans. The job survives this session and even a client restart — poll
    it with astra_job(job_id). Make the script print progress lines and end with
    'VERDICT: PASS' or 'VERDICT: FAIL'.

    Args:
        code: full script (same conventions as astra_execute).
        oracle: 'local' (default), 'astrum' (remote GPU — keep this machine
                awake: the runner holds the SSH), or 'auto'.
        max_seconds: hard kill ceiling for the job (default 86400 = 24 h).

    Returns JSON: job_id, runner_pid, oracle, max_seconds.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {"action": "submit", "code": code, "oracle": oracle, "max_seconds": max_seconds},
        timeout=60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_job(job_id: str = "") -> str:
    """
    Poll an async job started with astra_submit or astra_cycle_submit.

    Returns status (queued/running/done/failed/killed), heartbeat age, elapsed
    seconds, a LIVE stdout tail (local python jobs stream their output), and the
    final result (verdict, exit_code, duration_s) once finished. Empty job_id
    lists the 10 most recent jobs. Poll every 1-5 min on long runs; a running
    job with a fresh heartbeat is healthy even if stdout is quiet.
    """
    res = await asyncio.to_thread(_call_astra, {"action": "job", "job_id": job_id}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_capacity() -> str:
    """
    Report local CPU/thread capacity and ASTRA's safe parallelism policy.

    ASTRA detects process-visible logical CPUs, estimates physical cores,
    respects CPU affinity and reports recommended local workers. Independent
    local validators/benchmarks may use those workers; complete deliberative
    cycles remain serialized because they share model subscriptions.
    """
    res = await asyncio.to_thread(_call_astra, {"action": "capacity"}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cluster_submit(
    code: str,
    project: str = "",
    priority: int = 0,
    cpu_slots: int = 0,
    gpu_slots: int = 0,
    memory_mb: int = 0,
    max_seconds: int = 3600,
) -> str:
    """Queue persistent scientific computation on the shared ASTRUM node.

    Unlike a direct remote oracle call, this job is admitted by ASTRUM's central
    CPU/GPU scheduler, is attributed to ASTRA_CLIENT_ID, and continues if the
    laptop, agent, SSH session, or local MCP server disconnects. Poll the
    returned job_id with astra_cluster_job.

    Args:
        code: self-contained validation/calculation script. ASTRA_ENGINE markers
            route Sage, Maxima, Cadabra, Lean, sci, and company-package jobs.
        project: optional project/audit label; ASTRA_PROJECT_ID is the default.
        priority: -10..10. Keep 0 for normal work; use positive values only for
            genuinely interactive or urgent validation.
        cpu_slots: requested logical CPU slots; 0 selects an engine-aware default.
        gpu_slots: requested GPU slots; 0 auto-detects common CUDA/JAX/CuPy use.
        memory_mb: hard scheduler reservation; 0 leaves it unspecified.
        max_seconds: execution timeout after the job starts.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {
            "action": "cluster_submit",
            "code": code,
            "project": project,
            "priority": int(priority),
            "cpu_slots": int(cpu_slots),
            "gpu_slots": int(gpu_slots),
            "memory_mb": int(memory_mb),
            "max_seconds": int(max_seconds),
        },
        timeout=60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cluster_job(
    job_id: str = "",
    client_filter: str = "",
    limit: int = 20,
) -> str:
    """Poll one shared ASTRUM job or list the central multi-client queue.

    Empty job_id lists recent jobs from Nelson, Gabriel, and any future clients.
    Set client_filter to one ASTRA_CLIENT_ID to narrow the list. Completed jobs
    include their result, evidence tails, resource claims, attribution, events,
    and artifact directory.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {
            "action": "cluster_job",
            "job_id": job_id,
            "client_filter": client_filter,
            "limit": int(limit),
        },
        timeout=60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cluster_cancel(job_id: str) -> str:
    """Cancel a queued/running ASTRUM job and record who requested it."""
    res = await asyncio.to_thread(
        _call_astra,
        {"action": "cluster_cancel", "job_id": job_id},
        timeout=60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_cluster_capacity() -> str:
    """Report ASTRUM's shared CPU/GPU slots, usage, queue depth, and reserve."""
    res = await asyncio.to_thread(_call_astra, {"action": "cluster_capacity"}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


def _pid_alive(pid) -> bool:
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, TypeError, ValueError):
            return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFO
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


@mcp.tool()
def astra_probe() -> str:
    """
    PROBE — see what ASTRA is doing RIGHT NOW without disturbing it.

    Reads the per-phase heartbeat files every cycle writes (workspace/progress/)
    plus process liveness. Use it whenever a cycle seems slow BEFORE assuming a
    hang: most model phases take 30-240s, while translation/repair may take up
    to its larger configured cap. Zero cost, instant, safe to poll every ~60s.

    Returns JSON: in_flight (pid, stage, seconds since last heartbeat, partial
    timings), recent (finished/killed cycles with final stage), and a hint.
    """
    import glob
    if ASTRA_ROOT not in sys.path:
        sys.path.insert(0, ASTRA_ROOT)
    # Pure-stdlib helper shared with scripts/astra_progress.py: single source of
    # truth for terminal classification and checkpoint enrichment.
    from core import cycle_telemetry as ct
    in_flight, recent = [], []
    for f in sorted(glob.glob(os.path.join(ASTRA_ROOT, "workspace", "progress", "cycle_*.json")),
                    key=os.path.getmtime, reverse=True)[:12]:
        d = ct.load_json(f)
        if not d:
            continue
        d = ct.enrich_progress(d, _pid_alive(d.get("pid", -1)))
        # state: 'running' | 'finished' (clean terminal) | 'killed' (died before
        # a terminal stage) | 'exited' (clean BUSY/cache-hit return after
        # 'queued', no verdict). Live review round / budget come from the
        # heartbeat itself; the finer outcome (e.g. tool_error@reviewer) and
        # the stop cause come from the linked checkpoint.
        (in_flight if d["state"] == "running" else recent).append(d)
    if in_flight:
        top = in_flight[0]
        hint = (f"ASTRA esta TRABAJANDO: fase '{top.get('stage')}' (heartbeat hace "
                f"{top.get('age_s')}s; ronda de revision {top.get('review_rounds', 0)}; "
                f"presupuesto restante {top.get('budget_remaining_s', '?')}s). "
                "Traduccion/reparacion puede usar un presupuesto mayor que otras fases. "
                "Sondea de nuevo en ~60s antes de asumir cuelgue.")
    elif recent:
        last = recent[0]
        if last["state"] == "finished":
            hint = (f"No hay ciclos en vuelo. El ultimo TERMINO limpio con outcome "
                    f"'{last.get('outcome', last.get('stage'))}' "
                    f"({last.get('review_rounds', 0)} rondas de revision; causa: "
                    f"{last.get('stop_cause', '-')}).")
        elif last["state"] == "exited":
            # Ambiguous from the heartbeat alone: astra_cycle_submit waits for a
            # slot up to max_seconds and the job runner kills astra_tool at that
            # same ceiling, so a slot that never frees can ALSO die at 'queued'
            # -- indistinguishable here from the ordinary clean BUSY/cache-hit
            # return. Do not assert either as fact; check the submit job's own
            # result.json (astra_job) for a real TIMEOUT if this looks wrong.
            hint = (f"No hay ciclos en vuelo. El ultimo salio de 'queued' sin heartbeat "
                    "terminal: puede ser un retorno limpio (BUSY por slot ocupado, o "
                    "acierto de cache) o, si vino de astra_cycle_submit, un kill del "
                    "runner al agotar su propio limite mientras esperaba turno -- "
                    "ambiguo desde aqui; revisa astra_job si el slot parecia atascado.")
        else:
            hint = (f"No hay ciclos en vuelo. El ultimo MURIO en fase '{last.get('stage')}' "
                    "sin llegar a un estado terminal (probable kill por timeout externo).")
    else:
        hint = "Sin rastros de ciclos (directorio de progreso vacio)."
    return json.dumps({"in_flight": in_flight, "recent": recent[:5], "hint": hint},
                      indent=2, ensure_ascii=False)


@mcp.tool()
def astra_telemetry(limit: int = 30) -> str:
    """
    TELEMETRY — per-cycle timings, per GOAL how many cycles it took to resolve.

    Aggregates the checkpoints every cycle writes (workspace/cycle_checkpoints/):
    one row per cycle (outcome, review rounds, total and per-phase seconds, stop
    cause, budget, whether the strict-translator overlay produced it) plus
    aggregates under `summary` (cycles, finished vs incomplete, decisive cycles,
    mean/median duration, total review rounds, and `per_goal`: for each distinct
    objective, cycles consumed, cycles_to_decisive once it first reaches
    VALIDATED/REFUTED, and whether it has). `limit` caps how many recent cycles
    are included; `summary.window` reports the total checkpoints on disk versus
    `limit`, so a `truncated: true` flags that an older goal's earlier attempts
    may be undercounted -- raise `limit` to see full history. Read-only and
    instant. Pair with astra_probe for the live view.
    """
    if ASTRA_ROOT not in sys.path:
        sys.path.insert(0, ASTRA_ROOT)
    from core import cycle_telemetry as ct
    ckpt_dir = os.path.join(ASTRA_ROOT, "workspace", "cycle_checkpoints")
    window = max(1, int(limit))
    rows = ct.list_checkpoints(ckpt_dir, limit=window)
    summary = ct.summarize(rows)
    total = ct.count_checkpoint_files(ckpt_dir)
    summary["window"] = {"limit": window, "total_checkpoints": total, "truncated": total > window}
    return json.dumps({"cycles": rows, "summary": summary},
                      indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_status() -> str:
    """
    Health check for ASTRA: confirms whether ASTRUM (the remote GPU workstation)
    is reachable right now and reports its hostname. Call this before a heavy run.
    """
    res = await asyncio.to_thread(
        _call_astra,
        {"action": "execute",
         "code": "import platform; print('HOST', platform.node()); print('VERDICT: PASS')",
         "oracle": "astrum", "timeout": 30},
        timeout=60,
    )
    return json.dumps({
        "astrum_reachable": res.get("verdict") == "PASS",
        "astrum_host": (res.get("stdout") or "").replace("VERDICT: PASS", "").strip(),
        "raw": res,
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def astra_engines() -> str:
    """
    List ASTRUM's authoritative scientific-engine registry.

    Use this instead of PATH discovery. It reports the managed oracle, sci,
    SageMath, Cadabra, Maxima, Lean, and company-package (`pkgs`) environments.
    """
    res = await asyncio.to_thread(_call_astra, {"action": "engines"}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ASTRA 2.0 campaign tools — OFF BY DEFAULT ON THIS (production) CHECKOUT.
#
# `ASTRA2_ACCEPTANCE.md` forbids exposing these through the PRODUCTION MCP
# before promotion (G3-G6, still PENDING). They register only when the
# resolved profile/server name says so; on a bare production checkout with no
# env vars set that is always false (see the EndToEndEquivalenceTests-style
# invariant test in tests/test_mcp_server_profile.py, ported alongside this).
# ASTRA_CAMPAIGN_TOOLS=0 disables them regardless of profile; ASTRA_PROFILE
# must be explicitly set to "campaign" or "dev" (or ASTRA_CAMPAIGN_TOOLS=1) to
# turn them on here. Ported from the ASTRA-2.0 development line 2026-08-22
# (RFC phase 3, docs/architecture/ASTRA_UNIFIED_MCP_RFC.md); verbatim except
# for this header. The underlying campaign_executor falls back gracefully
# (no crash) if the cycle it drives does not emit the 2.0 line's structured
# portfolio, which this checkout's astra_tool.py does not -- that enhancement
# was deliberately NOT ported here; see HANDOFF entry for this phase.
# ---------------------------------------------------------------------------

def _campaign_tools_enabled_for(server_name: str, env: "os._Environ | dict" = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("ASTRA_CAMPAIGN_TOOLS") or "").strip().strip("'\"")
    if flag:
        return flag.lower() in {"1", "true", "on", "yes"}
    # Keyed off the resolved server NAME, not the profile directly: renaming to
    # "astra" (the documented promotion override) must keep disabling campaign
    # tools even if ASTRA_PROFILE alone would say otherwise, so a promoted
    # checkout cannot advertise them by omission.
    return server_name != "astra"


def _campaign_tools_enabled() -> bool:
    return _campaign_tools_enabled_for(MCP_SERVER_NAME)


def _campaign_api():
    sys.path.insert(0, ASTRA_ROOT) if ASTRA_ROOT not in sys.path else None
    from core import campaign_api

    return campaign_api


def _campaign_result(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _submit_campaign_step_job(
    campaign_id: str,
    root: str | None,
    max_seconds: int,
    cycle_timeout_seconds: int | None,
) -> dict:
    """Launch one campaign step as a DETACHED process; return instantly with a
    job_id pollable via astra_job. Mirrors astra_tool.py's _do_submit_cycle
    detached-process pattern, but runs under THIS server's own interpreter:
    campaign_api is 3.12-native here (see _campaign_api above), unlike the
    other *_submit tools, which cross into the venv-3.9 astra_tool.py dispatch.
    Writes into the same workspace/jobs/<job_id>/job.json schema astra_tool.py
    already reads, so astra_job polls it without any change on that side."""
    import uuid

    job_id = time.strftime("campaign_step_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    jobdir = os.path.join(ASTRA_ROOT, "workspace", "jobs", job_id)
    os.makedirs(jobdir, exist_ok=True)
    request = {
        "campaign_id": campaign_id,
        "root": root,
        "cycle_timeout_seconds": cycle_timeout_seconds,
    }
    with open(os.path.join(jobdir, "request.json"), "w", encoding="utf-8") as f:
        json.dump(request, f, ensure_ascii=False, indent=2)
    meta = {
        "id": job_id,
        "kind": "campaign_step",
        "status": "queued",
        "campaign_id": campaign_id,
        "max_seconds": max_seconds,
        "created_ts": time.time(),
        "ts": time.time(),
    }
    with open(os.path.join(jobdir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)

    runner = os.path.join(ASTRA_ROOT, "astra_campaign_step_job_runner.py")
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (+ BREAKAWAY_FROM_JOB first,
    # falling back without it): same Windows-only convention _do_submit_cycle
    # already uses; not a new platform gap.
    flags = 0x00000008 | 0x00000200
    runner_err = open(os.path.join(jobdir, "runner.err"), "w")
    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=runner_err,
        cwd=ASTRA_ROOT,
        close_fds=True,
    )
    try:
        try:
            process = subprocess.Popen(
                [sys.executable, runner, jobdir],
                creationflags=flags | 0x01000000,
                **kwargs,
            )
        except OSError:
            process = subprocess.Popen(
                [sys.executable, runner, jobdir], creationflags=flags, **kwargs
            )
    finally:
        runner_err.close()
    return {
        "job_id": job_id,
        "kind": "campaign_step",
        "runner_pid": process.pid,
        "campaign_id": campaign_id,
        "max_seconds": max_seconds,
        "poll_with": "astra_job",
    }


if _campaign_tools_enabled():

    @mcp.tool()
    async def astra_campaign_start(
        objective: str,
        success_definition: str,
        deliverables: list[str],
        budget_cycles: int = 6,
        budget_model_calls: int = 72,
        budget_wall_seconds: int = 21600,
        budget_execution_seconds: int = 3600,
        allowed_evidence_classes: list[str] | None = None,
        initial_portfolio: dict | None = None,
    ) -> str:
        """
        Start a long-horizon ASTRA 2.0 research campaign (development line).

        A campaign is an append-only ledger of branches, episodes, claims,
        evidence and deterministic decisions, unlike `astra_cycle`, which runs
        exactly one bounded cycle. Nothing runs yet: this only creates the
        campaign and, when an initial portfolio is supplied, selects the first
        branch. Drive it with `astra_campaign_step`.

        Budgets are hard ceilings, enforced fail-closed and accounted per
        dimension. `deliverables` are the mandatory outcomes; the campaign
        cannot be declared complete while any remains unresolved.
        """
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(
                api.astra_campaign_start,
                objective=objective,
                success_definition=success_definition,
                deliverables=list(deliverables),
                allowed_evidence_classes=list(
                    allowed_evidence_classes
                    or ["SYMBOLIC", "NUMERICAL", "COUNTEREXAMPLE", "FORMAL"]
                ),
                budget={
                    "cycles": int(budget_cycles),
                    "model_calls": int(budget_model_calls),
                    "wall_seconds": int(budget_wall_seconds),
                    "execution_seconds": int(budget_execution_seconds),
                    "human_interventions": 1,
                    "remote_jobs": 0,
                },
                initial_portfolio=initial_portfolio,
            )
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})
        return _campaign_result(result)

    @mcp.tool()
    async def astra_campaign_status(campaign_id: str) -> str:
        """
        Read-only state of a campaign: recommended next action, active branch,
        unresolved deliverables, budget spent and remaining, and the last
        decision. Takes no writer lock, so it is safe while a step is running.
        """
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(api.astra_campaign_status, campaign_id)
            return _campaign_result(result)
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})

    @mcp.tool()
    async def astra_campaign_step(campaign_id: str) -> str:
        """
        Run ONE campaign step: a full atomic cycle on the active branch, then
        the deterministic decision that follows from its evidence.

        This spends real model quota, roughly one `astra_cycle`. It records an
        episode with its five separate status axes, evidence with hashed
        artifacts, any materially different alternatives the synthesis
        proposed, and the decision, then checkpoints. Returns what happened
        and the campaign status afterwards.

        Runs off the server's event loop (a worker thread drives its own
        asyncio.run), so other MCP calls on this same connection — status
        checks, probes, other campaigns — stay responsive while this one runs.
        For a step long enough to risk a client-side wall timeout, prefer
        `astra_campaign_step_submit` and poll `astra_job`.
        """
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(
                asyncio.run, api.astra_campaign_step(campaign_id)
            )
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})
        return _campaign_result(result)

    @mcp.tool()
    async def astra_campaign_step_submit(
        campaign_id: str,
        root: str = "",
        max_seconds: int = 7200,
        cycle_timeout_seconds: int = 0,
    ) -> str:
        """
        Queue ONE campaign step as a persistent DETACHED background job.

        Prefer this over `astra_campaign_step` for a step long enough to risk a
        client-side wall timeout (adversarial audits commonly run 15-30 min).
        Returns instantly with a job_id; survives this session, the MCP server,
        and even a client restart. Poll it with `astra_job`, same as
        `astra_cycle_submit` jobs — it writes into the identical job schema.

        Args:
            campaign_id: the campaign to step.
            root: campaign-store root; empty uses ASTRA's default campaigns
                root (the same default `astra_campaign_step` uses today).
            max_seconds: advisory ceiling recorded on the job (not yet enforced
                by a watchdog; the step's own cycle_timeout_seconds bounds it).
            cycle_timeout_seconds: forwarded to the step's atomic cycle; 0 uses
                ASTRA's configured default.
        """
        try:
            result = await asyncio.to_thread(
                _submit_campaign_step_job,
                campaign_id,
                root or None,
                int(max_seconds),
                int(cycle_timeout_seconds) or None,
            )
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})
        return _campaign_result(result)

    @mcp.tool()
    async def astra_campaign_stop(
        campaign_id: str, mode: str = "pause", reason: str = ""
    ) -> str:
        """
        Stop a campaign: `pause` keeps it resumable, `cancel` is terminal and
        cannot be undone. Prefer `pause` unless the objective is abandoned.
        """
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(
                api.astra_campaign_stop,
                campaign_id,
                mode=mode,
                reason=reason or None,
            )
            return _campaign_result(result)
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})

    @mcp.tool()
    async def astra_campaign_reactivate(campaign_id: str) -> str:
        """Return a PAUSED campaign to ACTIVE after a human review."""
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(api.astra_campaign_reactivate, campaign_id)
            return _campaign_result(result)
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})

    @mcp.tool()
    async def astra_campaign_list() -> str:
        """List every campaign in this checkout with its status and progress."""
        api = _campaign_api()
        try:
            result = await asyncio.to_thread(api.astra_campaign_list)
            return _campaign_result(result)
        except Exception as exc:
            return _campaign_result({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    # Banner/title go to stderr and the window title only - never stdout, which
    # carries the stdio JSON-RPC transport.
    try:
        from core.astra_identity import banner
        banner("MCP server")
    except Exception:
        pass
    mcp.run()  # transporte stdio (lo que usan los CLIs de agentes)
