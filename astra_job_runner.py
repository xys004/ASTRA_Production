"""
astra_job_runner.py — worker DESACOPLADO para trabajos largos de ASTRA.

Lanzado por astra_tool (accion 'submit') con DETACHED_PROCESS: sobrevive al
astra_tool que lo pario, al server MCP y al cliente (Codex/Claude/Gemini).
Deja TODO en workspace/jobs/<job_id>/:
  job.json    — estado + heartbeat (ts se refresca cada ~5 s mientras corre)
  script.py   — el codigo del job
  stdout.log / stderr.log — salida; para python local se escribe EN VIVO
                (tail-eable por astra_job para ver el progreso)
  result.json — resultado final: stdout, stderr, exit_code, verdict, duration_s

Dos caminos de ejecucion:
  * python local  -> Popen directo con salida a archivo: tail en vivo + heartbeat.
  * sage/maxima/cadabra o oraculo remoto (ASTRUM) -> core.executor sincrono; la
    salida llega al final. Para ASTRUM el runner SOSTIENE el SSH todo el trabajo:
    la laptop debe permanecer despierta (mejora futura: nohup en el remoto).
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.preflight import load_project_env
load_project_env()


def _save(meta: dict, jobdir: str) -> None:
    meta["ts"] = time.time()                 # heartbeat
    tmp = os.path.join(jobdir, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(tmp, os.path.join(jobdir, "job.json"))


def _verdict(stdout: str) -> str:
    up = (stdout or "").upper()
    if "VERDICT: PASS" in up:
        return "PASS"
    if "VERDICT: FAIL" in up:
        return "FAIL"
    return "NONE"


def main(jobdir: str) -> None:
    with open(os.path.join(jobdir, "job.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(jobdir, "script.py"), encoding="utf-8") as f:
        code = f.read()

    meta.update(status="running", pid=os.getpid(), started_ts=time.time())
    _save(meta, jobdir)

    oracle = (meta.get("oracle") or "local").strip().lower()
    mode = {"astrum": "remote"}.get(oracle, oracle)
    if mode in ("local", "remote", "auto"):
        os.environ["ASTRA_ORACLE_MODE"] = mode

    from core.executor import _decide_oracle
    from core.engine_router import detect_engine
    if mode == "auto":
        mode = _decide_oracle(code)
        os.environ["ASTRA_ORACLE_MODE"] = mode
        meta["oracle_resolved"] = mode
        _save(meta, jobdir)

    try:
        max_s = int(meta.get("max_seconds") or 86400)
    except (TypeError, ValueError):
        max_s = 86400

    engine = detect_engine(code)
    outp = os.path.join(jobdir, "stdout.log")
    errp = os.path.join(jobdir, "stderr.log")
    t0 = time.time()

    try:
        if mode != "remote" and engine == "python":
            # Camino rapido: tail en vivo + heartbeat cada 5 s.
            script = os.path.join(jobdir, "script.py")
            ws = os.path.join(ROOT, "workspace")
            with open(outp, "w", encoding="utf-8") as so, \
                 open(errp, "w", encoding="utf-8") as se:
                p = subprocess.Popen(
                    [sys.executable, script], stdout=so, stderr=se, cwd=ws,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                rc = None
                while True:
                    rc = p.poll()
                    if rc is not None:
                        break
                    if time.time() - t0 > max_s:
                        p.kill()
                        try:
                            p.wait(timeout=10)
                        except Exception:
                            pass
                        rc = -9
                        se.write(f"\n[runner] Timeout of {max_s}s exceeded; job killed.")
                        break
                    _save(meta, jobdir)      # heartbeat
                    time.sleep(5)
            with open(outp, encoding="utf-8", errors="replace") as f:
                stdout = f.read()
            with open(errp, encoding="utf-8", errors="replace") as f:
                stderr = f.read()
            res = {"stdout": stdout, "stderr": stderr,
                   "exit_code": rc if rc is not None else -1, "engine": "python"}
        else:
            # Camino general: motores CAS externos u oraculo remoto (ASTRUM).
            import asyncio
            from core.executor import execute_python_code
            res = asyncio.run(execute_python_code(code, timeout=max_s))
            with open(outp, "w", encoding="utf-8") as f:
                f.write(res.get("stdout") or "")
            with open(errp, "w", encoding="utf-8") as f:
                f.write(res.get("stderr") or "")
    except Exception as e:
        res = {"stdout": "", "stderr": f"[runner] {type(e).__name__}: {e}", "exit_code": -1}

    res["verdict"] = _verdict(res.get("stdout"))
    res["duration_s"] = round(time.time() - t0, 2)
    res["oracle_used"] = os.environ.get("ASTRA_ORACLE_MODE", "local")
    with open(os.path.join(jobdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f)

    meta.update(status="done" if res.get("exit_code") == 0 else "failed",
                finished_ts=time.time(), exit_code=res.get("exit_code"),
                verdict=res["verdict"], duration_s=res["duration_s"])
    _save(meta, jobdir)


if __name__ == "__main__":
    main(sys.argv[1])
