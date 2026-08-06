#!/usr/bin/env python3
"""Small, persistent, multi-client scheduler for the ASTRUM workstation.

The manager deliberately uses only the Python standard library.  Clients talk
to the ``rpc`` command over the existing SSH transport; a user-level systemd
service runs ``serve`` and dispatches queued jobs.  Each job executes through
``astra_remote_worker.py`` in an isolated directory and survives the submitting
MCP/client connection.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid


TERMINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled", "interrupted"}
ACTIVE_STATES = {"starting", "running"}
CLIENT_RE = re.compile(r"[^a-z0-9_.-]+")
ENGINE_RE = re.compile(
    r"^\s*#\s*ASTRA_ENGINE:\s*(python|sympy|sage|maxima|cadabra|lean|lean4|sci|pkgs)\s*$",
    re.I | re.M,
)


def _now() -> float:
    return time.time()


def _safe_client(value: object) -> str:
    text = CLIENT_RE.sub("-", str(value or "unknown").strip().lower()).strip("-.")
    return text[:40] or "unknown"


def _safe_project(value: object) -> str:
    text = CLIENT_RE.sub("-", str(value or "general").strip().lower()).strip("-.")
    return text[:80] or "general"


def _int(value: object, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    return min(parsed, maximum) if maximum is not None else parsed


def _pid_alive(pid: object) -> bool:
    try:
        parsed = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed <= 0:
        return False
    try:
        os.kill(parsed, 0)
        return True
    except OSError:
        return False


def _kill_tree(pid: int) -> None:
    try:
        os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
        except OSError:
            pass


def _detect_engine(code: str, hint: str = "") -> str:
    engine = str(hint or "").strip().lower()
    if engine:
        return "lean4" if engine == "lean" else ("python" if engine == "sympy" else engine)
    match = ENGINE_RE.search(code or "")
    if match:
        engine = match.group(1).lower()
        return "lean4" if engine == "lean" else ("python" if engine == "sympy" else engine)
    return "python"


def _default_cpu(engine: str) -> int:
    return {
        "lean4": 1,
        "maxima": 1,
        "cadabra": 2,
        "sage": 4,
        "sci": 4,
        "pkgs": 4,
        "python": 2,
    }.get(engine, 2)


def _looks_gpu_bound(code: str) -> bool:
    lowered = (code or "").lower()
    return any(
        token in lowered
        for token in (
            "torch.cuda",
            "cupy",
            "jax.devices",
            "jax.local_devices",
            "cuda",
            "# astra_resource: gpu",
        )
    )


def _memory_total_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


class ClusterStore:
    def __init__(self, root: Path | str | None = None):
        default = os.environ.get("ASTRA_CLUSTER_ROOT", "~/astra-worker/cluster")
        self.root = Path(root or default).expanduser().resolve()
        self.jobs_root = self.root / "jobs"
        self.db_path = self.root / "state.db"
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    project TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    cpu_slots INTEGER NOT NULL,
                    gpu_slots INTEGER NOT NULL,
                    memory_mb INTEGER NOT NULL DEFAULT 0,
                    timeout_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    started_ts REAL,
                    finished_ts REAL,
                    heartbeat_ts REAL NOT NULL,
                    pid INTEGER,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    exit_code INTEGER,
                    verdict TEXT,
                    error TEXT,
                    source_ip TEXT NOT NULL DEFAULT '',
                    artifact_dir TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created
                    ON jobs(status, created_ts);
                CREATE INDEX IF NOT EXISTS jobs_client_created
                    ON jobs(client_id, created_ts);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "source_ip" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN source_ip TEXT NOT NULL DEFAULT ''"
                )

    def event(self, connection: sqlite3.Connection, job_id: str, event: str, detail: str = "") -> None:
        connection.execute(
            "INSERT INTO events(job_id, ts, event, detail) VALUES (?, ?, ?, ?)",
            (job_id, _now(), event, detail[:1000]),
        )

    def limits(self) -> dict:
        logical = max(1, os.cpu_count() or 1)
        reserve = _int(os.environ.get("ASTRA_CLUSTER_CPU_RESERVE"), 4, 0, logical - 1)
        cpu_slots = _int(
            os.environ.get("ASTRA_CLUSTER_CPU_SLOTS"),
            max(1, logical - reserve),
            1,
            logical,
        )
        detected_gpu = 1 if shutil.which("nvidia-smi") else 0
        gpu_slots = _int(os.environ.get("ASTRA_CLUSTER_GPU_SLOTS"), detected_gpu, 0, 16)
        return {
            "logical_cpus": logical,
            "cpu_reserve": reserve,
            "cpu_slots": cpu_slots,
            "gpu_slots": gpu_slots,
            "memory_total_mb": _memory_total_mb(),
        }

    def submit(self, payload: dict) -> dict:
        code = str(payload.get("code") or "")
        if not code.strip():
            return {"error": "code is empty"}
        client_id = _safe_client(payload.get("client_id"))
        project = _safe_project(payload.get("project"))
        engine = _detect_engine(code, str(payload.get("engine") or ""))
        limits = self.limits()
        cpu_slots = _int(payload.get("cpu_slots"), _default_cpu(engine), 1, limits["cpu_slots"])
        default_gpu = 1 if _looks_gpu_bound(code) else 0
        gpu_slots = _int(payload.get("gpu_slots"), default_gpu, 0, limits["gpu_slots"])
        memory_mb = _int(payload.get("memory_mb"), 0, 0, limits.get("memory_total_mb") or 10**9)
        priority = _int(payload.get("priority"), 0, -10, 10)
        timeout_seconds = _int(payload.get("timeout_seconds"), 3600, 1, 7 * 86400)
        source_ip = str(payload.get("_source_ip") or "").strip()[:64]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        job_id = f"astrum_{stamp}_{client_id}_{uuid.uuid4().hex[:6]}"
        jobdir = self.jobs_root / job_id
        jobdir.mkdir(mode=0o700)
        request = {
            "job_id": job_id,
            "client_id": client_id,
            "project": project,
            "engine": engine,
            "code": code,
            "timeout": timeout_seconds,
            "workdir": str(jobdir / "workspace"),
        }
        (jobdir / "request.json").write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, client_id, project, engine, priority, cpu_slots,
                    gpu_slots, memory_mb, timeout_seconds, status, created_ts,
                    heartbeat_ts, source_ip, artifact_dir
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    client_id,
                    project,
                    engine,
                    priority,
                    cpu_slots,
                    gpu_slots,
                    memory_mb,
                    timeout_seconds,
                    created,
                    created,
                    source_ip,
                    str(jobdir),
                ),
            )
            self.event(connection, job_id, "submitted")
        return self.status(job_id, include_result=False)

    def _row(self, connection: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

    def status(self, job_id: str, include_result: bool = True, tail_chars: int = 3000) -> dict:
        with self.connect() as connection:
            row = self._row(connection, job_id)
            if row is None:
                return {"error": f"unknown cluster job: {job_id}"}
            result = dict(row)
            events = connection.execute(
                "SELECT ts, event, detail FROM events WHERE job_id = ? ORDER BY id DESC LIMIT 12",
                (job_id,),
            ).fetchall()
            result["events"] = [dict(item) for item in reversed(events)]
        now = _now()
        result["heartbeat_age_s"] = round(max(0.0, now - float(result["heartbeat_ts"])), 1)
        if result.get("started_ts"):
            end = result.get("finished_ts") or now
            result["elapsed_s"] = round(max(0.0, end - result["started_ts"]), 1)
        artifact_dir = Path(result["artifact_dir"])
        if include_result:
            try:
                result["result"] = json.loads((artifact_dir / "result.json").read_text(encoding="utf-8"))
            except Exception:
                pass
        for key, filename in (("stdout_tail", "stdout.log"), ("stderr_tail", "stderr.log")):
            try:
                result[key] = (artifact_dir / filename).read_text(
                    encoding="utf-8", errors="replace"
                )[-tail_chars:]
            except Exception:
                pass
        return result

    def list_jobs(self, limit: int = 20, client_id: str = "") -> dict:
        limit = _int(limit, 20, 1, 200)
        params: list[object] = []
        where = ""
        if client_id:
            where = "WHERE client_id = ?"
            params.append(_safe_client(client_id))
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_ts DESC LIMIT ?",
                params,
            ).fetchall()
        return {"jobs": [dict(row) for row in rows], "capacity": self.capacity()}

    def cancel(self, job_id: str, requested_by: str = "") -> dict:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._row(connection, job_id)
            if row is None:
                connection.rollback()
                return {"error": f"unknown cluster job: {job_id}"}
            if row["status"] in TERMINAL_STATES:
                connection.commit()
                return self.status(job_id)
            now = _now()
            if row["status"] == "queued":
                connection.execute(
                    "UPDATE jobs SET status='cancelled', cancel_requested=1, finished_ts=?, heartbeat_ts=? WHERE job_id=?",
                    (now, now, job_id),
                )
            else:
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1, heartbeat_ts=? WHERE job_id=?",
                    (now, job_id),
                )
            self.event(connection, job_id, "cancel_requested", _safe_client(requested_by))
            connection.commit()
        return self.status(job_id)

    def recover_dead(self) -> None:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT job_id, pid, status FROM jobs WHERE status IN ('starting','running')"
            ).fetchall()
            for row in rows:
                if _pid_alive(row["pid"]):
                    continue
                now = _now()
                connection.execute(
                    "UPDATE jobs SET status='interrupted', finished_ts=?, heartbeat_ts=?, error=? WHERE job_id=?",
                    (now, now, "runner process is no longer alive", row["job_id"]),
                )
                self.event(connection, row["job_id"], "interrupted", "dead runner recovered")

    def capacity(self) -> dict:
        limits = self.limits()
        with self.connect() as connection:
            running = connection.execute(
                """
                SELECT COUNT(*) AS jobs, COALESCE(SUM(cpu_slots),0) AS cpu,
                       COALESCE(SUM(gpu_slots),0) AS gpu
                FROM jobs WHERE status IN ('starting','running')
                """
            ).fetchone()
            queued = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued'"
            ).fetchone()[0]
        limits.update(
            {
                "running_jobs": int(running["jobs"]),
                "used_cpu_slots": int(running["cpu"]),
                "used_gpu_slots": int(running["gpu"]),
                "available_cpu_slots": max(0, limits["cpu_slots"] - int(running["cpu"])),
                "available_gpu_slots": max(0, limits["gpu_slots"] - int(running["gpu"])),
                "queued_jobs": int(queued),
                "root": str(self.root),
            }
        )
        return limits

    def reserve_next(self) -> dict | None:
        """Reserve one fitting job, fairly rotating between client IDs."""
        limits = self.limits()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT COALESCE(SUM(cpu_slots),0) AS cpu,
                       COALESCE(SUM(gpu_slots),0) AS gpu
                FROM jobs WHERE status IN ('starting','running')
                """
            ).fetchone()
            available_cpu = limits["cpu_slots"] - int(active["cpu"])
            available_gpu = limits["gpu_slots"] - int(active["gpu"])
            queued = connection.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC, created_ts ASC"
            ).fetchall()
            last_started = {
                row["client_id"]: float(row["last_started"] or 0.0)
                for row in connection.execute(
                    "SELECT client_id, MAX(started_ts) AS last_started FROM jobs GROUP BY client_id"
                ).fetchall()
            }
            per_client: dict[str, sqlite3.Row] = {}
            for row in queued:
                if row["cpu_slots"] > available_cpu or row["gpu_slots"] > available_gpu:
                    continue
                per_client.setdefault(row["client_id"], row)
            if not per_client:
                connection.commit()
                return None
            candidate = min(
                per_client.values(),
                key=lambda row: (
                    -int(row["priority"]),
                    last_started.get(row["client_id"], 0.0),
                    float(row["created_ts"]),
                ),
            )
            now = _now()
            updated = connection.execute(
                """
                UPDATE jobs SET status='starting', started_ts=?, heartbeat_ts=?
                WHERE job_id=? AND status='queued'
                """,
                (now, now, candidate["job_id"]),
            ).rowcount
            if updated != 1:
                connection.rollback()
                return None
            self.event(connection, candidate["job_id"], "reserved")
            connection.commit()
            return self.status(candidate["job_id"], include_result=False)


