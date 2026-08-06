"""SSH client for ASTRUM's persistent shared-job manager."""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import subprocess

from core.remote_executor import _quote_remote_arg, _split_ssh_options


def cluster_enabled() -> bool:
    return os.environ.get("ASTRA_REMOTE_SCHEDULER", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def client_id() -> str:
    return (os.environ.get("ASTRA_CLIENT_ID") or getpass.getuser() or "unknown").strip()


def project_id() -> str:
    return (os.environ.get("ASTRA_PROJECT_ID") or "general").strip()


async def cluster_rpc(request: dict, timeout: int = 60) -> dict:
    host = os.environ.get("ASTRA_REMOTE_HOST", "").strip()
    if not host:
        return {"error": "ASTRA_REMOTE_HOST is not configured."}
    remote_python = os.environ.get("ASTRA_REMOTE_PYTHON", "python3").strip()
    manager = os.environ.get(
        "ASTRA_REMOTE_CLUSTER_MANAGER",
        "~/astra-worker/astra_cluster_manager.py",
    ).strip()
    connect_timeout = int(os.environ.get("ASTRA_REMOTE_CONNECT_TIMEOUT", "15"))
    ssh_options = _split_ssh_options(os.environ.get("ASTRA_REMOTE_SSH_OPTIONS", ""))
    ssh_bin = os.environ.get("ASTRA_REMOTE_SSH_BIN", "").strip() or "ssh"
    request = dict(request)
    request.setdefault("client_id", client_id())
    request.setdefault("project", project_id())
    command = f"{_quote_remote_arg(remote_python)} {_quote_remote_arg(manager)} rpc"
    args = [
        ssh_bin,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        *ssh_options,
        host,
        command,
    ]

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)) + connect_timeout,
        )

    try:
        completed = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return {
            "error": f"Cluster RPC timed out after {timeout}s.",
            "exit_code": 124,
        }
    except FileNotFoundError:
        return {"error": "ssh executable was not found.", "exit_code": -11}
    except Exception as exc:
        return {"error": f"Cluster RPC failed: {type(exc).__name__}: {exc}", "exit_code": -12}
    if completed.returncode != 0:
        return {
            "error": completed.stderr or f"ssh exited with code {completed.returncode}",
            "stdout": completed.stdout,
            "exit_code": completed.returncode,
        }
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "error": "Cluster manager returned non-JSON output.",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": -13,
        }
    response["remote_host"] = host
    return response


async def execute_cluster_code(
    code: str,
    timeout: int,
    engine: str = "",
) -> dict:
    queue_buffer = int(os.environ.get("ASTRA_REMOTE_QUEUE_WAIT", "300"))
    request = {
        "action": "submit_wait",
        "code": code,
        "engine": engine,
        "timeout_seconds": int(timeout),
        "wait_seconds": int(timeout) + max(0, queue_buffer),
    }
    status = await cluster_rpc(request, timeout=int(timeout) + max(0, queue_buffer) + 30)
    result = status.get("result")
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("cluster_job_id", status.get("job_id"))
        result.setdefault("cluster_status", status.get("status"))
        result.setdefault("remote_host", status.get("remote_host"))
        return result
    if status.get("wait_timeout"):
        return {
            "stdout": status.get("stdout_tail", ""),
            "stderr": (
                "Cluster queue wait expired; the persistent job continues. "
                f"Poll {status.get('job_id')} with astra_cluster_job."
            ),
            "exit_code": 125,
            "engine": engine or status.get("engine", "remote"),
            "cluster_job_id": status.get("job_id"),
            "cluster_status": status.get("status"),
            "remote_host": status.get("remote_host"),
        }
    return {
        "stdout": status.get("stdout", ""),
        "stderr": status.get("error") or status.get("stderr_tail") or "Cluster job failed.",
        "exit_code": int(status.get("exit_code", -15)),
        "engine": engine or status.get("engine", "remote"),
        "cluster_job_id": status.get("job_id"),
        "cluster_status": status.get("status"),
        "remote_host": status.get("remote_host"),
    }
