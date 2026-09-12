"""
astra_tool.py — API por subprocess del core de ASTRA (corre en el venv 3.9).

Recibe una peticion JSON por stdin y devuelve JSON por stdout. Existe para que
procesos EXTERNOS (p.ej. el servidor MCP en Python 3.12) usen el core de ASTRA
sin compartir su entorno Python — igual que el worker remoto: "JSON entra -> JSON sale".

Acciones:
  {"action":"cycle","intuition":"current direction",
   "objective":"shared final goal (optional)","oracle":"local|astrum|auto",
   "exec_timeout":180}
      -> delibera (Codex+agy), sintetiza (Codex), programa (Claude), revisa y
         analiza (Codex), y propone el siguiente paso (agy).

  {"action":"execute","code":"...","oracle":"astrum|local|auto","timeout":180}
      -> ejecuta el codigo via core.executor (respeta local/ASTRUM/auto) y
         devuelve {stdout, stderr, exit_code, engine, verdict, oracle_used}.

  {"action":"review","objective":"...","conjecture":"...","code":"...",
   "provider":"codex_cli"}
      -> audita la estrategia del validador sin ejecutarlo.

  {"action":"client_validate","case_id":"optional","oracle":"local|astrum|both|auto",
   "timeout":300}
      -> enruta y ejecuta la validacion minima orientada a clientes, devolviendo
         paquetes de evidencia con hashes, supuestos, limites y reproducibilidad.

  {"action":"cycle_submit","intuition":"...","max_seconds":7200}
      -> encola un ciclo deliberativo completo y persistente; consultar con
         {"action":"job","job_id":"cycle_..."}.

  {"action":"capacity"}
      -> informa cores/threads visibles y la politica segura de paralelismo.

Uso:  echo '{"action":"execute","code":"print(1)"}' | python astra_tool.py
"""
import os
import re
import sys
import json
import time
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.preflight import load_project_env
load_project_env()  # carga .env (proveedores + config ASTRA_REMOTE_* para ASTRUM)

from core.architecture_contract import (
    CACHE_SCHEMA_VERSION,
    production_manifest,
)
from core.request_structurer import structure_requested
from core.input_request import input_policy

_ACTIVE_CYCLE_CHECKPOINT = None


def _verdict(stdout: str) -> str:
    up = (stdout or "").upper()
    if "VERDICT: PASS" in up:
        return "PASS"
    if "VERDICT: FAIL" in up:
        return "FAIL"
    return "NONE"


_DEFERRED_SECTION_RE = re.compile(
    r"(?ims)^\s*\[Deferred(?:\s+Items|\s+Claims)?\]\s*:?\s*"
    r"(.*?)(?=^\s*\[[^\]]+\]\s*:?|\Z)"
)


def _normalize_deferred_items(value) -> list:
    """Return a bounded, de-duplicated list of explicitly deferred work."""
    if isinstance(value, str):
        candidates = re.split(r"(?:\r?\n\s*[-*]\s+)|(?:;\s+)", value)
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = []
    items = []
    seen = set()
    for candidate in candidates:
        item = re.sub(r"^\s*[-*]\s*", "", str(candidate or "")).strip()
        item = re.sub(r"\s+", " ", item)
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item[:1000])
        if len(items) >= 20:
            break
    return items


def _extract_deferred_items(conjecture: str) -> list:
    items = []
    for match in _DEFERRED_SECTION_RE.finditer(str(conjecture or "")):
        items.extend(_normalize_deferred_items(match.group(1)))
    return _normalize_deferred_items(items)


def _goal_coverage(
    shared_goal: str,
    intuition: str,
    conjecture: str,
    analysis: dict,
    navigation: dict,
) -> dict:
    """Separate an atomic scientific verdict from whole-goal completion.

    ASTRA deliberately validates one bounded conjecture per cycle.  A PASS or
    FAIL for that conjecture is not automatically a verdict on a broader paper,
    research programme, or multi-deliverable objective.
    """
    analysis = analysis if isinstance(analysis, dict) else {}
    navigation = navigation if isinstance(navigation, dict) else {}
    deferred = _normalize_deferred_items(
        [
            *_extract_deferred_items(conjecture),
            *_normalize_deferred_items(analysis.get("deferred_items")),
        ]
    )
    declared = str(analysis.get("goal_coverage") or "").strip().upper()
    analyst_resolved = analysis.get("goal_resolved") is True
    navigator_resolved = navigation.get("macro_resolved") is True
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    same_goal = bool(normalize(shared_goal)) and normalize(shared_goal) == normalize(intuition)

    if deferred:
        status = "partial"
        reason = "The atomic cycle explicitly deferred broader claims or deliverables."
    elif declared == "PARTIAL":
        status = "partial"
        reason = "The evidence analyst marked whole-goal coverage as partial."
    elif declared == "COMPLETE" or analyst_resolved or navigator_resolved:
        status = "complete"
        reason = "The cycle explicitly resolved the shared objective."
    elif same_goal:
        status = "complete"
        reason = "The request and shared objective are the same bounded claim."
    else:
        status = "partial"
        reason = "The cycle decided an atomic direction inside a broader objective."

    atomic_status = str(analysis.get("status") or "UNKNOWN").upper()
    scientific_status = atomic_status
    if status != "complete" and atomic_status in {"VALIDATED", "REFUTED"}:
        scientific_status = f"ATOMIC_{atomic_status}"
    return {
        "status": status,
        "scope": "full_goal" if status == "complete" else "atomic",
        "goal_resolved": status == "complete",
        "reason": reason,
        "deferred_items": deferred,
        "atomic_status": atomic_status,
        "scientific_status": scientific_status,
    }


def _workspace_root() -> str:
    """Directory that receives everything this module writes at run time:
    progress heartbeats, cycle checkpoints, the cycle cache and job folders.

    Default: ``<checkout>/workspace``, the historical location, unchanged.
    ``ASTRA_WORKSPACE_ROOT`` redirects it.  That override exists for the
    test-suite: its fake cycles used to land in the production pool that
    core/cycle_telemetry.py, astra_probe and astra_telemetry read as history,
    and a 0.02 s "Test author quota failure" cycle drags every mean and
    outcome count.  Readers (mcp_server/server.py, scripts/astra_progress.py)
    keep the checkout path on purpose: the variable isolates writers, it does
    not relocate production.  Never export it in the shell that launches the
    MCP server: the readers would look in the checkout while the writers
    write elsewhere.
    """
    configured = (os.environ.get("ASTRA_WORKSPACE_ROOT") or "").strip().strip("'\"")
    if configured:
        return os.path.expanduser(configured)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


def _progress_path(pid=None):
    return os.path.join(_workspace_root(), "progress", f"cycle_{pid or os.getpid()}.json")


def _progress(stage, **extra):
    """Escribe el hito de fase a un archivo que SOBREVIVE si este proceso es
    matado por el timeout externo del MCP. El server lo lee post-mortem para
    reportar en que fase murio el ciclo (defecto historico: el kill llegaba
    antes de que ASTRA pudiera devolver API_ERROR con la fase culpable)."""
    try:
        p = _progress_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if stage == "start":            # poda oportunista de restos viejos (>48h)
            now = time.time()
            for f in os.listdir(os.path.dirname(p)):
                fp = os.path.join(os.path.dirname(p), f)
                try:
                    if now - os.path.getmtime(fp) > 48 * 3600:
                        os.remove(fp)
                except OSError:
                    pass
        checkpoint = _ACTIVE_CYCLE_CHECKPOINT
        payload = {"pid": os.getpid(), "stage": stage, "ts": time.time(), **extra}
        if checkpoint:
            payload["checkpoint"] = checkpoint
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass                             # la observabilidad nunca tumba el ciclo


def _pid_alive_win(pid) -> bool:
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def _jobs_root() -> str:
    return os.path.join(_workspace_root(), "jobs")


