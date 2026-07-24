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


def _verdict(stdout: str) -> str:
    up = (stdout or "").upper()
    if "VERDICT: PASS" in up:
        return "PASS"
    if "VERDICT: FAIL" in up:
        return "FAIL"
    return "NONE"


def _progress_path(pid=None):
    root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "workspace", "progress", f"cycle_{pid or os.getpid()}.json")


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
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "stage": stage, "ts": time.time(), **extra}, f)
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
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace", "jobs")


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
                                 ("id", "status", "oracle", "verdict",
                                  "elapsed_s", "heartbeat_age_s")})
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
    """Junta los avisos de cuota (escalera de cli_backend) y que modelo CLI
    respondio cada fase, para exponerlos en el JSON del ciclo."""
    warnings, models = [], {}
    for name, ag in agents:
        warnings.extend(getattr(ag, "cli_warnings", []) or [])
        m = getattr(ag, "cli_last_model", None)
        if m:
            models[name] = m
    return warnings, models


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
    res["verdict"] = _verdict(res.get("stdout", ""))
    res["guard"] = assess_verdict(code, res)   # auditoria informativa del PASS
    res["oracle_used"] = os.environ.get("ASTRA_ORACLE_MODE", "local")
    return res


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
# criticas + 1 merge + codigo + 2 analisis); aun con las paralelas, supera de
# largo el presupuesto SINCRONO del MCP (~800-900s). Correrlo por _do_cycle DIRECTO
# fuera del MCP (sin muro de timeout):
#   echo '{"action":"cycle","intuition":"...","oracle":"local"}' | python astra_tool.py
# o subir los presupuestos del MCP. NO sirve astra_submit: solo ejecuta CODIGO,
# no ciclos. Un solo proveedor por fase => camino lineal clasico, sin coste extra.
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
_ANALYST_RANK = {"REFUTED": 4, "CODE_ERROR": 3, "WEAK_PASS": 2, "VALIDATED": 1}


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


