import asyncio
import os
import re
import subprocess
import sys
import uuid
import logging
from core.engine_router import detect_engine, execute_external_cas

logger = logging.getLogger("ASTRA_CORE.executor")


def _decide_oracle(code: str) -> str:
    """Modo AUTO ('que decidan los modelos'): honra un marcador explicito
    '# ASTRA_ORACLE: remote|local' que el traductor puede poner; si no hay,
    heuristica -> GPU/computo pesado va a ASTRUM, simbolico ligero va local."""
    m = re.search(r"#\s*ASTRA_ORACLE\s*:\s*(remote|local)", code, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    c = code.lower()
    heavy = ("import torch", "import cupy", "import jax", "cuda", "@njit",
             "prange", "differential_evolution", "workers=-1", "multiprocessing",
             "gpu")
    return "remote" if any(k in c for k in heavy) else "local"

async def execute_python_code(code: str, workspace_dir: str = "workspace", timeout: int = 60) -> dict:
    """
    Saves the Python code in the workspace and executes it asynchronously in an isolated subprocess.
    Captures standard output, error, and respects a timeout to prevent infinite loops in solvers.
    """
    timeout = int(os.environ.get("ASTRA_ORACLE_TIMEOUT", timeout))

    mode = os.environ.get("ASTRA_ORACLE_MODE", "local").strip().lower()
    if mode == "auto":
        mode = _decide_oracle(code)
        logger.info("Oracle AUTO -> %s", mode)
    if mode == "remote":
        from core.remote_executor import execute_remote_code
        return await execute_remote_code(code, timeout=timeout)

    workspace_dir = os.path.abspath(workspace_dir)
    os.makedirs(workspace_dir, exist_ok=True)
    engine = detect_engine(code)

    if engine in {"sage", "maxima", "cadabra"}:
        logger.info(f"Oracle routing script to external CAS: {engine}")
        return execute_external_cas(code, engine, workspace_dir, timeout)

    # Generate a unique filename to avoid async collisions
    filename = f"astra_exec_{uuid.uuid4().hex[:8]}.py"
    filepath = os.path.join(workspace_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

    logger.info(f"Oracle validating script: {filepath}")

    try:
        def _run_script():
            return subprocess.run(
                [sys.executable, filepath],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

        try:
            result = await asyncio.to_thread(_run_script)
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout of {timeout}s exceeded in {filepath}")
            return {
                "stdout": "",
                "stderr": f"TimeoutError: The Python solver exceeded the limit of {timeout} seconds (possible infinite loop or intractable computation).",
                "exit_code": 124
            }

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }

    except Exception as e:
        logger.error(f"Structural failure invoking the subprocess: {e}")
        return {
            "stdout": "",
            "stderr": f"SystemError: Failed to launch python in {filepath} -> {str(e)}",
            "exit_code": -1
        }
    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass
