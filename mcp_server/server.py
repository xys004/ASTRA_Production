"""
ASTRA MCP server — expone ASTRA como herramientas para CUALQUIER agente
(Claude Code, Codex, Gemini CLI, Claude Desktop) via Model Context Protocol.

Corre en Python 3.12 (el SDK de MCP necesita >=3.10). Habla con el core de ASTRA
(venv 3.9) por subprocess a traves de astra_tool.py -> versiones desacopladas.

La idea: tu agente favorito se vuelve tu enlace a ASTRA. El agente RAZONA
(conjetura, navega) y llama a estas tools para VERIFICAR con computo real en
ASTRUM (tu RTX 3080) o local.
"""
import json
import os
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

mcp = FastMCP("astra")


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
    )
    try:
        out, err = proc.communicate(input=json.dumps(req), timeout=timeout)
    except subprocess.TimeoutExpired:
        pid = proc.pid
        # taskkill /T: matar el ARBOL (astra_tool -> powershell -> claude/node).
        # proc.kill() solo mataria a astra_tool y dejaria un claude -p huerfano
        # quemando cuota (bug real observado tras cada timeout externo).
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
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
def astra_execute(code: str, oracle: str = "local", timeout: int = 180) -> str:
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
    res = _call_astra(
        {"action": "execute", "code": code, "oracle": oracle, "timeout": timeout},
        timeout=timeout + 60,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
def astra_cycle(intuition: str, oracle: str = "local", timeout: int = 1500,
                exec_timeout: int = 0, objective: str = "") -> str:
    """
    Run ASTRA's FULL deliberative multi-model pipeline and return a verdict.

    Codex and agy propose and cross-critique hypotheses against a shared final
    objective; Codex synthesizes the consensus. Claude writes the falsifiable
    validation program, Codex independently reviews it, the selected oracle
    executes it, Codex audits the evidence, and agy proposes the next direction.
    Use astra_execute when YOU wrote the code and only need the oracle.

    Slower than astra_execute (several model calls, ~1-4 min).

    Args:
        intuition: the current hypothesis or research direction (LaTeX/plain text ok).
        objective: optional overarching scientific goal shared by all three
            models. When empty, intuition is also used as the final objective.
        oracle: 'local' (default), 'astrum' (opt-in, remote GPU), or 'auto'.
        timeout: seconds for the WHOLE cycle (default 1500; the client wall is
            tool_timeout_sec=1800 in Codex). Heavy-physics translation is SLOW
            by nature (~350-700s measured): a 15-25 min cycle is normal, poll
            astra_probe meanwhile. If the translator still times out, the reply
            includes the paid-for 'conjecture' — translate it yourself and use
            astra_execute.
        exec_timeout: seconds for the EXECUTION phase only (0 = .env default,
            usually 180). Raise it for legitimately heavy computation (sweeps,
            GPU runs on ASTRUM) and keep timeout > exec_timeout + 400.

    Returns JSON: status, shared_goal, deliberation, conjecture, code_review,
    code, execution (stdout/verdict), analysis, navigation, providers, and
    timings (seconds per phase); plus 'warnings'/'cli_models' when a
    CLI model hit its usage limit and a fallback served the phase. Each internal
    CLI call is capped at ASTRA_CLI_TIMEOUT (240s default), so a hung phase fails
    alone with API_ERROR + phase name instead of eating the whole budget; if the
    outer timeout still fires, the error includes 'last_progress' (the phase the
    cycle died in).
    """
    req = {"action": "cycle", "intuition": intuition, "oracle": oracle}
    if objective.strip():
        req["objective"] = objective.strip()
    if exec_timeout and exec_timeout > 0:
        req["exec_timeout"] = int(exec_timeout)
    res = _call_astra(req, timeout=timeout)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
def astra_submit(code: str, oracle: str = "local", max_seconds: int = 86400) -> str:
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
    res = _call_astra({"action": "submit", "code": code, "oracle": oracle,
                       "max_seconds": max_seconds}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
def astra_job(job_id: str = "") -> str:
    """
    Poll an async job started with astra_submit — without disturbing it.

    Returns status (queued/running/done/failed/killed), heartbeat age, elapsed
    seconds, a LIVE stdout tail (local python jobs stream their output), and the
    final result (verdict, exit_code, duration_s) once finished. Empty job_id
    lists the 10 most recent jobs. Poll every 1-5 min on long runs; a running
    job with a fresh heartbeat is healthy even if stdout is quiet.
    """
    res = _call_astra({"action": "job", "job_id": job_id}, timeout=60)
    return json.dumps(res, indent=2, ensure_ascii=False)


def _pid_alive(pid) -> bool:
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
    hang: model phases take 30-240s each (cold CLI starts included) and heavy
    computations legitimately run up to exec_timeout. Zero cost, instant, safe
    to poll every ~60s.

    Returns JSON: in_flight (pid, stage, seconds since last heartbeat, partial
    timings), recent (finished/killed cycles with final stage), and a hint.
    """
    import glob
    now = time.time()
    in_flight, recent = [], []
    for f in sorted(glob.glob(os.path.join(ASTRA_ROOT, "workspace", "progress", "cycle_*.json")),
                    key=os.path.getmtime, reverse=True)[:12]:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        d["age_s"] = round(max(0.0, now - d.get("ts", 0)), 1)
        d["alive"] = _pid_alive(d.get("pid", -1))
        if d.get("stage") in ("done", "failed") or not d["alive"]:
            recent.append(d)
        else:
            in_flight.append(d)
    if in_flight:
        top = in_flight[0]
        hint = (f"ASTRA esta TRABAJANDO: fase '{top.get('stage')}' (heartbeat hace "
                f"{top.get('age_s')}s). Las fases de modelo tardan 30-240s y la ejecucion "
                f"hasta su exec_timeout. Sondea de nuevo en ~60s antes de asumir cuelgue.")
    elif recent:
        hint = (f"No hay ciclos en vuelo. El ultimo termino en stage '{recent[0].get('stage')}'"
                + ("" if recent[0].get("stage") in ("done", "failed")
                   else " (proceso muerto: probable kill por timeout externo)"))
    else:
        hint = "Sin rastros de ciclos (directorio de progreso vacio)."
    return json.dumps({"in_flight": in_flight, "recent": recent[:5], "hint": hint},
                      indent=2, ensure_ascii=False)


@mcp.tool()
def astra_status() -> str:
    """
    Health check for ASTRA: confirms whether ASTRUM (the remote GPU workstation)
    is reachable right now and reports its hostname. Call this before a heavy run.
    """
    res = _call_astra(
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


if __name__ == "__main__":
    mcp.run()  # transporte stdio (lo que usan los CLIs de agentes)