async def _ensemble_conjecture(providers, axiomatic_base, intuition, phase_timeout,
                               synth_provider):
    """Conjetura multi-modelo: propuestas en paralelo -> critica cruzada -> merge.
    Devuelve (conjetura_final, [(label, ASTRAIntelligence)] para _cli_meta)."""
    from core.llm_client import ASTRAIntelligence
    ais = [ASTRAIntelligence(provider=p, cli_models=None, cli_timeout=phase_timeout)
           for p in providers]
    gens = await asyncio.gather(
        *[a.generate_conjecture(axiomatic_base=axiomatic_base, intuition=intuition)
          for a in ais], return_exceptions=True)
    used = [("conjecture:%s" % p, a) for p, a in zip(providers, ais)]
    surv = [(p, _clean_text(g), a) for p, a, g in zip(providers, ais, gens)]
    surv = [(p, t, a) for (p, t, a) in surv if t]
    if not surv:
        return (
            "API_ERROR: todas las conjeturas del ensemble fallaron",
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
        rivals = "\n\n".join("=== RIVAL %s (%s) ===\n%s" % (chr(65 + j), surv[j][0], surv[j][1])
                             for j in range(len(surv)) if j != i)
        return await a_i._call_api(
            _CRITIQUE_SYSTEM,
            "Tu propia propuesta fue:\n%s\n\nAhora critica adversarialmente la(s) "
            "propuesta(s) RIVAL(es):\n\n%s" % (t_i, rivals))

    crits = await asyncio.gather(*[_crit(i) for i in range(len(surv))],
                                 return_exceptions=True)
    synth = ASTRAIntelligence(provider=synth_provider, cli_models=None,
                              cli_timeout=phase_timeout)
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


async def _do_cycle(req: dict) -> dict:
    """Goal-driven multi-model cycle with deliberation, review and navigation."""
    from core.preflight import phase_provider_map
    from core.llm_client import ASTRAIntelligence
    from core.executor import execute_python_code
    from core.verdict_guard import assess_verdict
    from core.autofix import try_autofix
    import hashlib

    oracle = (req.get("oracle") or "").strip().lower()
    mode = {"astrum": "remote"}.get(oracle, oracle)
    if mode in ("local", "remote", "auto"):
        os.environ["ASTRA_ORACLE_MODE"] = mode

    intuition = req.get("intuition", "")
    if not intuition.strip():
        return {"error": "intuition vacia"}
    shared_goal = (
        req.get("objective")
        or req.get("macro_question")
        or req.get("shared_goal")
        or intuition
    ).strip()

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
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "workspace", "cycle_cache")
    ckey = hashlib.sha256(json.dumps(
        {"intuition": intuition, "shared_goal": shared_goal,
         "ax": req.get("axiomatic_base", ""),
         "providers": providers_resolved, "oracle": os.environ.get("ASTRA_ORACLE_MODE", "local")},
        sort_keys=True).encode("utf-8")).hexdigest()[:24]
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

    def _mark(name, t0):
        timings[name] = round(timings.get(name, 0.0) + (time.monotonic() - t0), 2)

    _progress("start", oracle=os.environ.get("ASTRA_ORACLE_MODE", "local"))

    def _phase_models(phase):
        # Escalera de modelos POR FASE (ASTRA_TRANSLATOR_MODELS='sonnet,default');
        # si no hay, cli_backend usa la escalera global ASTRA_<CLI>_MODELS.
        v = (os.environ.get(f"ASTRA_{phase}_MODELS")
             or os.environ.get(f"ASTRA_{phase}_MODEL") or "")
        return v.strip().strip("'\"") or None

    def _phase_timeout(phase):
        # Presupuesto por llamada especifico de la fase (p.ej. el TRADUCTOR
        # genera scripts de fisica largos: ASTRA_TRANSLATOR_TIMEOUT=480);
        # sin variable, cli_backend usa ASTRA_CLI_TIMEOUT (240).
        v = (os.environ.get(f"ASTRA_{phase}_TIMEOUT") or "").strip().strip("'\"")
        try:
            return int(v) if v else None
        except ValueError:
            return None

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

    async def _run_analysis(cj, ex):
        # Un solo analista => camino lineal clasico. >=2 => consenso conservador.
        if len(an_providers) > 1:
            a, used = await _ensemble_analysis(
                an_providers, shared_goal, cj, ex, _phase_timeout("ANALYST")
            )
            ensemble_agents.extend(used)
            return a
        return await analyst.analyze_results(cj, ex, shared_goal=shared_goal)

    def _fail(msg, phase, conjecture_text=None):
        out = {"error": msg, "phase": phase}
        if conjecture_text:
            # SALVAVIDAS: si murio el traductor, devolver la conjetura ya pagada
            # para que el agente llamador la traduzca el mismo y use astra_execute.
            out["conjecture"] = conjecture_text
        if timings:
            timings["total"] = round(time.monotonic() - t_start, 2)
            out["timings"] = timings
        warnings, _ = _cli_meta(agents + ensemble_agents)
        if warnings:
            out["warnings"] = warnings
        _progress("failed", phase=phase, timings=timings)
        return out

    review_history = []

    async def _review_or_revise(current_code, conjecture_text, translation_input):
        """Codex audits; Claude remains the sole generative code author."""
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
            max_revisions = max(
                0,
                int(
                    os.environ.get("ASTRA_REVIEW_MAX_REVISIONS", "1")
                    .strip()
                    .strip("'\"")
                ),
            )
        except ValueError:
            max_revisions = 1

        revisions = 0
        while True:
            _progress("review", revision=revisions, timings=timings)
            t0 = time.monotonic()
            review = await reviewer.review_validation_code(
                shared_goal=shared_goal,
                conjecture=conjecture_text,
                code=current_code,
            )
            _mark("review", t0)
            review_history.append(dict(review))
            status = str(review.get("status") or "").upper()
            if status == "APPROVED":
                return current_code, review, None
            if status == "API_ERROR":
                return current_code, review, review.get("reasoning") or "reviewer API error"
            if revisions >= max_revisions:
                return (
                    current_code,
                    review,
                    "Independent reviewer did not approve the validation strategy "
                    f"after {revisions} revision(s): {review.get('reasoning', '')}",
                )

            revisions += 1
            instructions = (
                review.get("revision_instructions")
                or review.get("reasoning")
                or "Regenerate a falsifiable validator with independent checks."
            )
            _progress("review_revision", revision=revisions, timings=timings)
            t0 = time.monotonic()
            current_code = await trans.translate_to_code(
                translation_input,
                is_correction=True,
                previous_error=(
                    "Independent Codex review returned "
                    f"{status}. Revise the validation script without changing the "
                    f"scientific claim. Instructions:\n{instructions}"
                )[:3500],
            )
            _mark("translate", t0)
            if isinstance(current_code, str) and current_code.startswith("API_ERROR:"):
                return current_code, review, current_code

    _progress("conjecture", timings=timings)
    t0 = time.monotonic()
    goal_directed_intuition = (
        "SHARED FINAL OBJECTIVE:\n"
        f"{shared_goal}\n\nCURRENT RESEARCH DIRECTION:\n{intuition}\n\n"
        "Develop evidence for both proof and refutation. State explicitly if the "
        "direction cannot decide the objective."
    )
    deliberation = {}
    if len(conj_providers) > 1:
        conjecture, _cu, deliberation = await _ensemble_conjecture(
            conj_providers, req.get("axiomatic_base", ""), goal_directed_intuition,
            _phase_timeout("CONJECTURE"), synth_provider)
        ensemble_agents.extend(_cu)
    else:
        conjecture = await conj.generate_conjecture(
            axiomatic_base=req.get("axiomatic_base", ""), intuition=goal_directed_intuition)
        deliberation = {
            "proposals": [{"provider": conj_providers[0], "text": conjecture[:6000]}],
            "critiques": [],
            "synthesis_provider": conj_providers[0],
        }
    _mark("conjecture", t0)
    if isinstance(conjecture, str) and conjecture.startswith("API_ERROR:"):
        return _fail(conjecture, "conjecture")

    translation_input = (
        "SHARED FINAL OBJECTIVE:\n"
        f"{shared_goal}\n\nCONSENSUS CONJECTURE TO VALIDATE:\n{conjecture}"
    )
    _progress("translate", timings=timings)
    t0 = time.monotonic()
    code = await trans.translate_to_code(translation_input)
    _mark("translate", t0)
    if isinstance(code, str) and code.startswith("API_ERROR:") and "timeout tras" in code:
        # Timeout de GENERACION (scripts de fisica enormes): un reintento
        # pidiendo script MINIMO antes de rendirse — verificar los claims
        # decisivos, no transcribir el formalismo completo.
        _progress("translate_retry_minimal", timings=timings)
        # El reintento pide un script MINIMO (<150 lineas): medido ~350s para
        # ~190 lineas => 360s bastan y el peor caso del ciclo cabe en la pared
        # del cliente (240+720+360+180+analisis < 1800).
        trans.cli_timeout = min(trans.cli_timeout or 360, 360)
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
    code, code_review, review_error = await _review_or_revise(
        code, conjecture, translation_input
    )
    if review_error:
        out = _fail(review_error, "reviewer", conjecture_text=conjecture)
        out["code"] = code
        out["code_review"] = code_review
        out["deliberation"] = deliberation
        return out
    # exec_timeout opcional del request: calculos pesados legitimos (sweeps,
    # GPU en ASTRUM) pueden necesitar mas que el ASTRA_ORACLE_TIMEOUT del .env.
    try:
        exec_t = int(req.get("exec_timeout") or 0) or None
    except (TypeError, ValueError):
        exec_t = None

    _progress("execute", timings=timings)
    t0 = time.monotonic()
    exec_result = await execute_python_code(code, timeout=exec_t)
    _mark("execute", t0)
    exec_result["validation_code"] = code
    exec_result["code_review"] = code_review
    exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
    exec_result["guard"] = assess_verdict(code, exec_result)
    _progress("analyze", timings=timings)
    t0 = time.monotonic()
    analysis = await _run_analysis(conjecture, exec_result)
    _mark("analyze", t0)
    analysis = _apply_guard(analysis, exec_result)

    # Reintentos: primero arreglos MECANICOS deterministas (gratis), luego el
    # traductor corrige (error matematico) o refuerza (WEAK_PASS del auditor).
    retries = 0
    autofixes = 0
    max_retries = max(0, int(os.environ.get("ASTRA_MAX_RETRIES", "2").strip().strip("'\"")))
    while analysis.get("status") in ("CODE_ERROR", "WEAK_PASS") and retries < max_retries:
        retries += 1
        _progress("retry", n=retries, status=analysis.get("status"), timings=timings)
        if analysis.get("status") == "WEAK_PASS":
            reasons = "; ".join((exec_result.get("guard") or {}).get("reasons") or [])
            t0 = time.monotonic()
            code = await trans.translate_to_code(
                translation_input, is_correction=True,
                previous_error=("The script printed VERDICT: PASS but the deterministic "
                                f"auditor rejected it: {reasons}. Rewrite it with >=3 "
                                "independent CHECK legs (symbolic, random-numeric, limit "
                                "case) and a real, reachable VERDICT: FAIL branch.")[:2000])
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
                t0 = time.monotonic()
                code = await trans.translate_to_code(
                    translation_input,
                    is_correction=True,
                    previous_error=err_ctx[:3000],
                )
                _mark("translate", t0)
        if isinstance(code, str) and code.startswith("API_ERROR:"):
            return _fail(code, "translator_retry", conjecture_text=conjecture)
        code, code_review, review_error = await _review_or_revise(
            code, conjecture, translation_input
        )
        if review_error:
            out = _fail(review_error, "reviewer_retry", conjecture_text=conjecture)
            out["code"] = code
            out["code_review"] = code_review
            out["deliberation"] = deliberation
            return out
        t0 = time.monotonic()
        exec_result = await execute_python_code(code, timeout=exec_t)
        _mark("execute", t0)
        exec_result["validation_code"] = code
        exec_result["code_review"] = code_review
        exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
        exec_result["guard"] = assess_verdict(code, exec_result)
        t0 = time.monotonic()
        analysis = await _run_analysis(conjecture, exec_result)
        _mark("analyze", t0)
        analysis = _apply_guard(analysis, exec_result)
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
            cycles_since_milestone = int(req.get("cycles_since_milestone") or 1)
        except (TypeError, ValueError):
            cycles_since_milestone = 1
        thread_summary = req.get("thread_summary") or (
            "Single deliberative ASTRA cycle. "
            f"Conjecture ensemble: {', '.join(conj_providers)}; "
            f"code review: {code_review.get('status')}; "
            f"oracle verdict: {exec_result.get('verdict')}; "
            f"analyst status: {analysis.get('status')}."
        )
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

    timings["total"] = round(time.monotonic() - t_start, 2)
    out = {
        "status": analysis.get("status"),
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
        "execution": exec_result,
        "analysis": analysis,
        "navigation": navigation,
        "oracle_used": os.environ.get("ASTRA_ORACLE_MODE", "local"),
        "providers": providers_resolved,
    }
    if est:
        out["est_runtime"] = est
    warnings, cli_models = _cli_meta(agents + ensemble_agents)
    if warnings:
        out["warnings"] = warnings      # avisos de cuota/fallback de los CLIs
    if cli_models:
        out["cli_models"] = cli_models  # modelo que realmente respondio cada fase
    if est == "long" and not exec_t:
        out.setdefault("warnings", []).append(
            "El traductor estima computo LARGO (>10 min): considera correrlo como "
            "job asincrono (astra_submit) o repetir el ciclo con exec_timeout mayor.")
    if use_cache and out.get("status") in ("VALIDATED", "REFUTED"):
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception:
            pass
    _progress("done", status=out.get("status"), timings=timings)
    return out


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
        elif action == "cycle":
            out = asyncio.run(_do_cycle(req))
        elif action == "submit":
            out = _do_submit(req)
        elif action == "job":
            out = _do_job(req)
        else:
            out = {"error": f"accion desconocida: {action}"}
    except Exception as e:
        out = {"error": f"{type(e).__name__}: {e}"}

    print(json.dumps(out))


if __name__ == "__main__":
    main()
