"""
astra_tool.py — API por subprocess del core de ASTRA (corre en el venv 3.9).

Recibe una peticion JSON por stdin y devuelve JSON por stdout. Existe para que
procesos EXTERNOS (p.ej. el servidor MCP en Python 3.12) usen el core de ASTRA
sin compartir su entorno Python — igual que el worker remoto: "JSON entra -> JSON sale".

Acciones:
  {"action":"execute","code":"...","oracle":"astrum|local|auto","timeout":180}
      -> ejecuta el codigo via core.executor (respeta local/ASTRUM/auto) y
         devuelve {stdout, stderr, exit_code, engine, verdict, oracle_used}.

Uso:  echo '{"action":"execute","code":"print(1)"}' | python astra_tool.py
"""
import os
import sys
import json
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


async def _do_execute(req: dict) -> dict:
    from core.executor import execute_python_code

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
    res["oracle_used"] = os.environ.get("ASTRA_ORACLE_MODE", "local")
    return res


async def _do_cycle(req: dict) -> dict:
    """Pipeline completo de un ciclo: conjetura -> codigo -> ejecuta -> analiza.
    Usa los proveedores por fase del .env (Codex conjetura, Claude codigo/analisis)."""
    from core.preflight import phase_provider_map
    from core.llm_client import ASTRAIntelligence
    from core.executor import execute_python_code

    oracle = (req.get("oracle") or "").strip().lower()
    mode = {"astrum": "remote"}.get(oracle, oracle)
    if mode in ("local", "remote", "auto"):
        os.environ["ASTRA_ORACLE_MODE"] = mode

    intuition = req.get("intuition", "")
    if not intuition.strip():
        return {"error": "intuition vacia"}

    pmap = phase_provider_map()
    conj = ASTRAIntelligence(provider=pmap["conjecture"])
    trans = ASTRAIntelligence(provider=pmap["translator"])
    analyst = ASTRAIntelligence(provider=pmap["analyst"])

    conjecture = await conj.generate_conjecture(
        axiomatic_base=req.get("axiomatic_base", ""), intuition=intuition)
    if isinstance(conjecture, str) and conjecture.startswith("API_ERROR:"):
        return {"error": conjecture, "phase": "conjecture"}

    code = await trans.translate_to_code(conjecture)
    exec_result = await execute_python_code(code)
    exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
    analysis = await analyst.analyze_results(conjecture, exec_result)

    # Un reintento si el codigo fallo (como el loop web de ASTRA): el traductor corrige.
    retried = False
    if analysis.get("status") == "CODE_ERROR":
        retried = True
        corrected = analysis.get("corrected_code")
        if corrected and "```" in corrected:
            parts = corrected.split("```")
            if len(parts) >= 3:
                corrected = parts[1]
                if corrected.split("\n", 1)[0].strip() in ("python", "sage", "maxima", "cadabra"):
                    corrected = corrected.split("\n", 1)[1]
        if corrected and corrected.strip():
            code = corrected.strip()
        else:
            code = await trans.translate_to_code(
                conjecture, is_correction=True,
                previous_error=(exec_result.get("stderr") or "")[:2000])
        exec_result = await execute_python_code(code)
        exec_result["verdict"] = _verdict(exec_result.get("stdout", ""))
        analysis = await analyst.analyze_results(conjecture, exec_result)

    return {
        "status": analysis.get("status"),
        "retried": retried,
        "conjecture": conjecture,
        "code": code,
        "execution": exec_result,
        "analysis": analysis,
        "oracle_used": os.environ.get("ASTRA_ORACLE_MODE", "local"),
        "providers": pmap,
    }


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
        else:
            out = {"error": f"accion desconocida: {action}"}
    except Exception as e:
        out = {"error": f"{type(e).__name__}: {e}"}

    print(json.dumps(out))


if __name__ == "__main__":
    main()