def _verdict(stdout: str) -> str:
    upper = (stdout or "").upper()
    if "VERDICT: PASS" in upper:
        return "PASS"
    if "VERDICT: FAIL" in upper:
        return "FAIL"
    return "NONE"


def run_job(store: ClusterStore, job_id: str) -> int:
    job = store.status(job_id, include_result=False)
    if job.get("error"):
        return 2
    jobdir = Path(job["artifact_dir"])
    request = json.loads((jobdir / "request.json").read_text(encoding="utf-8"))
    worker = Path(
        os.environ.get(
            "ASTRA_CLUSTER_WORKER",
            str(Path(__file__).resolve().with_name("astra_remote_worker.py")),
        )
    ).expanduser()
    python_bin = os.environ.get("ASTRA_CLUSTER_PYTHON", sys.executable)
    now = _now()
    with store.connect() as connection:
        connection.execute(
            "UPDATE jobs SET status='running', pid=?, heartbeat_ts=? WHERE job_id=?",
            (os.getpid(), now, job_id),
        )
        store.event(connection, job_id, "running", f"pid={os.getpid()}")

    stdout_path = jobdir / "stdout.log"
    stderr_path = jobdir / "stderr.log"
    result_path = jobdir / "result.json"
    workspace = jobdir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    timeout_seconds = int(job["timeout_seconds"])
    env = dict(os.environ)
    threads = str(max(1, int(job["cpu_slots"])))
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        env[name] = threads
    payload = {
        "code": request["code"],
        "timeout": timeout_seconds,
        "workdir": str(workspace),
    }
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            [python_bin, str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=True,
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        process.stdin = None
        timed_out = False
        cancelled = False
        while process.poll() is None:
            elapsed = time.monotonic() - started
            with store.connect() as connection:
                row = store._row(connection, job_id)
                cancelled = bool(row and row["cancel_requested"])
                connection.execute(
                    "UPDATE jobs SET heartbeat_ts=? WHERE job_id=?",
                    (_now(), job_id),
                )
            if cancelled or elapsed > timeout_seconds + 15:
                timed_out = not cancelled
                _kill_tree(process.pid)
                break
            time.sleep(2)
        out, err = process.communicate(timeout=10)
        return_code = process.returncode if process.returncode is not None else -9
        try:
            result = json.loads(out or "{}")
        except json.JSONDecodeError:
            result = {
                "stdout": out or "",
                "stderr": err or "cluster worker returned non-JSON output",
                "exit_code": return_code,
                "engine": request.get("engine", "remote"),
            }
        if err:
            result["worker_stderr"] = err
        if cancelled:
            state = "cancelled"
            result.update(exit_code=130, error="job cancelled")
        elif timed_out:
            state = "timed_out"
            result.update(exit_code=124, error=f"job exceeded {timeout_seconds}s")
        else:
            state = "succeeded" if int(result.get("exit_code", return_code)) == 0 else "failed"
    except Exception as exc:
        state = "failed"
        result = {
            "stdout": "",
            "stderr": f"ClusterRunnerError: {type(exc).__name__}: {exc}",
            "exit_code": -1,
            "engine": request.get("engine", "remote"),
        }

    result.setdefault("engine", request.get("engine", "remote"))
    result["verdict"] = _verdict(str(result.get("stdout") or ""))
    if (
        result["verdict"] == "NONE"
        and request.get("engine") == "lean4"
        and int(result.get("exit_code", -1)) == 0
    ):
        # For a Lean artifact, successful type-checking is the executable proof.
        result["verdict"] = "PASS"
    result["cluster_job_id"] = job_id
    result["client_id"] = job["client_id"]
    result["project"] = job["project"]
    result["duration_s"] = round(time.monotonic() - started, 3)
    stdout_path.write_text(str(result.get("stdout") or ""), encoding="utf-8")
    stderr_path.write_text(str(result.get("stderr") or ""), encoding="utf-8")
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    finished = _now()
    with store.connect() as connection:
        connection.execute(
            """
            UPDATE jobs SET status=?, finished_ts=?, heartbeat_ts=?, exit_code=?,
                verdict=?, error=? WHERE job_id=?
            """,
            (
                state,
                finished,
                finished,
                int(result.get("exit_code", -1)),
                result["verdict"],
                str(result.get("error") or "")[:2000],
                job_id,
            ),
        )
        store.event(connection, job_id, state)
    return 0 if state == "succeeded" else 1


def _launch_runner(store: ClusterStore, job: dict) -> None:
    jobdir = Path(job["artifact_dir"])
    launcher_out = (jobdir / "runner.out").open("a", encoding="utf-8")
    launcher_err = (jobdir / "runner.err").open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "run", job["job_id"]],
            stdin=subprocess.DEVNULL,
            stdout=launcher_out,
            stderr=launcher_err,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        launcher_out.close()
        launcher_err.close()
    with store.connect() as connection:
        connection.execute(
            "UPDATE jobs SET pid=?, heartbeat_ts=? WHERE job_id=? AND status='starting'",
            (process.pid, _now(), job["job_id"]),
        )
        store.event(connection, job["job_id"], "runner_spawned", f"pid={process.pid}")


