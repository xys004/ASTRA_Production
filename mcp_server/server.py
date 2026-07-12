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

from mcp.server.fastmcp import FastMCP

# --- Rutas al core de ASTRA (venv 3.9) ---
ASTRA_ROOT = r"C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production"
ASTRA_PY = os.path.join(ASTRA_ROOT, "venv", "Scripts", "python.exe")
ASTRA_TOOL = os.path.join(ASTRA_ROOT, "astra_tool.py")

mcp = FastMCP("astra")


def _call_astra(req: dict, timeout: int = 300) -> dict:
    """Invoca astra_tool.py (venv 3.9) con una peticion JSON y parsea la respuesta."""
    try:
        proc = subprocess.run(
            [ASTRA_PY, ASTRA_TOOL],
            input=json.dumps(req), text=True, encoding="utf-8", errors="replace",
            capture_output=True, cwd=ASTRA_ROOT, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return {"error": f"astra_tool timeout tras {timeout}s"}
    if proc.returncode != 0:
        return {"error": f"astra_tool exit {proc.returncode}", "stderr": (proc.stderr or "")[-600:]}
    lines = [l for l in (proc.stdout or "").strip().splitlines() if l.strip()]
    if not lines:
        return {"error": "astra_tool no devolvio salida", "stderr": (proc.stderr or "")[-600:]}
    try:
        return json.loads(lines[-1])   # ultima linea = objeto JSON
    except Exception as e:
        return {"error": f"parseo JSON fallo: {e}", "raw": (proc.stdout or "")[-600:]}


@mcp.tool()
def astra_execute(code: str, oracle: str = "astrum", timeout: int = 180) -> str:
    """
    Run a verification script through ASTRA's oracle and return real results.

    Use this to VERIFY a physics/math hypothesis with actual computation instead
    of trusting an LLM's judgment. Write a self-contained script (sympy, einsteinpy,
    z3, scipy, numpy, qutip, pint, ... or a Sage/Maxima/Cadabra script with a
    '# ASTRA_ENGINE: sage' marker) that prints its evidence and ends with a line
    'VERDICT: PASS' or 'VERDICT: FAIL'.

    Args:
        code: the full script to execute.
        oracle: where to run it — 'astrum' (remote GPU workstation, default),
                'local', or 'auto' (the model may tag the code with
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
def astra_cycle(intuition: str, oracle: str = "astrum", timeout: int = 420) -> str:
    """
    Run ASTRA's FULL multi-model pipeline on a scientific intuition and return a verdict.

    ASTRA forms a falsifiable conjecture (Codex), translates it into a verification
    script (Claude), runs it on the oracle (ASTRUM by default), and analyzes the
    output into VALIDATED / REFUTED / CODE_ERROR. Use this when you want ASTRA to
    drive the whole loop; use astra_execute when YOU wrote the code and just need it run.

    Slower than astra_execute (several model calls, ~1-4 min).

    Args:
        intuition: the hypothesis or research prompt (LaTeX/plain text ok).
        oracle: 'astrum' (default), 'local', or 'auto'.
        timeout: seconds (default 420).

    Returns JSON: status, conjecture, code, execution (stdout/verdict), analysis, providers.
    """
    res = _call_astra(
        {"action": "cycle", "intuition": intuition, "oracle": oracle},
        timeout=timeout,
    )
    return json.dumps(res, indent=2, ensure_ascii=False)


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
