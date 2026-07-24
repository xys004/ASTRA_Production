import asyncio
import json
import logging
import os
import re
import shlex
import subprocess

logger = logging.getLogger("ASTRA_CORE.remote_executor")


def _split_ssh_options(raw: str) -> list[str]:
    if not raw:
        return []
    parts = shlex.split(raw, posix=False if os.name == "nt" else True)
    return [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in parts]


def _quote_remote_arg(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./~:+-]+", value):
        return value
    return shlex.quote(value)


async def execute_remote_code(code: str, timeout: int = 60) -> dict:
    """
    Execute oracle validation code on a remote Linux worker over SSH.

    The remote side runs a small ASTRA worker script that receives JSON on stdin
    and returns JSON with stdout, stderr, exit_code, and engine metadata.
    """
    host = os.environ.get("ASTRA_REMOTE_HOST", "").strip()
    if not host:
        return {
            "stdout": "",
            "stderr": "RemoteExecutionError: ASTRA_REMOTE_HOST is not configured.",
            "exit_code": -10,
            "engine": "remote",
        }

    remote_python = os.environ.get("ASTRA_REMOTE_PYTHON", "python3").strip()
    remote_worker = os.environ.get("ASTRA_REMOTE_WORKER", "~/astra-worker/astra_remote_worker.py").strip()
    remote_workdir = os.environ.get("ASTRA_REMOTE_WORKDIR", "~/astra-worker/workspace").strip()
    connect_timeout = int(os.environ.get("ASTRA_REMOTE_CONNECT_TIMEOUT", "15"))
    ssh_options = _split_ssh_options(os.environ.get("ASTRA_REMOTE_SSH_OPTIONS", ""))

    payload = json.dumps(
        {
            "code": code,
            "timeout": timeout,
            "workdir": remote_workdir,
        }
    )

    # Win32-OpenSSH (System32) muere con exit 255 y CERO output cuando el proceso
    # padre no tiene consola (caso: server MCP lanzado por el host de Claude).
    # ASTRA_REMOTE_SSH_BIN permite apuntar a un ssh que no la necesite (p.ej. el de Git).
    ssh_bin = os.environ.get("ASTRA_REMOTE_SSH_BIN", "").strip() or "ssh"

    remote_cmd = f"{_quote_remote_arg(remote_python)} {_quote_remote_arg(remote_worker)}"
    cmd = [
        ssh_bin,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        *ssh_options,
        host,
        remote_cmd,
    ]

    logger.info("Oracle routing script to remote worker: %s", host)

    try:
        def _run_remote():
            return subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout + connect_timeout + 10,
            )

        result = await asyncio.to_thread(_run_remote)
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"TimeoutError: Remote oracle exceeded {timeout} seconds.",
            "exit_code": 124,
            "engine": "remote",
        }
    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": "RemoteExecutionError: ssh executable was not found on this machine.",
            "exit_code": -11,
            "engine": "remote",
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": f"RemoteExecutionError: Failed to launch ssh remote worker -> {exc}",
            "exit_code": -12,
            "engine": "remote",
        }

    if result.returncode != 0:
        return {
            "stdout": result.stdout,
            "stderr": result.stderr or f"ssh exited with code {result.returncode}",
            "exit_code": result.returncode,
            "engine": "remote",
        }

    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "stdout": result.stdout,
            "stderr": result.stderr or "RemoteExecutionError: Worker returned non-JSON output.",
            "exit_code": -13,
            "engine": "remote",
        }

    response.setdefault("engine", "remote")
    response["remote_host"] = host
    if result.stderr:
        response["ssh_stderr"] = result.stderr
    return response