def _do_submit(req: dict) -> dict:
    """Lanza un trabajo LARGO como proceso DESACOPLADO (astra_job_runner.py) y
    retorna al instante con el job_id. El job sobrevive a este proceso, al
    server MCP y al cliente: es la via para computo que excede el muro
    sincrono del MCP (~15 min)."""
    import uuid
    import subprocess
    code = req.get("code", "")
    if not code.strip():
        return {"error": "code vacio"}
    oracle = (req.get("oracle") or "local").strip().lower()
    try:
        max_s = int(req.get("max_seconds") or 86400)
    except (TypeError, ValueError):
        max_s = 86400
    job_id = time.strftime("job_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    jobdir = os.path.join(_jobs_root(), job_id)
    os.makedirs(jobdir, exist_ok=True)
    with open(os.path.join(jobdir, "script.py"), "w", encoding="utf-8") as f:
        f.write(code)
    meta = {"id": job_id, "status": "queued", "oracle": oracle,
            "max_seconds": max_s, "created_ts": time.time(), "ts": time.time()}
    with open(os.path.join(jobdir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astra_job_runner.py")
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: el runner vive por su cuenta.
    # Se intenta ademas BREAKAWAY_FROM_JOB por si el cliente MCP usa Job Objects
    # con kill-on-close; si el SO lo rechaza, se reintenta sin el.
    flags = 0x00000008 | 0x00000200
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=open(os.path.join(jobdir, "runner.err"), "w"),
              cwd=os.path.dirname(runner), close_fds=True)
    try:
        p = subprocess.Popen([sys.executable, runner, jobdir],
                             creationflags=flags | 0x01000000, **kw)
    except OSError:
        p = subprocess.Popen([sys.executable, runner, jobdir],
                             creationflags=flags, **kw)
    return {"job_id": job_id, "runner_pid": p.pid, "oracle": oracle,
            "max_seconds": max_s}


def _do_submit_cycle(req: dict) -> dict:
    """Launch a complete deliberative cycle outside the synchronous MCP wall."""
    import subprocess
    import uuid

    intuition = str(req.get("intuition") or "").strip()
    if not intuition:
        return {"error": "intuition vacia"}
    try:
        max_s = max(300, int(req.get("max_seconds") or 7200))
    except (TypeError, ValueError):
        max_s = 7200

    job_id = time.strftime("cycle_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    jobdir = os.path.join(_jobs_root(), job_id)
    os.makedirs(jobdir, exist_ok=True)
    request = {
        key: value
        for key, value in req.items()
        if key not in {"action", "max_seconds"}
    }
    request["wait_for_cycle_slot_seconds"] = max_s
    request["persistent_cycle"] = True
    with open(os.path.join(jobdir, "request.json"), "w", encoding="utf-8") as f:
        json.dump(request, f, ensure_ascii=False, indent=2)
    meta = {
        "id": job_id,
        "kind": "deliberative_cycle",
        "status": "queued",
        "oracle": str(req.get("oracle") or "local").strip().lower(),
        "max_seconds": max_s,
        "created_ts": time.time(),
        "ts": time.time(),
    }
    with open(os.path.join(jobdir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)

    runner = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "astra_cycle_job_runner.py",
    )
    flags = 0x00000008 | 0x00000200
    runner_err = open(os.path.join(jobdir, "runner.err"), "w")
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": runner_err,
        "cwd": os.path.dirname(runner),
        "close_fds": True,
    }
    try:
        try:
            process = subprocess.Popen(
                [sys.executable, runner, jobdir],
                creationflags=flags | 0x01000000,
                **kwargs,
            )
        except OSError:
            process = subprocess.Popen(
                [sys.executable, runner, jobdir],
                creationflags=flags,
                **kwargs,
            )
    finally:
        runner_err.close()
    return {
        "job_id": job_id,
        "kind": "deliberative_cycle",
        "runner_pid": process.pid,
        "oracle": meta["oracle"],
        "max_seconds": max_s,
        "poll_with": "astra_job",
    }


def _do_capacity() -> dict:
    from core.runtime_resources import (
        detect_compute_capacity,
        recommended_parallelism,
    )

    capacity = detect_compute_capacity()
    return {
        "capacity": capacity,
        "parallelism": recommended_parallelism(capacity),
        "already_parallel": [
            "independent conjecture proposals",
            "cross-critiques",
            "independent evidence analyses",
        ],
        "kept_serial": [
            "consensus synthesis after proposals",
            "validator authoring after conjecture",
            "review after validator authoring",
            "oracle execution after approval",
        ],
    }


async def _do_cluster_submit(req: dict) -> dict:
    """Submit scientific code to ASTRUM's persistent shared queue."""
    from core.cluster_client import cluster_rpc
    from core.engine_router import detect_engine

    code = str(req.get("code") or "")
    if not code.strip():
        return {"error": "code vacio"}
    engine = str(req.get("engine") or "").strip().lower() or detect_engine(code)
    payload = {
        "action": "submit",
        "code": code,
        "engine": engine,
        "client_id": req.get("client_id"),
        "project": req.get("project"),
        "priority": req.get("priority", 0),
        "cpu_slots": req.get("cpu_slots", 0),
        "gpu_slots": req.get("gpu_slots", 0),
        "memory_mb": req.get("memory_mb", 0),
        "timeout_seconds": req.get("max_seconds", 3600),
    }
    # Zero means "let the central manager choose its engine-aware default".
    payload = {
        key: value
        for key, value in payload.items()
        if value not in (None, "") and not (key in {"cpu_slots", "gpu_slots", "memory_mb"} and int(value or 0) == 0)
    }
    return await cluster_rpc(payload, timeout=60)


async def _do_cluster_job(req: dict) -> dict:
    from core.cluster_client import cluster_rpc

    return await cluster_rpc(
        {
            "action": "job",
            "job_id": str(req.get("job_id") or "").strip(),
            "limit": req.get("limit", 20),
            "client_filter": str(req.get("client_filter") or "").strip(),
        },
        timeout=60,
    )


async def _do_cluster_cancel(req: dict) -> dict:
    from core.cluster_client import cluster_rpc

    job_id = str(req.get("job_id") or "").strip()
    if not job_id:
        return {"error": "job_id vacio"}
    return await cluster_rpc({"action": "cancel", "job_id": job_id}, timeout=60)


async def _do_cluster_capacity() -> dict:
    from core.cluster_client import cluster_rpc

    return await cluster_rpc({"action": "capacity"}, timeout=60)


def _job_summary(jobdir: str, tail_chars: int = 0):
    try:
        with open(os.path.join(jobdir, "job.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None
    now = time.time()
    meta["heartbeat_age_s"] = round(max(0.0, now - meta.get("ts", 0)), 1)
    if meta.get("status") == "running":
        meta["elapsed_s"] = round(now - meta.get("started_ts", meta.get("created_ts", now)), 1)
        meta["alive"] = _pid_alive_win(meta.get("pid", -1))
        if not meta["alive"]:
            meta["status"] = "killed"    # murio sin llegar a escribir resultado
    else:
        meta["elapsed_s"] = meta.get("duration_s")
    if tail_chars:
        try:
            with open(os.path.join(jobdir, "stdout.log"),
                      encoding="utf-8", errors="replace") as f:
                meta["stdout_tail"] = f.read()[-tail_chars:]
        except Exception:
            pass
    return meta


def _do_job(req: dict) -> dict:
    """Estado/resultado de un job asincrono; sin job_id lista los recientes."""
    job_id = (req.get("job_id") or "").strip()
    root = _jobs_root()
    if not job_id:
        jobs = []
        if os.path.isdir(root):
            dirs = sorted((os.path.join(root, d) for d in os.listdir(root)),
                          key=os.path.getmtime, reverse=True)[:10]
            for d in dirs:
                m = _job_summary(d)
                if m:
                    jobs.append({k: m.get(k) for k in
                                 ("id", "kind", "status", "oracle", "verdict",
                                  "scientific_status", "phase", "elapsed_s",
                                  "heartbeat_age_s")})
        return {"jobs": jobs}
    jobdir = os.path.join(root, job_id)
    if not os.path.isdir(jobdir):
        return {"error": f"job desconocido: {job_id}"}
    meta = _job_summary(jobdir, tail_chars=2000)
    try:
        with open(os.path.join(jobdir, "result.json"), encoding="utf-8") as f:
            meta["result"] = json.load(f)
        s = meta["result"].get("stdout")
        if isinstance(s, str) and len(s) > 4000:
            meta["result"]["stdout"] = s[-4000:]   # el completo queda en stdout.log
    except Exception:
        pass
    return meta


def _cli_meta(agents):
    """Junta los avisos de cuota (escalera de cli_backend), que modelo CLI
    respondio cada fase y el coste proxy acumulado (solo el CLI de claude lo
    reporta; codex/agy devuelven 0), para exponerlos en el JSON del ciclo."""
    warnings, models, costs, accounts = [], {}, {}, {}
    for name, ag in agents:
        warnings.extend(getattr(ag, "cli_warnings", []) or [])
        m = getattr(ag, "cli_last_model", None)
        if m:
            models[name] = m
        account = getattr(ag, "cli_last_account_profile", None)
        if account:
            accounts[name] = account
        c = getattr(ag, "cli_cost_usd", 0.0) or 0.0
        if c:
            costs[name] = round(c, 4)
    return warnings, models, costs, accounts


def _escalate_agent_models(agent):
    """Escalada POR CALIDAD de la escalera de modelos de un agente.

    La escalera de cli_backend solo DESCIENDE por errores de cuota. Esta sube
    por calidad: si el verdict_guard rechazo el resultado del peldano actual
    (WEAK_PASS / CODE_ERROR), el reintento debe arrancar en el peldano
    siguiente (mas capaz), no repetir con el mismo modelo que ya fallo.
    Muta agent.cli_models quitando el primer peldano. Devuelve el nuevo peldano
    inicial, o None si no habia adonde escalar (escalera de un solo tramo)."""
    raw = (getattr(agent, "cli_models", None) or "").strip().strip("'\"")
    rungs = [t.strip() for t in raw.split(",") if t.strip()]
    if len(rungs) < 2:
        return None
    # Phase ladders used for quality escalation are normally ordered from the
    # cheaper model to the stronger model.  Refuse an obvious downgrade when a
    # user supplied a quota-fallback ladder in the opposite direction.
    def _known_rank(model):
        name = model.lower()
        if "opus" in name:
            return 30
        if "sonnet" in name:
            return 20
        if "haiku" in name:
            return 10
        return 0

    current_rank = _known_rank(rungs[0])
    next_rank = _known_rank(rungs[1])
    if current_rank and next_rank and next_rank <= current_rank:
        return None
    agent.cli_models = ",".join(rungs[1:])
    return rungs[1]


def _apply_guard(analysis: dict, exec_result: dict) -> dict:
    """La auditoria determinista manda sobre el juicio del LLM: un VALIDATED
    cuyo script no podia fallar (o con CHECKs en FAIL) se degrada a WEAK_PASS."""
    g = (exec_result or {}).get("guard") or {}
    if analysis.get("status") == "VALIDATED" and g.get("verdict_suspect"):
        analysis = dict(analysis)
        analysis["status"] = "WEAK_PASS"
        analysis["reasoning"] = ((analysis.get("reasoning") or "") +
                                 " | AUDITOR determinista: " +
                                 "; ".join(g.get("reasons") or []) +
                                 " -> PASS no creible tal cual.").strip(" |")
    return analysis


async def _do_execute(req: dict) -> dict:
    from core.executor import execute_python_code
    from core.verdict_guard import assess_verdict

    oracle = (req.get("oracle") or "").strip().lower()
    # 'astrum' es alias amistoso de 'remote'
    mode = {"astrum": "remote"}.get(oracle, oracle)
    if mode in ("local", "remote", "auto"):
        os.environ["ASTRA_ORACLE_MODE"] = mode

    code = req.get("code", "")
    if not code.strip():
        return {"error": "code vacio"}
    timeout = int(req.get("timeout", 180))

    res = await execute_python_code(code, timeout=timeout)
    verdict = _verdict(res.get("stdout", ""))
    if verdict == "NONE" and res.get("engine") == "lean4":
        formal_status = str(res.get("status") or "").upper()
        if formal_status == "PASS":
            verdict = "PASS"
        elif formal_status in {"FAIL", "REJECTED"}:
            verdict = "FAIL"
    res["verdict"] = verdict
    res["guard"] = assess_verdict(code, res)   # auditoria informativa del PASS
    res["oracle_used"] = os.environ.get("ASTRA_ORACLE_MODE", "local")
    return res


async def _do_engines(_req: dict) -> dict:
    """Discover ASTRUM engines through its authoritative registry."""
    from core.remote_executor import list_remote_engines

    result = await list_remote_engines(timeout=30)
    result["available"] = int(result.get("exit_code", -1)) == 0
    return result


async def _do_review(req: dict) -> dict:
    """Public subprocess boundary for adversarial validator-audit benchmarks."""
    from core.llm_client import ASTRAIntelligence
    from core.preflight import phase_provider_map

    code = req.get("code", "")
    if not code.strip():
        return {"error": "code vacio"}
    provider = (
        req.get("provider")
        or os.environ.get("ASTRA_REVIEWER_PROVIDER")
        or phase_provider_map()["analyst"]
    )
    reviewer = ASTRAIntelligence(provider=str(provider))
    review = await reviewer.review_validation_code(
        shared_goal=str(req.get("objective") or req.get("conjecture") or ""),
        conjecture=str(req.get("conjecture") or req.get("objective") or ""),
        code=code,
    )
    warnings, models, _costs, accounts = _cli_meta([("reviewer", reviewer)])
    out = {"review": review, "provider": provider}
    if warnings:
        out["warnings"] = warnings
    if models:
        out["cli_models"] = models
    if accounts:
        out["cli_account_profiles"] = accounts
    return out


async def _do_client_validate(req: dict) -> dict:
    """Run one or all deterministic client evidence cases through the router."""
    from core.client_validation import (
        load_client_validation_cases,
        run_client_validation_case,
        select_oracles,
    )

    cases = load_client_validation_cases(
        include_optional=bool(req.get("include_optional", False))
    )
    case_id = str(req.get("case_id") or "").strip()
    if case_id:
        wanted = {item.strip() for item in case_id.split(",") if item.strip()}
        cases = [case for case in cases if case.id in wanted]
        missing = wanted - {case.id for case in cases}
        if missing:
            return {"error": f"casos de cliente desconocidos: {sorted(missing)}"}
    oracle = str(req.get("oracle") or "auto").strip().lower()
    timeout = int(req.get("timeout") or 300)
    bundles = []
    skipped = []
    for case in cases:
        oracles = select_oracles(case, oracle)
        if not oracles:
            skipped.append(case.id)
            continue
        for selected in oracles:
            bundles.append(
                await run_client_validation_case(
                    case,
                    oracle=selected,
                    timeout=timeout,
                )
            )

    grouped = {}
    for bundle in bundles:
        grouped.setdefault(bundle["case"]["id"], []).append(bundle)
    passing_cases = sum(
        bool(items)
        and all(item["validation"]["status"] == "PASS" for item in items)
        for items in grouped.values()
    )
    comparable = [items for items in grouped.values() if len(items) > 1]
    agreements = [
        len({item["validation"]["claim_verdict"] for item in items}) == 1
        for items in comparable
    ]
    return {
        "schema_version": "1.0",
        "summary": {
            "registered_cases": len(cases),
            "executed_cases": len(grouped),
            "bundles": len(bundles),
            "passing_bundles": sum(
                item["validation"]["status"] == "PASS" for item in bundles
            ),
            "passing_cases": passing_cases,
            "cross_oracle_cases": len(comparable),
            "cross_oracle_agreement": (
                round(sum(agreements) / len(agreements), 6)
                if agreements else None
            ),
            "skipped": skipped,
        },
        "bundles": bundles,
    }


# ============================================================================
# ENSEMBLE MULTI-MODELO (conjetura y/o analisis con >1 proveedor por fase)
# ----------------------------------------------------------------------------
# Config: ASTRA_<FASE>_PROVIDER admite una LISTA separada por comas. Un solo
# valor = comportamiento lineal clasico (sin coste extra). Cada miembro usa la
# escalera GLOBAL de SU CLI (ASTRA_AGY_MODELS / ASTRA_CODEX_MODELS / ...), NO una
# escalera por-fase compartida (mezclaria modelos entre CLIs distintos).
#   * CONJETURA (>=2): cada modelo propone -> CRITICA CRUZADA (cada uno critica a
#     los rivales) -> el sintetizador (ASTRA_SYNTH_PROVIDER, def=traductor/Opus)
#     funde todo en UNA conjetura de consenso.
#   * ANALISIS  (>=2): cada modelo juzga el MISMO resultado -> CONSENSO
#     CONSERVADOR: gana el veredicto mas prudente (REFUTED > CODE_ERROR >
#     WEAK_PASS > VALIDATED). El guard determinista (pint/sympy) sigue mandando.
# OJO LATENCIA: un ciclo ensemble encadena ~8 llamadas CLI (2 conjeturas + 2
# criticas + 1 merge + codigo + 2 analisis). Las ramas independientes corren en
# paralelo, pero las dependencias siguen siendo seriales. Para auditorias largas
# usar cycle_submit/astra_cycle_submit; astra_submit queda reservado a codigo ya
# escrito. Un solo proveedor por fase => camino lineal clasico, sin coste extra.
# ============================================================================

_CRITIQUE_SYSTEM = (
    "Eres un fisico-matematico adversarial. Tu trabajo es REFUTAR: busca errores "
    "dimensionales, algebraicos o de limite, supuestos no justificados y claims que no "
    "sean verificables numerica o simbolicamente. Se conciso y especifico; no elogies. "
    "Si algo esta bien, dilo en una linea y sigue con el siguiente punto debil. "
    "Mantente orientado al OBJETIVO FINAL compartido, no a defender tu propuesta.")

_MERGE_SYSTEM = (
    "Eres un sintetizador cientifico riguroso. Recibes varias conjeturas independientes "
    "y sus criticas cruzadas. Produce UNA sola conjetura de consenso: integra lo mas "
    "solido, descarta lo que las criticas refutaron y deja EXPLICITOS y VERIFICABLES los "
    "2-4 claims decisivos (con la forma exacta a comprobar). La conjetura debe mantener "
    "trazabilidad con el OBJETIVO FINAL compartido, pedir evidencia equilibrada de prueba "
    "y refutacion, y admitir que una estrategia no es decidible si esa es la conclusion "
    "honesta. Devuelve SOLO la conjetura final, sin preambulo ni meta-comentario.")

# Prioridad del consenso conservador: gana el status de mayor rango.
# NON_DECIDABLE sits above CODE_ERROR: when one analyst says "broken script"
# and another "the inputs are missing" (the validator declared it), stopping
# with the list of missing inputs beats burning retries on a rewrite.
_ANALYST_RANK = {"REFUTED": 4, "NON_DECIDABLE": 3.5, "CODE_ERROR": 3, "WEAK_PASS": 2, "VALIDATED": 1}


# Budget-aware review/repair loop (ported from ASTRA 2.0, 2026-09-05).
#
# The review loop used to run until ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS with
# no check on the remaining wall.  On a hard case the reviewer correctly
# rejects a defective validator up to the cap; each rejected round is another
# review + repair, and with nothing watching the budget the cycle blew past the
# 1500 s wall and the outer watchdog hard-killed it -> PARTIAL, no
# certification, wall wasted.  Measured over the recent codex+agy history (all
# the way back to 30-jul), that overflow is the single most common failure.
#
# The fix does NOT relax the reviewer (the rejections are genuine: undefined
# names, hard-coded PASS, tautological self-comparisons, sampling-as-proof).
# It makes the loop STOP CLEAN when what remains cannot fund another
# review + repair + tail, returning a clear "budget exhausted" with the last
# real source preserved, instead of a wall-busting hard kill.
#
# Reserves are measured from ASTRA 1's own cycle_checkpoints, kept low on
# purpose (over-reserving would clean-fail cycles that would have finished):
#   tail (execute+analyze+navigate)  p90 ~= 157 s   -> TRANSLATOR_REPAIR = 160
#   repair (translate_patch)         p50 ~= 212 s   -> REVIEWER = 280 (repair
#                                                       + tail at the median)
# Both are env-overridable so they can be tuned from live runs without a code
# change; they are validated by the next runs, not asserted to be final.
PHASE_MIN_USEFUL_SECONDS = 45


def _reserve_seconds(phase: str, default: int) -> int:
    raw = (os.environ.get(f"ASTRA_{phase}_DOWNSTREAM_RESERVE") or "").strip().strip("'\"")
    try:
        return max(0, int(raw)) if raw else default
    except ValueError:
        return default


def _phase_downstream_reserve(phase: str) -> int:
    """Seconds held back for whatever must still run after ``phase``."""
    return _reserve_seconds(phase, {"REVIEWER": 280, "TRANSLATOR_REPAIR": 160}.get(phase, 0))


def review_round_reserve(model_revisions: int, max_revisions: int, budget) -> int:
    """Seconds to hold back for whatever can still run after THIS review round.

    With revisions remaining, a repair may follow and must be funded, so
    reserve for repair + tail (REVIEWER).  With the revision budget spent, only
    the tail can follow, so reserve for that alone (TRANSLATOR_REPAIR).  And if
    what is usable is already below the repair-follows reserve, a repair could
    not be afforded even if permitted, so treat the round as terminal rather
    than refuse a review the cycle can still run -- the repair (if reached)
    meets its own guard then.
    """
    if model_revisions >= max_revisions:
        return _phase_downstream_reserve("TRANSLATOR_REPAIR")
    full_reserve = _phase_downstream_reserve("REVIEWER")
    usable = getattr(budget, "usable_seconds", None)
    # Downgrade to the tail reserve whenever keeping the full repair+tail
    # reserve would itself starve the review -- not only when usable is below
    # the full reserve. Otherwise a cycle with slightly MORE budget (usable in
    # [full_reserve, full_reserve+min_useful)) would refuse a review that, run
    # as a terminal round, would have fit and could have APPROVED, while a
    # cycle with LESS budget runs it. Closes that non-monotonic band.
    if usable is not None and (usable - full_reserve) < PHASE_MIN_USEFUL_SECONDS:
        return _phase_downstream_reserve("TRANSLATOR_REPAIR")
    return full_reserve


# MAX mode (2026-09-05): one deliberate cycle that uses each CLI's TOP model at
# max reasoning, with NO fallback to a cheaper rung, and enough per-call time
# and wall for those slow models to finish and certify instead of being killed
# at their ceiling (the heavy-model-timeout blocker: gpt-5.6-sol at 240s,
# opus at 720s). The default ladder already tries the top model FIRST but
# degrades to sonnet/gpt-5.5/flash on quota or timeout; MAX refuses to degrade
# and buys the top model the time to succeed.
#
# Triggered per request (req["max_mode"] = True), NEVER persisted: astra_tool
# runs one action per process, so these os.environ overrides die with the
# cycle and revert on the next one unless requested again. The top-model ids
# are constants (update when a provider ships a new top model).
#
# MAX deliberately does NOT set the cycle wall: the wall is the caller's
# deadline (astra_cycle's timeout, astra_cycle_submit's max_seconds). Setting
# a wall higher than the real kill deadline would desync the budget guard from
# the watchdog and reintroduce the wall-bust. Because the top models are slow,
# MAX is meant to be SUBMITTED with a large max_seconds
# (astra_cycle_submit max_mode=True max_seconds=7200) rather than run
# synchronously; an interactive MAX cycle still gets top models + no
# degradation + generous per-call ceilings, but bounded by the client wall.
_MAX_MODE_ENV = {
    "ASTRA_CODEX_MODELS": "gpt-5.6-sol",
    "ASTRA_CLAUDE_MODELS": "claude-opus-4-8",
    "ASTRA_TRANSLATOR_MODELS": "claude-opus-4-8",
    "ASTRA_AGY_MODELS": "gemini-3.1-pro-high",
    "ASTRA_MUSE_MODELS": "muse-spark-1.3",
    "ASTRA_CODEX_REASONING": "xhigh",
    "ASTRA_AGY_EFFORT": "high",
    "ASTRA_MUSE_REASONING": "ultra",
    # Generous per-call ceilings so the top models are not killed mid-thought.
    "ASTRA_CLI_TIMEOUT": "900",
    "ASTRA_CONJECTURE_TIMEOUT": "900",
    "ASTRA_TRANSLATOR_TIMEOUT": "1800",
    "ASTRA_REVIEWER_TIMEOUT": "900",
    "ASTRA_ANALYST_TIMEOUT": "600",
    "ASTRA_NAVIGATOR_TIMEOUT": "600",
    # A deliberate MAX request runs fresh, never served from the cycle cache
    # (and a non-MAX cache can't be served to it anyway: the pinned models and
    # raised timeouts change the cache key). Disables read and write here.
    "ASTRA_CYCLE_CACHE": "0",
}


def _max_mode_requested(req) -> bool:
    v = req.get("max_mode")
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "on", "yes")


def apply_max_mode(req: dict):
    """Force TOP model + max reasoning + generous per-call timeouts for ONE
    cycle, or return None if MAX was not requested.

    Sets in-process env overrides and returns a snapshot {key: prior_value}
    (prior_value None means the key was unset) so the caller can restore it in
    a finally. Restoring makes MAX self-cleaning rather than relying on the
    process dying -- the CLI entrypoints are one-action-per-process, but the
    campaign path runs cycles in-process, and a snapshot/restore keeps MAX from
    ever leaking into a later cycle. Does NOT set the cycle wall: the wall stays
    the caller's deadline (astra_cycle's timeout / astra_cycle_submit's
    max_seconds), so the budget guard can never desync from the watchdog.

    No-fallback by design: each ladder is pinned to a single top model. If that
    model is quota-exhausted or times out even at the raised ceiling, the phase
    has no cheaper rung and the cycle hard-fails with no certification (the
    error carries the provider cause, e.g. 'CUOTA AGOTADA'). Run MAX when the
    pinned accounts have headroom.
    """
    if not _max_mode_requested(req):
        return None
    snapshot = {key: os.environ.get(key) for key in _MAX_MODE_ENV}
    for key, value in _MAX_MODE_ENV.items():
        os.environ[key] = value
    return snapshot


def restore_max_mode(snapshot) -> None:
    """Undo apply_max_mode's env overrides (no-op if snapshot is None)."""
    if not snapshot:
        return
    for key, prior in snapshot.items():
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


def _phase_providers(phase_key, default):
    """Proveedores de una fase. ASTRA_<PHASE>_PROVIDER puede ser una LISTA (comas)
    = ensemble; un solo valor = lineal. Vacio -> [default] (phase_provider_map)."""
    raw = (os.environ.get("ASTRA_%s_PROVIDER" % phase_key.upper()) or "").strip().strip("'\"")
    if raw:
        lst = [p.strip().lower() for p in raw.split(",") if p.strip()]
        if lst:
            return lst
    return [default]


def _clean_text(x):
    """Texto util de una respuesta de _call_api, o None si fallo/simulado/vacio."""
    if isinstance(x, Exception) or not isinstance(x, str):
        return None
    s = x.strip()
    if not s or s == "SIMULATED_RESPONSE" or s.startswith("API_ERROR:"):
        return None
    return s


def _ensemble_report(verdicts):
    """Lista transparente de que dijo cada analista (para el JSON del ciclo)."""
    return [{"provider": p, "status": d.get("status"),
             "reasoning": (d.get("reasoning") or "")[:600]} for p, d in verdicts]


def _combine_verdicts(verdicts):
    """CONSENSO CONSERVADOR puro (testeable sin LLM): descarta abstenciones
    (API_ERROR); del resto gana el veredicto mas prudente por _ANALYST_RANK.
    `verdicts` = [(provider, analysis_dict), ...]."""
    voting = [(p, d) for p, d in verdicts if d.get("status") != "API_ERROR"]
    if not voting:
        merged = dict(verdicts[0][1]) if verdicts else {"status": "API_ERROR"}
        merged["ensemble"] = _ensemble_report(verdicts)
        return merged
    worst_p, worst = max(voting, key=lambda pd: _ANALYST_RANK.get(pd[1].get("status"), 3))
    merged = dict(worst)
    merged["reasoning"] = (
        "[Consenso conservador de %d analistas -> %s (mas prudente, de %s)] %s"
        " || veredictos: %s" % (
            len(voting), worst.get("status"), worst_p, (worst.get("reasoning") or ""),
            "; ".join("%s=%s" % (p, d.get("status")) for p, d in verdicts)))
    merged["ensemble"] = _ensemble_report(verdicts)
    if not merged.get("corrected_code"):
        for _p, d in voting:
            if d.get("corrected_code"):
                merged["corrected_code"] = d["corrected_code"]
                break
    return merged


def _cycle_cache_payload(req, shared_goal, providers_resolved):
    """Return every non-secret input that can change a deliberative cycle.

    Navigation is deliberately context-sensitive.  A repeated local direction
    in a deeper research thread must not replay an earlier navigator decision
    merely because the immediate intuition text happens to be identical.
    """
    runtime_keys = (
        "ASTRA_ORACLE_MODE",
        "ASTRA_ORACLE_TIMEOUT",
        "ASTRA_CLI_TIMEOUT",
        "ASTRA_CONJECTURE_TIMEOUT",
        "ASTRA_SYNTH_TIMEOUT",
        "ASTRA_TRANSLATOR_TIMEOUT",
        "ASTRA_REVIEWER_TIMEOUT",
        "ASTRA_ANALYST_TIMEOUT",
        "ASTRA_NAVIGATOR_TIMEOUT",
        "ASTRA_MAX_RETRIES",
        "ASTRA_REVIEW_MAX_REVISIONS",
        "ASTRA_VNEXT_REVIEW_MAX_REVISIONS",
        "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS",
    )
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "intuition": req.get("intuition", ""),
        "shared_goal": shared_goal,
        "axiomatic_base": req.get("axiomatic_base", ""),
        "thread_summary": req.get("thread_summary", ""),
        "cycles_since_milestone": req.get("cycles_since_milestone", 1),
        "exec_timeout": req.get("exec_timeout", 0),
        # C3: a structured run must never be served a cached raw-request verdict.
        "structure_request": structure_requested(req),
        # Inputs and the input policy change what the validator can decide.
        "inputs": req.get("inputs", ""),
        "input_policy": input_policy(req),
        "resume_checkpoint": req.get("resume_checkpoint", ""),
        "providers": providers_resolved,
        "architecture": production_manifest(),
        "runtime": {
            key: str(os.environ.get(key, "") or "").strip().strip("'\"")
            for key in runtime_keys
        },
    }


async def _ensemble_conjecture(
    providers,
    axiomatic_base,
    intuition,
    phase_timeout,
    synth_provider,
    synth_models=None,
    timeout_for_phase=None,
):
    """Conjetura multi-modelo: propuestas en paralelo -> critica cruzada -> merge.
    Devuelve (conjetura_final, [(label, ASTRAIntelligence)] para _cli_meta)."""
    from core.llm_client import ASTRAIntelligence
    current_timeout = (
        timeout_for_phase("CONJECTURE")
        if timeout_for_phase
        else phase_timeout
    )
    ais = [ASTRAIntelligence(provider=p, cli_models=None, cli_timeout=current_timeout)
           for p in providers]
    gens = await asyncio.gather(
        *[a.generate_conjecture(axiomatic_base=axiomatic_base, intuition=intuition)
          for a in ais], return_exceptions=True)
    used = [("conjecture:%s" % p, a) for p, a in zip(providers, ais)]
    surv = [(p, _clean_text(g), a) for p, a, g in zip(providers, ais, gens)]
    surv = [(p, t, a) for (p, t, a) in surv if t]
    if not surv:
        failures = []
        for provider, result in zip(providers, gens):
            if isinstance(result, Exception):
                detail = f"{type(result).__name__}: {result}"
            elif isinstance(result, str):
                detail = result.strip() or "respuesta vacia"
            else:
                detail = f"respuesta no textual: {type(result).__name__}"
            failures.append(
                f"{provider}={detail.replace(chr(10), ' ')[:500]}"
            )
        return (
            "API_ERROR: todas las conjeturas del ensemble fallaron; "
            + " | ".join(failures),
            used,
            {"proposals": [], "critiques": [], "synthesis_provider": synth_provider},
        )
    if len(surv) == 1:
        return (
            surv[0][1],
            used,
            {
                "proposals": [{"provider": surv[0][0], "text": surv[0][1][:6000]}],
                "critiques": [],
                "synthesis_provider": surv[0][0],
            },
        )

    async def _crit(i):
        p_i, t_i, a_i = surv[i]
        if timeout_for_phase:
            a_i.cli_timeout = timeout_for_phase("CONJECTURE")
        rivals = "\n\n".join("=== RIVAL %s (%s) ===\n%s" % (chr(65 + j), surv[j][0], surv[j][1])
                             for j in range(len(surv)) if j != i)
        return await a_i._call_api(
            _CRITIQUE_SYSTEM,
            "Tu propia propuesta fue:\n%s\n\nAhora critica adversarialmente la(s) "
            "propuesta(s) RIVAL(es):\n\n%s" % (t_i, rivals))

    crits = await asyncio.gather(*[_crit(i) for i in range(len(surv))],
                                 return_exceptions=True)
    synth_timeout = (
        timeout_for_phase("SYNTH")
        if timeout_for_phase
        else phase_timeout
    )
    synth = ASTRAIntelligence(provider=synth_provider, cli_models=synth_models,
                              cli_timeout=synth_timeout)
    used.append(("conjecture_merge:%s" % synth_provider, synth))
    blocks = []
    for i, (p, t, _a) in enumerate(surv):
        blocks.append("=== CONJETURA %s (%s) ===\n%s" % (chr(65 + i), p, t))
        c = _clean_text(crits[i]) if i < len(crits) else None
        if c:
            blocks.append("--- Critica de %s a las rivales ---\n%s" % (p, c))
    merged = _clean_text(await synth._call_api(
        _MERGE_SYSTEM, "Intuicion original:\n%s\n\n%s" % (intuition, "\n\n".join(blocks))))
    if not merged:
        # Merge fallo -> degradar a concatenacion etiquetada (el traductor Opus
        # reconcilia igual, solo sin conjetura de consenso previa).
        merged = "\n\n".join("=== CONJETURA %s (%s) ===\n%s" % (chr(65 + i), p, t)
                             for i, (p, t, _a) in enumerate(surv))
    deliberation = {
        "proposals": [{"provider": p, "text": t[:6000]} for p, t, _a in surv],
        "critiques": [
            {
                "provider": surv[i][0],
                "text": (_clean_text(crits[i]) or "")[:4000],
            }
            for i in range(len(surv))
        ],
        "synthesis_provider": synth_provider,
    }
    return merged, used, deliberation


async def _ensemble_analysis(providers, shared_goal, conjecture, exec_result, phase_timeout):
    """Analisis multi-modelo con CONSENSO CONSERVADOR (_combine_verdicts).
    Devuelve (analysis_dict, [(label, ASTRAIntelligence)])."""
    from core.llm_client import ASTRAIntelligence
    ais = [ASTRAIntelligence(provider=p, cli_models=None, cli_timeout=phase_timeout)
           for p in providers]
    res = await asyncio.gather(
        *[a.analyze_results(conjecture, exec_result, shared_goal=shared_goal) for a in ais],
        return_exceptions=True)
    used = [("analyst:%s" % p, a) for p, a in zip(providers, ais)]
    verdicts = []
    for p, r in zip(providers, res):
        if not isinstance(r, dict):
            r = {"status": "API_ERROR", "reasoning": "respuesta no-dict: %s" % (r,)}
        verdicts.append((p, r))
    return _combine_verdicts(verdicts), used


async def _do_cycle_impl(req: dict) -> dict:
    """Goal-driven multi-model cycle with deliberation, review and navigation."""
    from core.cycle_budget import CycleBudget
    from core.preflight import phase_provider_map
    from core.llm_client import ASTRAIntelligence
    from core.executor import execute_python_code
    from core.verdict_guard import assess_verdict
    from core.autofix import try_autofix
    from core.review_defects import (
        StuckTracker,
        alternative_strategy,
        detector_enabled,
        directed_correction,
        stuck_message,
    )
    from core.request_structurer import (
        compose_direction,
        has_bounded_claim,
        parse_structured_request,
    )
    from core.input_request import (
        SILENT_ASSUME_DEFERRED,
        build_input_request,
        inputs_block,
        inputs_text,
        inputs_truncated,
        parse_assumed_inputs,
    )
    from core.non_decidable import detect_non_decidable, resolve_non_decidable
    from core.progress_window import open_progress_window
    import hashlib

    oracle = (req.get("oracle") or "").strip().lower()
    mode = {"astrum": "remote"}.get(oracle, oracle)
    if mode in ("local", "remote", "auto"):
        os.environ["ASTRA_ORACLE_MODE"] = mode

    # MAX mode env is applied (and restored) by _do_cycle around this call; here
    # we only read the flag to record it on the checkpoint.
    max_mode = _max_mode_requested(req)

    intuition = req.get("intuition", "")
    if not intuition.strip():
        return {"error": "intuition vacia"}
    shared_goal = (
        req.get("objective")
        or req.get("macro_question")
        or req.get("shared_goal")
        or intuition
    ).strip()
    # C3 provenance: the raw request is kept whether or not structuring runs.
    request_record = {
        "structure_request": structure_requested(req),
        "original": intuition,
    }
    # Ask-instead-of-stop (core/input_request.py): user-supplied inputs and the
    # input policy reach the conjecture engine, the structurer and the author
    # as one authoritative block; empty by default so prompts are unchanged.
    extra_inputs = inputs_block(req)
    axiomatic_base_text = "\n\n".join(
        part for part in (extra_inputs, str(req.get("axiomatic_base") or "")) if part
    )
    request_record["input_policy"] = input_policy(req)
    if inputs_text(req):
        request_record["inputs"] = inputs_text(req)
    if inputs_truncated(req):
        request_record["inputs_truncated"] = True
    # The independent reviewer and the analyst must see the same inputs and
    # policy as the author, or they reject the placeholders the user approved.
    # Policy first, values capped: the reviewer reads conjecture[:5000].
    auditor_block = inputs_block(req, inputs_limit=1500)
    review_conjecture_prefix = (auditor_block + "\n\n") if auditor_block else ""
    # resume_checkpoint: reuse the conjecture of the cycle that asked for the
    # inputs (already paid for) when it was about the same objective.
    resumed_from = None
    prior_checkpoint = {}
    resume_path = str(req.get("resume_checkpoint") or "").strip()
    if resume_path:
        try:
            with open(resume_path, encoding="utf-8") as fh:
                prior_checkpoint = json.load(fh) or {}
        except Exception:
            prior_checkpoint = {}
        _norm = lambda value: re.sub(r"\s+", " ", str(value or "")).strip().casefold()
        prior_request = prior_checkpoint.get("request") if isinstance(prior_checkpoint, dict) else None
        prior_intuition = (
            (prior_request or {}).get("original") if isinstance(prior_request, dict) else None
        ) or (prior_checkpoint.get("intuition") if isinstance(prior_checkpoint, dict) else None)
        if (
            isinstance(prior_checkpoint, dict)
            and str(prior_checkpoint.get("conjecture") or "").strip()
            and _norm(prior_checkpoint.get("shared_goal")) == _norm(shared_goal)
            and _norm(prior_intuition) == _norm(intuition)
        ):
            resumed_from = resume_path
        else:
            request_record["resume_warning"] = (
                "resume_checkpoint ignored: unreadable, without a conjecture, or about "
                "a different objective or direction; the conjecture phase runs again"
            )
    validator_repair_vnext = (
        os.environ.get("ASTRA_VALIDATOR_REPAIR_VNEXT", "0")
        .strip()
        .strip("'\"")
        .lower()
        in ("1", "true", "on", "yes")
    )
    validator_repair_strategy = (
        os.environ.get("ASTRA_VALIDATOR_REPAIR_STRATEGY", "local-patch")
        .strip()
        .strip("'\"")
        .lower()
    )
    validator_repair_vnext1 = (
        validator_repair_vnext
        and validator_repair_strategy
        in ("local-patch", "local_patch", "vnext1", "vnext.1", "production")
    )

    pmap = phase_provider_map()
    # Ensemble multi-modelo: ASTRA_<FASE>_PROVIDER puede ser lista (comas). El
    # sintetizador de conjeturas por defecto = el traductor. Se resuelve
    # ANTES del cache key para que providers distintos no colisionen en cache.
    conj_providers = _phase_providers("CONJECTURE", pmap["conjecture"])
    an_providers = _phase_providers("ANALYST", pmap["analyst"])
    synth_provider = ((os.environ.get("ASTRA_SYNTH_PROVIDER") or "").strip().strip("'\"")
                      or pmap["translator"])
    reviewer_provider = ((os.environ.get("ASTRA_REVIEWER_PROVIDER") or "").strip().strip("'\"")
                         or pmap["analyst"])
    navigator_provider = ((os.environ.get("ASTRA_NAVIGATOR_PROVIDER") or "").strip().strip("'\"")
                          or pmap["analyst"])
    providers_resolved = dict(pmap)
    providers_resolved["conjecture"] = conj_providers if len(conj_providers) > 1 else conj_providers[0]
    providers_resolved["analyst"] = an_providers if len(an_providers) > 1 else an_providers[0]
    providers_resolved["reviewer"] = reviewer_provider
    providers_resolved["navigator"] = navigator_provider
    if len(conj_providers) > 1:
        providers_resolved["conjecture_synth"] = synth_provider
    ensemble_agents = []   # instancias extra de los ensembles, para _cli_meta

    # --- Cache de ciclos: misma intuicion+providers+oraculo => mismo resultado.
    # Los research loops revisitan direcciones parecidas; sin esto cada revisita
    # quema el pipeline entero. ASTRA_CYCLE_CACHE=0 lo apaga.
    use_cache = (os.environ.get("ASTRA_CYCLE_CACHE", "1").strip().strip("'\"").lower()
                 not in ("0", "off", "false"))
    cache_dir = os.path.join(_workspace_root(), "cycle_cache")
    cache_payload = _cycle_cache_payload(
        req,
        shared_goal,
        providers_resolved,
    )
    ckey = hashlib.sha256(
        json.dumps(cache_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    cpath = os.path.join(cache_dir, ckey + ".json")
    if use_cache and os.path.exists(cpath):
        try:
            with open(cpath, encoding="utf-8") as f:
                cached = json.load(f)
            cached["cached"] = True
            return cached
        except Exception:
            pass

    # --- Observabilidad: cronometro por fase + hitos al archivo de progreso.
    t_start = time.monotonic()
    timings = {}
    # Persistent runners supply their own hard ceiling.  Honour it here so
    # CycleBudget can return a checkpointed PARTIAL result before the detached
    # watchdog kills the process and turns useful progress into empty stdout.
    cycle_wall = req.get("cycle_timeout_seconds") or (
        None if req.get("persistent_cycle") else 1500
    )
    budget = CycleBudget(
        cycle_wall,
        return_buffer_seconds=req.get("cycle_return_buffer_seconds") or 60,
    )
    checkpoint_dir = os.path.join(_workspace_root(), "cycle_checkpoints")
    checkpoint_path = os.path.join(
        checkpoint_dir,
        f"{ckey}_{os.getpid()}.json",
    )
    global _ACTIVE_CYCLE_CHECKPOINT
    _ACTIVE_CYCLE_CHECKPOINT = checkpoint_path
    checkpoint_state = {
        "schema_version": "1.0",
        "pid": os.getpid(),
        "cache_key": ckey,
        "shared_goal": shared_goal,
        "intuition": intuition,
        "providers": providers_resolved,
        "max_mode": max_mode,
        "input_policy": request_record["input_policy"],
        "inputs": request_record.get("inputs", ""),
        "created_ts": time.time(),
        # Stamped ONCE here so _save_cycle_checkpoint's update() propagates it
        # to every save this cycle makes (start, translation_complete, review
        # rejections, tool_error/failed/partial, done). Without this the
        # manifest reached only the final 'done' result, so every rejected or
        # killed cycle -- exactly what the strict-translator overlay targets --
        # had no record of which translator contract produced it (cycle-
        # robustness spec, 'Transversal: procedencia').
        "architecture": production_manifest(),
    }

    def _save_cycle_checkpoint(stage, **artifacts):
        checkpoint_state.update(artifacts)
        checkpoint_state.update(
            {
                "stage": stage,
                "updated_ts": time.time(),
                "timings": dict(timings),
                "budget": budget.snapshot(),
            }
        )
        try:
            os.makedirs(checkpoint_dir, exist_ok=True)
            temporary = checkpoint_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump(checkpoint_state, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, checkpoint_path)
        except Exception:
            pass
        return checkpoint_path

    def _mark(name, t0):
        timings[name] = round(timings.get(name, 0.0) + (time.monotonic() - t0), 2)

    _save_cycle_checkpoint("start")
    _progress(
        "start",
        oracle=os.environ.get("ASTRA_ORACLE_MODE", "local"),
        budget=budget.snapshot(),
    )
    # One console per cycle (core/progress_window.py): follows this pid's
    # heartbeat with the instruction, the phase, a bar and an ETA. Windows
    # only, ASTRA_PROGRESS_WINDOW=0 disables it, never raises.
    launcher_pid = open_progress_window(
        os.getpid(), _workspace_root(), checkpoint=checkpoint_path
    )
    if launcher_pid:
        checkpoint_state["progress_window"] = {"launcher_pid": launcher_pid}

    def _phase_models(phase):
        # Escalera de modelos POR FASE (ASTRA_TRANSLATOR_MODELS='sonnet,default');
        # si no hay, cli_backend usa la escalera global ASTRA_<CLI>_MODELS.
        v = (os.environ.get(f"ASTRA_{phase}_MODELS")
             or os.environ.get(f"ASTRA_{phase}_MODEL") or "")
        return v.strip().strip("'\"") or None

    def _configured_phase_timeout(phase):
        # Presupuesto por llamada especifico de la fase (p.ej. el TRADUCTOR
        # genera scripts de fisica largos: ASTRA_TRANSLATOR_TIMEOUT=480);
        # sin variable, cli_backend usa ASTRA_CLI_TIMEOUT (240).
        v = (os.environ.get(f"ASTRA_{phase}_TIMEOUT") or "").strip().strip("'\"")
        try:
            if v:
                return int(v)
            return int(
                str(os.environ.get("ASTRA_CLI_TIMEOUT", "240"))
                .strip()
                .strip("'\"")
            )
        except ValueError:
            return 240

    def _phase_timeout(phase, reserve=None):
        return budget.phase_timeout(
            _configured_phase_timeout(phase),
            default_seconds=240,
            reserve_seconds=(
                _phase_downstream_reserve(phase) if reserve is None else reserve
            ),
        )

    def _prepare_agent(agent, phase, reserve=None):
        agent.cli_timeout = _phase_timeout(phase, reserve)
        return agent.cli_timeout

    def _phase_starved(phase, reserve=None):
        """True when what is left cannot fund a call worth making."""
        return _phase_timeout(phase, reserve) < PHASE_MIN_USEFUL_SECONDS

    def _starved_error(what, phase, reserve=None):
        snap = budget.snapshot()
        # "time budget" is the phrase _fail keys on to classify this as a
        # deadline-limited PARTIAL (an honest "ran out of wall" outcome with
        # the last real source preserved), not a TOOL_ERROR (infra fault).
        return (
            f"Cycle budget exhausted before {what}: the phase would get "
            f"{_phase_timeout(phase, reserve)}s of time budget, below the "
            f"{PHASE_MIN_USEFUL_SECONDS}s a call needs to be worth making "
            f"({snap.get('remaining_seconds')}s remain of "
            f"{snap.get('total_seconds')}s, minus what is reserved for the "
            "phases still ahead)."
        )

    conj = ASTRAIntelligence(provider=pmap["conjecture"],
                             cli_models=_phase_models("CONJECTURE"),
                             cli_timeout=_phase_timeout("CONJECTURE"))
    trans = ASTRAIntelligence(provider=pmap["translator"],
                              cli_models=_phase_models("TRANSLATOR"),
                              cli_timeout=_phase_timeout("TRANSLATOR"))
    analyst = ASTRAIntelligence(provider=pmap["analyst"],
                                cli_models=_phase_models("ANALYST"),
                                cli_timeout=_phase_timeout("ANALYST"))
    reviewer = ASTRAIntelligence(provider=reviewer_provider,
                                 cli_models=_phase_models("REVIEWER"),
                                 cli_timeout=_phase_timeout("REVIEWER"))
    navigator = ASTRAIntelligence(provider=navigator_provider,
                                  cli_models=_phase_models("NAVIGATOR"),
                                  cli_timeout=_phase_timeout("NAVIGATOR"))
    agents = [
        ("conjecture", conj),
        ("translator", trans),
        ("reviewer", reviewer),
        ("analyst", analyst),
        ("navigator", navigator),
    ]
    quality_escalations = []
    # C2: one entry per model-reviewer rejection (classes, repeat, action).
    # Defined before _fail, which stamps it on every failure result.
    defect_trace = []
    # Bound before _fail too: a declared non-decidable validator whose retry
    # then dies (starved review, author API error) must keep its record.
    analysis = {}

    def _escalate_for_quality(stage, status):
        new_rung = _escalate_agent_models(trans)
        if not new_rung:
            return None
        record = {
            "stage": stage,
            "status": status,
            "translator_now": new_rung,
        }
        quality_escalations.append(record)
        _progress(
            "quality_escalation",
            quality_stage=stage,
            status=status,
            model=new_rung,
            timings=timings,
        )
        return new_rung

    async def _run_analysis(cj, ex):
        # Un solo analista => camino lineal clasico. >=2 => consenso conservador.
        if len(an_providers) > 1:
            a, used = await _ensemble_analysis(
                an_providers, shared_goal, cj, ex, _phase_timeout("ANALYST")
            )
            ensemble_agents.extend(used)
            return a
        _prepare_agent(analyst, "ANALYST")
        return await analyst.analyze_results(cj, ex, shared_goal=shared_goal)

    def _fail(msg, phase, conjecture_text=None):
        deadline_limited = (
            budget.total_seconds is not None
            and (
                "timeout tras" in str(msg).lower()
                or "time budget" in str(msg).lower()
                or not budget.can_start()
            )
        )
        out = {
            "status": "PARTIAL" if deadline_limited else "TOOL_ERROR",
            "error": msg,
            "phase": phase,
            "budget": budget.snapshot(),
            "checkpoint": checkpoint_path,
            "resume_available": True,
            "resume_hint": (
                "Submit the same request with astra_cycle_submit for a persistent "
                "cycle, or use the checkpoint's conjecture/code with astra_execute."
            ),
        }
        if conjecture_text:
            # SALVAVIDAS: si murio el traductor, devolver la conjetura ya pagada
            # para que el agente llamador la traduzca el mismo y use astra_execute.
            out["conjecture"] = conjecture_text
        if request_record["structure_request"]:
            out["request"] = request_record
        if defect_trace:
            out["review_defect_trace"] = defect_trace
        if isinstance(analysis, dict) and analysis.get("non_decidable"):
            out["non_decidable"] = analysis["non_decidable"]
            out["missing_inputs"] = list(analysis.get("missing_inputs") or [])
        if timings:
            timings["total"] = round(time.monotonic() - t_start, 2)
            out["timings"] = timings
        warnings, cli_models, cli_costs, cli_accounts = _cli_meta(agents + ensemble_agents)
        if warnings:
            out["warnings"] = warnings
        if cli_models:
            out["cli_models"] = cli_models
        if cli_costs:
            out["cli_cost_usd"] = {**cli_costs,
                                   "total": round(sum(cli_costs.values()), 4)}
        if cli_accounts:
            out["cli_account_profiles"] = cli_accounts
        if quality_escalations:
            out["quality_escalations"] = list(quality_escalations)
        _save_cycle_checkpoint(
            "partial" if deadline_limited else "failed",
            error=str(msg),
            failed_phase=phase,
        )
        _progress("failed", phase=phase, timings=timings)
        return out

    review_history = []
    preflight_history = []
    local_repair_history = []
    model_patch_history = []
    # Quien fallo DENTRO de _review_or_revise: el revisor da su veredicto, pero
    # la regeneracion la firma el traductor. Sin esto, un tope de cuota del
    # autor se reportaba como fallo del revisor.
    review_failure_phase = {}

    async def _request_model_patch(
        current_code,
        translation_input,
        instructions,
        source,
    ):
        """Request and audit a bounded exact-edit patch from the code author."""
        before_sha = hashlib.sha256(current_code.encode("utf-8")).hexdigest()
        _progress(
            "model_patch",
            source=source,
            patch=len(model_patch_history) + 1,
            timings=timings,
            budget=budget.snapshot(),
        )
        t0 = time.monotonic()
        _prepare_agent(trans, "TRANSLATOR")
        patch_result = await trans.repair_validation_code(
            translation_input,
            current_code,
            instructions,
        )
        _mark("translate_patch", t0)
        patched_code = patch_result.get("code") or current_code
        record = {
            key: value
            for key, value in patch_result.items()
            if key != "code"
        }
        record.update(
            {
                "source": source,
                "before_sha256": before_sha,
                "after_sha256": hashlib.sha256(
                    patched_code.encode("utf-8")
                ).hexdigest(),
            }
        )
        model_patch_history.append(record)
        if patch_result.get("status") == "API_ERROR":
            # Fallo del PROVEEDOR del autor (cuota, timeout, transporte), no un
            # veredicto sobre el parche. Envolverlo como "parche no aplicable"
            # perdia el prefijo API_ERROR: del que dependen el corto circuito de
            # fase y los consumidores aguas abajo, y disparaba una regeneracion
            # condenada que quema otra llamada con la cuota ya agotada.
            reason = str(patch_result.get("reason") or "").strip()
            if not reason.startswith("API_ERROR:"):
                reason = f"API_ERROR: {reason or 'bounded validator patch failed'}"
            return current_code, reason
        if patch_result.get("status") != "APPLIED":
            return (
                current_code,
                "Bounded model patch was not applicable: "
                f"{patch_result.get('reason') or patch_result.get('status')}",
            )
        return patched_code, None

    async def _review_or_revise(current_code, conjecture_text, translation_input):
        """Codex audits; Claude remains the sole generative code author."""
        review_failure_phase.clear()
        stuck_tracker = StuckTracker(defect_trace) if detector_enabled() else None
        enabled = (
            os.environ.get("ASTRA_CODE_REVIEW", "1").strip().strip("'\"").lower()
            not in ("0", "off", "false")
        )
        if not enabled:
            review = {
                "status": "APPROVED",
                "reasoning": "Independent code review disabled by ASTRA_CODE_REVIEW.",
                "revision_instructions": "",
                "coverage": [],
            }
            return current_code, review, None
        try:
            if validator_repair_vnext1:
                revision_env = "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS"
                revision_default = "1"
            elif validator_repair_vnext:
                revision_env = "ASTRA_VNEXT_REVIEW_MAX_REVISIONS"
                revision_default = "2"
            else:
                revision_env = "ASTRA_REVIEW_MAX_REVISIONS"
                revision_default = "1"
            max_revisions = max(
                0,
                int(
                    os.environ.get(revision_env, revision_default)
                    .strip()
                    .strip("'\"")
                ),
            )
        except ValueError:
            max_revisions = 1 if validator_repair_vnext1 else (
                2 if validator_repair_vnext else 1
            )

        model_revisions = 0
        review_round = 0
        seen_code = set()
        last_review = {
            "status": "INCONCLUSIVE",
            "reasoning": "No review round completed.",
            "revision_instructions": "",
            "coverage": [],
        }
        while True:
            # Budget guard: what must be held back depends on what can still
            # follow THIS round (a repair if revisions remain, else only the
            # tail). If there is not enough usable wall to make the review
            # worth starting, stop clean with the last real source preserved
            # instead of running a round that would blow the wall -> PARTIAL.
            review_reserve = review_round_reserve(
                model_revisions, max_revisions, budget
            )
            if _phase_starved("REVIEWER", review_reserve):
                return (
                    current_code,
                    last_review,
                    _starved_error("independent review", "REVIEWER", review_reserve),
                )
            code_sha = hashlib.sha256(current_code.encode("utf-8")).hexdigest()
            _progress(
                "review",
                revision=model_revisions,
                review_round=review_round,
                timings=timings,
                budget=budget.snapshot(),
            )
            t0 = time.monotonic()
            if validator_repair_vnext:
                from core.validator_preflight import (
                    audit_validation_code,
                    preflight_as_review,
                    repair_validation_code,
                    smoke_validation_code,
                )

                preflight = audit_validation_code(current_code)
                smoke = smoke_validation_code(current_code)
                preflight_record = {
                    **preflight,
                    "smoke": smoke,
                    "revision": model_revisions,
                    "review_round": review_round,
                    "code_sha256": code_sha,
                }
                preflight_history.append(preflight_record)
                if (
                    validator_repair_vnext1
                    and preflight.get("status") != "APPROVED"
                    and code_sha not in seen_code
                ):
                    seen_code.add(code_sha)
                    local_result = repair_validation_code(current_code, preflight)
                    repaired_code = local_result.get("code") or current_code
                    if local_result.get("changed"):
                        after_sha = hashlib.sha256(
                            repaired_code.encode("utf-8")
                        ).hexdigest()
                        local_repair_history.append(
                            {
                                "source": "deterministic_local_patch",
                                "review_round": review_round,
                                "before_sha256": code_sha,
                                "after_sha256": after_sha,
                                "repairs": local_result.get("repairs") or [],
                            }
                        )
                        current_code = repaired_code
                        review_round += 1
                        _mark("review", t0)
                        continue
                if preflight.get("status") != "APPROVED":
                    review = preflight_as_review(preflight)
                else:
                    _prepare_agent(reviewer, "REVIEWER", review_reserve)
                    review = await reviewer.review_validation_code(
                        shared_goal=shared_goal,
                        conjecture=conjecture_text,
                        code=current_code,
                        static_context=smoke,
                    )
                    review["source"] = "model_reviewer"
            else:
                _prepare_agent(reviewer, "REVIEWER", review_reserve)
                review = await reviewer.review_validation_code(
                    shared_goal=shared_goal,
                    conjecture=conjecture_text,
                    code=current_code,
                )
                review["source"] = "model_reviewer"
            _mark("review", t0)
            last_review = review
            review_history.append(
                {
                    **dict(review),
                    "revision": model_revisions,
                    "review_round": review_round,
                    "code_sha256": code_sha,
                }
            )
            status = str(review.get("status") or "").upper()
            if status == "APPROVED":
                return current_code, review, None
            if status == "API_ERROR":
                return current_code, review, review.get("reasoning") or "reviewer API error"
            # C2 (cycle-robustness spec): classify this rejection against the
            # C0 defect taxonomy and decide what the next revision is: directed
            # (first sighting of a class), a strategy switch (same class twice)
            # or a clean stop naming the class (it persisted after the switch).
            # Only model-reviewer rejections are observed: preflight rejections
            # are deterministic and so is their repair. Same revision cap as
            # before (decision 4): a directed round replaces a blind one.
            decision = None
            if stuck_tracker is not None and review.get("source") == "model_reviewer":
                decision = stuck_tracker.observe(
                    review,
                    review_round,
                    model_revisions,
                    can_revise=model_revisions < max_revisions,
                )
                review_history[-1].update(
                    {
                        "defect_classes": decision["classes"],
                        "defect_primary": decision["primary"],
                        "repeated_classes": decision["repeated"],
                        "c2_action": decision["action"],
                    }
                )
            if decision is not None and decision["action"] == "stop":
                diagnosis = stuck_tracker.diagnosis()
                review["stuck_diagnosis"] = diagnosis
                return (
                    current_code,
                    review,
                    stuck_message(
                        decision["repeated"],
                        [
                            r["review_round"]
                            for r in stuck_tracker.own
                            if set(r["classes"]) & set(decision["repeated"])
                        ],
                        model_revisions,
                        max_revisions,
                        review.get("reasoning", ""),
                        actions=diagnosis["actions"],
                        switched_for=diagnosis["switched_for"],
                    ),
                )
            if model_revisions >= max_revisions:
                return (
                    current_code,
                    review,
                    "Independent reviewer did not approve the validation strategy "
                    f"after {model_revisions} model revision(s): "
                    f"{review.get('reasoning', '')}",
                )

            model_revisions += 1
            instructions = (
                review.get("revision_instructions")
                or review.get("reasoning")
                or "Regenerate a falsifiable validator with independent checks."
            )
            _progress(
                "review_revision",
                revision=model_revisions,
                review_round=review_round,
                timings=timings,
                budget=budget.snapshot(),
                **(
                    {"defect_classes": decision["classes"], "c2_action": decision["action"]}
                    if decision
                    else {}
                ),
            )
            patch_instructions = (
                "Independent Codex review returned "
                f"{status}. Revise the validation script without changing the "
                f"scientific claim. Instructions:\n{instructions}"
            )[:3500]
            if decision and decision["action"] == "directed_patch":
                patch_instructions = (
                    patch_instructions + "\n\n" + directed_correction(decision["classes"])
                )[:6000]
            elif decision and decision["action"] == "strategy_switch":
                patch_instructions = (
                    patch_instructions + "\n\n" + alternative_strategy(decision["repeated"])
                )[:6000]
            _escalate_for_quality("pre_oracle_review", status)
            defect_labels = {
                str(item).lower()
                for item in (review.get("defect_labels") or [])
            }
            requires_regeneration = (
                status == "REJECT"
                or "syntax_error" in defect_labels
                # C2 strategy switch: a different route needs a fresh validator,
                # not a bounded patch of the rejected wiring.
                or (decision is not None and decision["action"] == "strategy_switch")
                or current_code.strip().lower()
                in {
                    "write operation completed",
                    "file written successfully",
                    "operation completed",
                }
            )
            # Budget guard before the repair: the repair call (patch or full
            # regeneration) plus the tail must still fit, or stop clean with
            # the last real source instead of starting a repair that would
            # blow the wall -> PARTIAL.
            repair_reserve = _phase_downstream_reserve("TRANSLATOR_REPAIR")
            if _phase_starved("TRANSLATOR", repair_reserve):
                review_failure_phase["phase"] = "translator"
                return current_code, review, _starved_error(
                    "validator repair", "TRANSLATOR", repair_reserve
                )
            if validator_repair_vnext1 and not requires_regeneration:
                current_code, patch_error = await _request_model_patch(
                    current_code,
                    translation_input,
                    patch_instructions,
                    "model_reviewer",
                )
                if patch_error and patch_error.startswith("API_ERROR:"):
                    # El autor no llego a opinar sobre el parche: su proveedor
                    # fallo. Abortar YA con el error del proveedor y conservar el
                    # ultimo fuente REAL; regenerar aqui solo repetiria el mismo
                    # fallo de cuota y enterraria la causa.
                    review_failure_phase["phase"] = "translator"
                    return current_code, review, patch_error
                if patch_error:
                    # The bounded patch guard may correctly reject a model reply
                    # that rewrites too much source.  That is a strategy signal,
                    # not a terminal tool failure: regenerate once with the
                    # already quality-escalated author, then re-run preflight and
                    # independent review inside the same revision budget.
                    #
                    # _request_model_patch is itself an uncapped model call that
                    # can burn most of what was left before returning
                    # patch_error, so re-check the budget here: otherwise this
                    # fallback regeneration is handed the scraps and dies at
                    # "timeout tras 1s", which reads as a hung model rather than
                    # an exhausted cycle.
                    if _phase_starved("TRANSLATOR", repair_reserve):
                        review_failure_phase["phase"] = "translator"
                        return current_code, review, _starved_error(
                            "validator repair regeneration", "TRANSLATOR", repair_reserve
                        )
                    _progress(
                        "review_regeneration",
                        reason=patch_error[:500],
                        revision=model_revisions,
                        review_round=review_round,
                        timings=timings,
                        budget=budget.snapshot(),
                    )
                    t0 = time.monotonic()
                    _prepare_agent(trans, "TRANSLATOR")
                    regenerated = await trans.translate_to_code(
                        translation_input,
                        is_correction=True,
                        previous_error=patch_instructions,
                        previous_code=current_code,
                    )
                    _mark("translate", t0)
                    if (
                        isinstance(regenerated, str)
                        and regenerated.startswith("API_ERROR:")
                    ):
                        # Fallo del AUTOR (cuota, timeout, transporte). Conservar
                        # el ultimo fuente REAL: publicar el texto del error como
                        # `code` hace que el preflight denuncie un error de
                        # sintaxis en la linea 1 y tapa la causa verdadera.
                        review_failure_phase["phase"] = "translator"
                        return current_code, review, regenerated
                    current_code = regenerated
            else:
                t0 = time.monotonic()
                _prepare_agent(trans, "TRANSLATOR")
                regenerated = await trans.translate_to_code(
                    translation_input,
                    is_correction=True,
                    previous_error=patch_instructions,
                    previous_code=current_code,
                )
                _mark("translate", t0)
                if (
                    isinstance(regenerated, str)
                    and regenerated.startswith("API_ERROR:")
                ):
                    # Mismo salvavidas que en la rama de parche acotado: el
                    # error del autor no debe suplantar al codigo.
                    review_failure_phase["phase"] = "translator"
                    return current_code, review, regenerated
                current_code = regenerated
            review_round += 1

    # C3 (cycle-robustness spec, opt-in): turn the raw request into a
    # structured single-cycle direction before the conjecture phase. Original
    # and structured request are both kept on the checkpoint and the result.
    # A structurer failure never kills the cycle: the raw request is used and
    # the error recorded.
    if request_record["structure_request"]:
        structurer_provider = (
            (os.environ.get("ASTRA_STRUCTURER_PROVIDER") or "").strip().strip("'\"")
            or synth_provider
        )
        structurer = ASTRAIntelligence(
            provider=structurer_provider,
            cli_models=_phase_models("STRUCTURER"),
            cli_timeout=_phase_timeout("STRUCTURER"),
        )
        agents.append(("structurer", structurer))
        request_record["provider"] = structurer_provider
        _progress("structure", timings=timings, budget=budget.snapshot())
        t0 = time.monotonic()
        structured_raw = await structurer.structure_request(
            intuition,
            objective=str(req.get("objective") or req.get("macro_question") or ""),
            axiomatic_base=axiomatic_base_text,
        )
        _mark("structure", t0)
        structured = _clean_text(structured_raw)
        parsed = parse_structured_request(structured or "")
        if not structured:
            request_record["structurer_error"] = (
                str(structured_raw)[:500]
                if isinstance(structured_raw, str) and structured_raw.strip()
                else "empty response"
            )
        elif not has_bounded_claim(parsed):
            # A refusal, prose, or an unheaded blob must not become the
            # cycle's direction: keep the raw request, record the reply.
            request_record["structurer_error"] = (
                "structurer reply has no BOUNDED CLAIM heading; raw request used"
            )
            request_record["structured_reply"] = structured[:1500]
        else:
            request_record.update(
                {
                    "structured": structured,
                    "complete": parsed["complete"],
                    "required_inputs": parsed["required_inputs"],
                }
            )
            intuition = compose_direction(structured, intuition)
        _save_cycle_checkpoint(
            "request_structured", request=request_record, intuition=intuition
        )

    _progress("conjecture", timings=timings)
    t0 = time.monotonic()
    goal_directed_intuition = (
        "SHARED FINAL OBJECTIVE:\n"
        f"{shared_goal}\n\nCURRENT RESEARCH DIRECTION:\n{intuition}\n\n"
        "For this single cycle, select exactly one bounded, high-information "
        "falsifiable proposition that advances the direction and can be checked "
        "by a compact validator. Develop evidence for both proof and refutation. "
        "Do not combine all program deliverables into one conjecture; state "
        "explicitly what remains deferred or cannot yet be decided."
    )
    deliberation = {}
    if resumed_from:
        conjecture = str(prior_checkpoint["conjecture"])
        deliberation = {
            **(prior_checkpoint.get("deliberation") or {}),
            "resumed_from": resumed_from,
        }
        _progress("conjecture_reused", resumed_from=resumed_from, timings=timings)
    elif len(conj_providers) > 1:
        conjecture, _cu, deliberation = await _ensemble_conjecture(
            conj_providers, axiomatic_base_text, goal_directed_intuition,
            _phase_timeout("CONJECTURE"), synth_provider,
            _phase_models("SYNTH"),
            timeout_for_phase=_phase_timeout,
        )
        ensemble_agents.extend(_cu)
    else:
        _prepare_agent(conj, "CONJECTURE")
        conjecture = await conj.generate_conjecture(
            axiomatic_base=axiomatic_base_text, intuition=goal_directed_intuition)
        deliberation = {
            "proposals": [{"provider": conj_providers[0], "text": conjecture[:6000]}],
            "critiques": [],
            "synthesis_provider": conj_providers[0],
        }
    if not resumed_from:
        _mark("conjecture", t0)
    if isinstance(conjecture, str) and conjecture.startswith("API_ERROR:"):
        return _fail(conjecture, "conjecture")
    _save_cycle_checkpoint(
        "conjecture_complete",
        conjecture=conjecture,
        deliberation=deliberation,
    )

    # Inputs and policy go BEFORE the conjecture: the bounded repairer reads
    # only the first 5000 characters of this text, and it must not re-declare
    # MISSING on the very retry the user's answer was for.
    translation_input = (
        "SHARED FINAL OBJECTIVE:\n"
        f"{shared_goal}\n\n"
        + (extra_inputs + "\n\n" if extra_inputs else "")
        + f"CONSENSUS CONJECTURE TO VALIDATE:\n{conjecture}"
    )
    _progress("translate", timings=timings)
    t0 = time.monotonic()
    _prepare_agent(trans, "TRANSLATOR")
    code = await trans.translate_to_code(translation_input)
    _mark("translate", t0)
    if isinstance(code, str) and code.startswith("API_ERROR:") and "timeout tras" in code:
        # Timeout de GENERACION (scripts de fisica enormes): un reintento
        # pidiendo script MINIMO antes de rendirse — verificar los claims
        # decisivos, no transcribir el formalismo completo.
        _progress("translate_retry_minimal", timings=timings)
        # El reintento pide un script MINIMO (<150 lineas); su timeout tambien
        # se recorta contra el presupuesto global restante.
        trans.cli_timeout = min(_phase_timeout("TRANSLATOR"), 360)
        t0 = time.monotonic()
        code = await trans.translate_to_code(
            translation_input, is_correction=True,
            previous_error=("Your previous translation attempt exceeded its time budget "
                            "(the generated script was too long). Produce a MINIMAL "
                            "script (<150 lines): verify only the 2-4 DECISIVE claims "
                            "of the conjecture using the CHECK protocol, factor repeated "
                            "structure into functions, do NOT transcribe the full formalism."))
        _mark("translate", t0)
    if isinstance(code, str) and code.startswith("API_ERROR:"):
        return _fail(code, "translator", conjecture_text=conjecture)
    _save_cycle_checkpoint(
        "translation_complete",
        conjecture=conjecture,
        deliberation=deliberation,
        code=code,
    )
    code, code_review, review_error = await _review_or_revise(
        code, review_conjecture_prefix + conjecture, translation_input
    )
    if review_error:
        out = _fail(
            review_error,
            review_failure_phase.get("phase", "reviewer"),
            conjecture_text=conjecture,
        )
        out["code"] = code
        out["code_review"] = code_review
        out["code_review_history"] = review_history
        out["validator_preflight_history"] = preflight_history
        out["validator_local_repair_history"] = local_repair_history
        out["validator_model_patch_history"] = model_patch_history
        out["review_defect_trace"] = defect_trace
        out["deliberation"] = deliberation
        _save_cycle_checkpoint(
            out["status"].lower(),
            code=code,
            code_review=code_review,
            code_review_history=review_history,
            validator_preflight_history=preflight_history,
            validator_local_repair_history=local_repair_history,
            validator_model_patch_history=model_patch_history,
            review_defect_trace=defect_trace,
        )
        return out
    _save_cycle_checkpoint(
        "review_complete",
        code=code,
        code_review=code_review,
        code_review_history=review_history,
        validator_preflight_history=preflight_history,
        validator_local_repair_history=local_repair_history,
        validator_model_patch_history=model_patch_history,
        review_defect_trace=defect_trace,
    )
    # exec_timeout opcional del request: calculos pesados legitimos (sweeps,
    # GPU en ASTRUM) pueden necesitar mas que el ASTRA_ORACLE_TIMEOUT del .env.
    try:
        exec_t = int(req.get("exec_timeout") or 0) or None
    except (TypeError, ValueError):
        exec_t = None

    requested_exec_t = exec_t
    if requested_exec_t is None:
        try:
            requested_exec_t = int(
                str(os.environ.get("ASTRA_ORACLE_TIMEOUT", "180"))
                .strip()
                .strip("'\"")
            )
        except ValueError:
            requested_exec_t = 180
    effective_exec_t = budget.phase_timeout(
        requested_exec_t,
        default_seconds=180,
    )
    _progress(
        "execute",
        timings=timings,
        budget=budget.snapshot(),
        timeout=effective_exec_t,
    )
    t0 = time.monotonic()
    exec_result = await execute_python_code(code, timeout=effective_exec_t)
    _mark("execute", t0)
    exec_result["validation_code"] = code
    exec_result["code_review"] = code_review
    exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
    exec_result["guard"] = assess_verdict(code, exec_result)
    _save_cycle_checkpoint(
        "execution_complete",
        execution=exec_result,
    )
    _progress("analyze", timings=timings)
    t0 = time.monotonic()
    analysis = await _run_analysis(review_conjecture_prefix + conjecture, exec_result)
    _mark("analyze", t0)
    analysis = _apply_guard(analysis, exec_result)
    # Non-decidable with these inputs (core/non_decidable.py): the validator's
    # own declaration decides whether the retry loop below is even worth it.
    nd_declaration = detect_non_decidable(exec_result)
    nd_declarations = 1 if nd_declaration else 0
    max_retries = max(0, int(os.environ.get("ASTRA_MAX_RETRIES", "2").strip().strip("'\"")))
    analysis = resolve_non_decidable(
        analysis, nd_declaration, nd_declarations, retry_available=max_retries > 0
    )
    _save_cycle_checkpoint(
        "analysis_complete",
        analysis=analysis,
    )

    # Reintentos: primero arreglos MECANICOS deterministas (gratis), luego el
    # traductor corrige (error matematico) o refuerza (WEAK_PASS del auditor).
    retries = 0
    autofixes = 0
    while analysis.get("status") in ("CODE_ERROR", "WEAK_PASS") and retries < max_retries:
        retries += 1
        _progress("retry", n=retries, status=analysis.get("status"), timings=timings)
        # Escalada por CALIDAD (2026-07-31): el guard rechazo lo que produjo el
        # peldano actual del traductor -> el retry (y el model-patch de vnext,
        # que usa el mismo agente) arranca en el peldano superior. Sin esto, con
        # la escalera invertida ('sonnet,opus') el retry repetia con sonnet y
        # Opus no se pagaba nunca, ni siquiera cuando hacia falta.
        new_rung = _escalate_for_quality(
            "post_oracle_retry",
            analysis.get("status"),
        )
        if new_rung:
            quality_escalations[-1]["retry"] = retries
        if analysis.get("status") == "WEAK_PASS":
            reasons = "; ".join((exec_result.get("guard") or {}).get("reasons") or [])
            correction = (
                "The script printed VERDICT: PASS but the deterministic auditor "
                f"rejected it: {reasons}. Add the missing independent CHECK legs "
                "and a real, reachable VERDICT: FAIL branch without changing "
                "sound validation code."
            )[:2000]
            if validator_repair_vnext1:
                code, patch_error = await _request_model_patch(
                    code,
                    translation_input,
                    correction,
                    "post_execution_weak_pass",
                )
                if patch_error:
                    out = _fail(
                        patch_error,
                        "translator_retry",
                        conjecture_text=conjecture,
                    )
                    out["validator_model_patch_history"] = model_patch_history
                    return out
            else:
                t0 = time.monotonic()
                _prepare_agent(trans, "TRANSLATOR")
                code = await trans.translate_to_code(
                    translation_input,
                    is_correction=True,
                    previous_error=correction,
                    previous_code=code,
                )
                _mark("translate", t0)
        else:
            fixed = try_autofix(code, exec_result.get("stderr") or "")
            if fixed:
                autofixes += 1
                code = fixed
            else:
                # Codex diagnoses and reviews; Claude remains the code author.
                err_ctx = (
                    (exec_result.get("stderr") or "")
                    + "\n--- stdout tail ---\n"
                    + (exec_result.get("stdout") or "")[-800:]
                    + "\n--- Codex analyst diagnosis ---\n"
                    + str(analysis.get("reasoning") or "")
                ).strip()
                if validator_repair_vnext1:
                    code, patch_error = await _request_model_patch(
                        code,
                        translation_input,
                        err_ctx[:3000],
                        "post_execution_code_error",
                    )
                    if (
                        patch_error
                        and analysis.get("non_decidable")
                        and not patch_error.startswith("API_ERROR:")
                    ):
                        # The author cannot patch in data the request lacks
                        # (CANNOT_PATCH / not applicable): that confirms the
                        # declaration. Finalize NON_DECIDABLE, not TOOL_ERROR.
                        analysis = resolve_non_decidable(
                            analysis, nd_declaration, nd_declarations, retry_available=False
                        )
                        break
                    if patch_error:
                        out = _fail(
                            patch_error,
                            "translator_retry",
                            conjecture_text=conjecture,
                        )
                        out["validator_model_patch_history"] = model_patch_history
                        return out
                else:
                    t0 = time.monotonic()
                    _prepare_agent(trans, "TRANSLATOR")
                    code = await trans.translate_to_code(
                        translation_input,
                        is_correction=True,
                        previous_error=err_ctx[:3000],
                        previous_code=code,
                    )
                    _mark("translate", t0)
        if isinstance(code, str) and code.startswith("API_ERROR:"):
            return _fail(code, "translator_retry", conjecture_text=conjecture)
        code, code_review, review_error = await _review_or_revise(
            code, review_conjecture_prefix + conjecture, translation_input
        )
        if review_error:
            out = _fail(
                review_error,
                review_failure_phase.get("phase", "reviewer") + "_retry",
                conjecture_text=conjecture,
            )
            out["code"] = code
            out["code_review"] = code_review
            out["code_review_history"] = review_history
            out["validator_preflight_history"] = preflight_history
            out["validator_local_repair_history"] = local_repair_history
            out["validator_model_patch_history"] = model_patch_history
            out["review_defect_trace"] = defect_trace
            out["deliberation"] = deliberation
            _save_cycle_checkpoint(
                out["status"].lower(),
                code=code,
                code_review=code_review,
                code_review_history=review_history,
                validator_preflight_history=preflight_history,
                validator_local_repair_history=local_repair_history,
                validator_model_patch_history=model_patch_history,
                review_defect_trace=defect_trace,
            )
            return out
        t0 = time.monotonic()
        effective_exec_t = budget.phase_timeout(
            requested_exec_t,
            default_seconds=180,
        )
        exec_result = await execute_python_code(code, timeout=effective_exec_t)
        _mark("execute", t0)
        exec_result["validation_code"] = code
        exec_result["code_review"] = code_review
        exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
        exec_result["guard"] = assess_verdict(code, exec_result)
        t0 = time.monotonic()
        analysis = await _run_analysis(review_conjecture_prefix + conjecture, exec_result)
        _mark("analyze", t0)
        analysis = _apply_guard(analysis, exec_result)
        nd_declaration = detect_non_decidable(exec_result)
        if nd_declaration:
            nd_declarations += 1
        # A second declaration ends the cycle whatever the analyst says: the
        # regenerated validator cannot supply data the request lacks.
        analysis = resolve_non_decidable(
            analysis, nd_declaration, nd_declarations, retry_available=retries < max_retries
        )
    retried = retries > 0

    # Estimacion de duracion emitida por el traductor (# ASTRA_EST_RUNTIME: ...).
    est = None
    m_est = re.search(r"#\s*ASTRA_EST_RUNTIME:\s*(short|medium|long)",
                      code or "", re.IGNORECASE)
    if m_est:
        est = m_est.group(1).lower()

    navigation = {}
    navigate_enabled = (
        os.environ.get("ASTRA_NAVIGATE_AFTER_CYCLE", "1")
        .strip()
        .strip("'\"")
        .lower()
        not in ("0", "off", "false")
    )
    if navigate_enabled:
        _progress("navigate", timings=timings)
        t0 = time.monotonic()
        try:
            cycles_since_milestone = int(
                req.get("cycles_since_milestone", 1)
            )
        except (TypeError, ValueError):
            cycles_since_milestone = 1
        thread_summary = req.get("thread_summary") or (
            "Single deliberative ASTRA cycle. "
            f"Conjecture ensemble: {', '.join(conj_providers)}; "
            f"code review: {code_review.get('status')}; "
            f"oracle verdict: {exec_result.get('verdict')}; "
            f"analyst status: {analysis.get('status')}."
        )
        _prepare_agent(navigator, "NAVIGATOR")
        navigation = await navigator.navigate_research(
            macro_question=shared_goal,
            axiomatic_base=req.get("axiomatic_base", ""),
            last_conjecture=conjecture,
            last_status=analysis.get("status") or "UNKNOWN",
            last_reasoning=str(analysis.get("reasoning") or ""),
            thread_summary=thread_summary,
            cycles_since_milestone=cycles_since_milestone,
        )
        _mark("navigate", t0)

    # ASSUMED: lines (input policy 'assume', or a validator declaring its own
    # placeholders) make the verdict conditional: report them and defer their
    # confirmation, so coverage stays partial and scientific_status atomic.
    assumed_inputs = parse_assumed_inputs((exec_result or {}).get("stdout") or "")
    silent_assume = request_record["input_policy"] == "assume" and not assumed_inputs
    if assumed_inputs or silent_assume:
        analysis = dict(analysis)
        deferred_assumed = _normalize_deferred_items(analysis.get("deferred_items"))
        for item in assumed_inputs:
            entry = f"Confirm assumed input: {item}"
            if entry not in deferred_assumed:
                deferred_assumed.append(entry)
        if silent_assume and SILENT_ASSUME_DEFERRED not in deferred_assumed:
            # The user approved placeholders but the validator declared none:
            # the values it used are unknown, so the verdict stays conditional.
            deferred_assumed.append(SILENT_ASSUME_DEFERRED)
        analysis["deferred_items"] = deferred_assumed
    coverage = _goal_coverage(
        shared_goal,
        intuition,
        conjecture,
        analysis,
        navigation,
    )
    analysis["goal_coverage"] = coverage["status"].upper()
    analysis["goal_resolved"] = coverage["goal_resolved"]
    analysis["deferred_items"] = coverage["deferred_items"]

    timings["total"] = round(time.monotonic() - t_start, 2)
    out = {
        "status": analysis.get("status"),
        "atomic_status": coverage["atomic_status"],
        "scientific_status": coverage["scientific_status"],
        "oracle_verdict": exec_result.get("verdict") or "NONE",
        "goal_coverage": coverage,
        "deferred_claims": coverage["deferred_items"],
        "shared_goal": shared_goal,
        "retried": retried,
        "retries": retries,
        "autofixed": autofixes,
        "timings": timings,
        "deliberation": deliberation,
        "conjecture": conjecture,
        "code": code,
        "code_review": code_review,
        "code_review_history": review_history,
        "validator_preflight_history": preflight_history,
        "validator_local_repair_history": local_repair_history,
        "validator_model_patch_history": model_patch_history,
        "review_defect_trace": defect_trace,
        "validator_repair": {
            "enabled": validator_repair_vnext,
            "strategy": (
                "local-patch-vnext.1"
                if validator_repair_vnext1
                else (
                    "legacy-vnext.0"
                    if validator_repair_vnext
                    else "classic"
                )
            ),
            "local_repairs": sum(
                len(item.get("repairs") or [])
                for item in local_repair_history
            ),
            "model_patches": sum(
                item.get("status") == "APPLIED"
                for item in model_patch_history
            ),
        },
        "execution": exec_result,
        "analysis": analysis,
        "navigation": navigation,
        "oracle_used": os.environ.get("ASTRA_ORACLE_MODE", "local"),
        "providers": providers_resolved,
        "architecture": production_manifest(),
        "cache_key": ckey,
    }
    if est:
        out["est_runtime"] = est
    if analysis.get("non_decidable"):
        out["non_decidable"] = analysis["non_decidable"]
        out["missing_inputs"] = list(analysis.get("missing_inputs") or [])
    if analysis.get("status") == "NON_DECIDABLE":
        # Ask instead of stop: the calling agent puts this to the user.
        out["input_request"] = build_input_request(
            out.get("missing_inputs") or [], checkpoint_path, req
        )
    out["input_policy"] = request_record["input_policy"]
    if request_record.get("inputs"):
        out["inputs"] = request_record["inputs"]
    if assumed_inputs or silent_assume:
        out["assumed_inputs"] = assumed_inputs
        out["conditional_on_assumptions"] = True
    if resumed_from:
        out["resumed_from"] = resumed_from
    if request_record["structure_request"] or request_record.get("resume_warning"):
        out["request"] = request_record
    warnings, cli_models, cli_costs, cli_accounts = _cli_meta(agents + ensemble_agents)
    if request_record.get("resume_warning"):
        warnings = list(warnings or []) + [request_record["resume_warning"]]
    if request_record.get("inputs_truncated"):
        warnings = list(warnings or []) + [
            "inputs were truncated at 20000 characters; pass a smaller extract"
        ]
    if warnings:
        out["warnings"] = warnings      # avisos de cuota/fallback de los CLIs
    if cli_models:
        out["cli_models"] = cli_models  # modelo que realmente respondio cada fase
    if cli_costs:
        # coste proxy por agente (USD segun el CLI de claude; codex/agy no lo
        # reportan y van a 0). Telemetria para la auditoria de cuota, NO cargo real.
        out["cli_cost_usd"] = {**cli_costs,
                               "total": round(sum(cli_costs.values()), 4)}
    if cli_accounts:
        out["cli_account_profiles"] = cli_accounts
    if quality_escalations:
        out["quality_escalations"] = quality_escalations
    if est == "long" and not exec_t:
        out.setdefault("warnings", []).append(
            "El traductor estima computo LARGO (>10 min): considera correrlo como "
            "ciclo persistente (astra_cycle_submit), o usa astra_submit para "
            "solo la ejecucion pesada.")
    out["budget"] = budget.snapshot()
    out["checkpoint"] = checkpoint_path
    if use_cache and out.get("status") in ("VALIDATED", "REFUTED"):
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception:
            pass
    _save_cycle_checkpoint("done", result=out)
    _progress("done", status=out.get("status"), timings=timings)
    return out


async def _do_cycle(req: dict) -> dict:
    """Admit one full cycle per configured model-account slot.

    Independent branches inside a cycle remain parallel.  Separate complete
    cycles are serialized by default because they share the same Codex, Claude
    and AGY subscriptions and otherwise make each other's latency unpredictable.
    """
    from core.astra_identity import banner
    banner("cycle")
    from pathlib import Path

    from core.runtime_resources import (
        acquire_cycle_slot,
        detect_compute_capacity,
        recommended_parallelism,
    )

    capacity = detect_compute_capacity()
    plan = recommended_parallelism(capacity)
    max_slots = max(1, int(plan["deliberative_cycles"]))
    try:
        wait_seconds = max(0, int(req.get("wait_for_cycle_slot_seconds") or 0))
    except (TypeError, ValueError):
        wait_seconds = 0
    wait_started = time.monotonic()
    active = []
    slot = None
    while slot is None:
        slot, active = acquire_cycle_slot(Path(__file__).resolve().parent, max_slots)
        if slot is not None:
            break
        if time.monotonic() - wait_started >= wait_seconds:
            return {
                "status": "BUSY",
                "error": (
                    "Another full ASTRA deliberative cycle is already using the "
                    "shared model-account set."
                ),
                "active_cycles": active,
                "capacity": capacity,
                "parallelism": plan,
                "retry_hint": (
                    "Poll the active cycle, retry later, or use astra_cycle_submit "
                    "to queue a persistent cycle."
                ),
            }
        _progress(
            "queued",
            active_cycles=active,
            waited_s=round(time.monotonic() - wait_started, 1),
        )
        await asyncio.sleep(min(5, max(1, wait_seconds)))

    # Apply MAX mode here (once, outside _do_cycle_impl) and restore it in the
    # finally, so its env overrides are undone even when this cycle runs
    # in-process (e.g. a campaign step) instead of in a throwaway subprocess.
    max_snapshot = apply_max_mode(req)
    try:
        result = await _do_cycle_impl(req)
        if isinstance(result, dict):
            result.setdefault("capacity", capacity)
            result.setdefault("parallelism", plan)
        return result
    except Exception as exc:
        # An escaping exception used to leave the heartbeat at its last
        # phase forever (a "running" window, a "killed" row in telemetry).
        _progress("failed", phase="exception", error=f"{type(exc).__name__}: {exc}"[:500])
        raise
    finally:
        restore_max_mode(max_snapshot)
        slot.release()
        global _ACTIVE_CYCLE_CHECKPOINT
        _ACTIVE_CYCLE_CHECKPOINT = None


def main() -> None:
    try:
        req = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"error": f"JSON de entrada invalido: {e}"}))
        return

    action = req.get("action")
    try:
        if action == "execute":
            out = asyncio.run(_do_execute(req))
        elif action == "engines":
            out = asyncio.run(_do_engines(req))
        elif action == "review":
            out = asyncio.run(_do_review(req))
        elif action == "client_validate":
            out = asyncio.run(_do_client_validate(req))
        elif action == "cycle":
            out = asyncio.run(_do_cycle(req))
        elif action == "submit":
            out = _do_submit(req)
        elif action == "cycle_submit":
            out = _do_submit_cycle(req)
        elif action == "job":
            out = _do_job(req)
        elif action == "capacity":
            out = _do_capacity()
        elif action == "cluster_submit":
            out = asyncio.run(_do_cluster_submit(req))
        elif action == "cluster_job":
            out = asyncio.run(_do_cluster_job(req))
        elif action == "cluster_cancel":
            out = asyncio.run(_do_cluster_cancel(req))
        elif action == "cluster_capacity":
            out = asyncio.run(_do_cluster_capacity())
        else:
            out = {"error": f"accion desconocida: {action}"}
    except Exception as e:
        out = {"error": f"{type(e).__name__}: {e}"}

    print(json.dumps(out))


if __name__ == "__main__":
    main()