def serve(store: ClusterStore, poll_seconds: float = 1.0) -> int:
    while True:
        store.recover_dead()
        while True:
            job = store.reserve_next()
            if not job:
                break
            _launch_runner(store, job)
        time.sleep(max(0.2, poll_seconds))


def _wait_for_job(store: ClusterStore, job_id: str, seconds: int) -> dict:
    deadline = time.monotonic() + max(1, seconds)
    while time.monotonic() < deadline:
        status = store.status(job_id)
        if status.get("status") in TERMINAL_STATES:
            return status
        time.sleep(1)
    status = store.status(job_id)
    status["wait_timeout"] = True
    status["hint"] = "The cluster job continues; poll it with astra_cluster_job."
    return status


def rpc(store: ClusterStore, request: dict) -> dict:
    action = str(request.get("action") or "").strip().lower()
    if action in {"submit", "submit_wait"}:
        request = dict(request)
        connection = os.environ.get("SSH_CONNECTION", "").strip().split()
        request["_source_ip"] = connection[0] if connection else ""
        submitted = store.submit(request)
        if submitted.get("error") or action == "submit":
            return submitted
        wait_seconds = _int(
            request.get("wait_seconds"),
            int(submitted.get("timeout_seconds") or 3600) + 300,
            1,
            7 * 86400,
        )
        return _wait_for_job(store, submitted["job_id"], wait_seconds)
    if action == "job":
        job_id = str(request.get("job_id") or "").strip()
        if job_id:
            return store.status(job_id)
        return store.list_jobs(request.get("limit", 20), str(request.get("client_filter") or ""))
    if action == "cancel":
        return store.cancel(
            str(request.get("job_id") or "").strip(),
            str(request.get("client_id") or ""),
        )
    if action == "capacity":
        return store.capacity()
    return {"error": f"unknown cluster action: {action}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("rpc")
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--poll-seconds", type=float, default=1.0)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("job_id")
    args = parser.parse_args()
    store = ClusterStore(args.root)
    if args.command == "init":
        print(json.dumps({"status": "initialized", "capacity": store.capacity()}))
        return 0
    if args.command == "rpc":
        try:
            request = json.loads(sys.stdin.read() or "{}")
            result = rpc(store, request)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "serve":
        return serve(store, args.poll_seconds)
    if args.command == "run":
        return run_job(store, args.job_id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
