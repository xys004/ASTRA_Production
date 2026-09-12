"""Local, experimental adapter from campaigns to ASTRUM's scheduler RPC.

Nothing in this module changes or deploys the remote scheduler.  The adapter
uses the existing ``submit`` and ``job`` RPC contract and persists a unique
campaign/task/attempt -> scheduler job binding in the campaign's local SQLite
database.  Tests inject a fake gateway; ``ClusterRpcGateway`` is the opt-in
bridge to the real persistent scheduler.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import sqlite3
import time
from typing import Any, Dict, Mapping, Optional, Protocol

from core.experimental_campaign_manager import (
    ExperimentalCampaignRunner,
    ExperimentalCampaignStore,
    TaskOutcome,
)


ACTIVE_SCHEDULER_STATES = {"queued", "starting", "running"}
TERMINAL_SCHEDULER_STATES = {
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
}
SCHEDULER_REQUEST_KEYS = {
    "code",
    "engine",
    "project",
    "priority",
    "cpu_slots",
    "gpu_slots",
    "memory_mb",
    "timeout_seconds",
}


class SchedulerGateway(Protocol):
    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def job(self, job_id: str) -> Mapping[str, Any]:
        ...


class ClusterRpcGateway:
    """Synchronous opt-in wrapper around ASTRA's existing SSH scheduler RPC."""

    @staticmethod
    def _rpc(request: Mapping[str, Any], timeout: int = 60) -> Mapping[str, Any]:
        from core.cluster_client import cluster_rpc

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(cluster_rpc(dict(request), timeout=timeout))
        raise RuntimeError(
            "ClusterRpcGateway is synchronous and must run outside an asyncio event loop"
        )

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = dict(request)
        payload["action"] = "submit"
        return self._rpc(payload)

    def job(self, job_id: str) -> Mapping[str, Any]:
        return self._rpc({"action": "job", "job_id": job_id})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(request).encode("utf-8")).hexdigest()


def _scheduler_idempotency_key(
    campaign_id: str, task: Mapping[str, Any], attempt_no: int
) -> str:
    identity = {
        "campaign_id": campaign_id,
        "task_id": str(task["task_id"]),
        "task_idempotency_key": str(task["idempotency_key"]),
        "attempt_no": int(attempt_no),
    }
    return "ecm-v1:" + _request_digest(identity)


def validate_scheduler_request(task: Mapping[str, Any]) -> Dict[str, Any]:
    payload = task.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("task payload must be an object")
    request = payload.get("scheduler_request")
    if not isinstance(request, Mapping):
        raise ValueError("payload.scheduler_request must be an object")
    unknown = set(request) - SCHEDULER_REQUEST_KEYS
    if unknown:
        raise ValueError("unknown scheduler request keys: %s" % sorted(unknown))
    code = request.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("scheduler request code must be non-empty")
    normalized: Dict[str, Any] = {
        "code": code,
        "engine": str(request.get("engine") or ""),
        "project": str(request.get("project") or ""),
        "priority": int(request.get("priority", 0)),
        "cpu_slots": int(request.get("cpu_slots", 0)),
        "gpu_slots": int(request.get("gpu_slots", 0)),
        "memory_mb": int(request.get("memory_mb", 0)),
        "timeout_seconds": int(request.get("timeout_seconds", 3600)),
    }
    if not -10 <= normalized["priority"] <= 10:
        raise ValueError("priority out of range")
    for key in ("cpu_slots", "gpu_slots", "memory_mb"):
        if normalized[key] < 0:
            raise ValueError("%s cannot be negative" % key)
    if not 1 <= normalized["timeout_seconds"] <= 7 * 86400:
        raise ValueError("timeout_seconds out of range")
    return normalized


def classify_scheduler_status(status: Mapping[str, Any]) -> Optional[TaskOutcome]:
    """Map one scheduler response to a terminal outcome, or None if active."""

    if status.get("error") and not status.get("status"):
        return TaskOutcome.operational_failure(
            "scheduler_rpc_error", {"scheduler_response": dict(status)}
        )
    state = str(status.get("status") or "")
    if state in ACTIVE_SCHEDULER_STATES:
        return None
    if state not in TERMINAL_SCHEDULER_STATES:
        return TaskOutcome.operational_failure(
            "scheduler_protocol_error", {"scheduler_response": dict(status)}
        )

    result = status.get("result") if isinstance(status.get("result"), Mapping) else {}
    verdict = str(status.get("verdict") or result.get("verdict") or "NONE").upper()
    exit_code_raw = status.get("exit_code", result.get("exit_code", -1))
    try:
        exit_code = int(exit_code_raw)
    except (TypeError, ValueError):
        exit_code = -1
    evidence = {
        "scheduler_job_id": status.get("job_id") or result.get("cluster_job_id"),
        "scheduler_status": state,
        "verdict": verdict,
        "exit_code": exit_code,
    }

    # A physical/scientific FAIL is never operationally retried, even when the
    # scheduler also reports a non-zero exit code.
    if verdict == "FAIL":
        return TaskOutcome.scientific_failure(evidence)
    if state == "succeeded" and exit_code == 0 and verdict == "PASS":
        return TaskOutcome.success(evidence)
    if state == "succeeded":
        evidence["reason"] = "successful process lacks an unambiguous PASS"
        return TaskOutcome.scientific_failure(evidence)
    if state == "cancelled":
        return TaskOutcome.operational_failure("scheduler_cancelled", evidence)
    if state == "timed_out":
        return TaskOutcome.operational_failure("scheduler_timeout", evidence)
    if state == "interrupted":
        return TaskOutcome.operational_failure("runner_interrupted", evidence)
    return TaskOutcome.operational_failure("scheduler_failed", evidence)


class ExperimentalAstrumCampaignAdapter:
    """Bind and reconcile experimental campaign attempts with ASTRUM jobs."""

    def __init__(
        self,
        store: ExperimentalCampaignStore,
        campaign_id: str,
        gateway: SchedulerGateway,
        poll_interval_seconds: float = 1.0,
        max_poll_seconds: float = 7 * 86400,
        submission_attempts: int = 2,
    ) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.gateway = gateway
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self.max_poll_seconds = max(0.0, float(max_poll_seconds))
        self.submission_attempts = max(1, int(submission_attempts))
        self._init_binding_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.store.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_binding_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_bindings (
                    campaign_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL,
                    scheduler_job_id TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL,
                    scheduler_status TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    updated_ts REAL NOT NULL,
                    PRIMARY KEY(campaign_id, task_id, attempt_no),
                    FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id)
                )
                """
            )

    def bindings(self) -> list:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM scheduler_bindings WHERE campaign_id=? ORDER BY created_ts",
                (self.campaign_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _current_attempt(self, task_id: str, attempt_no: int) -> Mapping[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE campaign_id=? AND task_id=? AND attempt_no=?",
                (self.campaign_id, task_id, attempt_no),
            ).fetchone()
        if not row:
            raise RuntimeError("campaign attempt was not persisted before submission")
        return dict(row)

    def bind_or_submit(self, task: Mapping[str, Any], attempt_no: int) -> str:
        task_id = str(task["task_id"])
        attempt = self._current_attempt(task_id, attempt_no)
        request = validate_scheduler_request(task)
        request["idempotency_key"] = _scheduler_idempotency_key(
            self.campaign_id, task, attempt_no
        )
        digest = _request_digest(request)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM scheduler_bindings WHERE campaign_id=? AND task_id=? AND attempt_no=?",
                (self.campaign_id, task_id, attempt_no),
            ).fetchone()
            if existing:
                if existing["request_sha256"] != digest:
                    raise RuntimeError("bound scheduler request digest changed")
                connection.commit()
                return str(existing["scheduler_job_id"])

            submitted: Dict[str, Any] = {}
            for submission_no in range(1, self.submission_attempts + 1):
                try:
                    submitted = dict(self.gateway.submit(request))
                except Exception as exc:
                    submitted = {
                        "error": "scheduler submit RPC raised %s" % type(exc).__name__
                    }
                job_id = str(submitted.get("job_id") or "")
                if job_id:
                    break
                if "different request" in str(submitted.get("error") or ""):
                    raise RuntimeError("scheduler idempotency protocol conflict")
                if submission_no < self.submission_attempts:
                    time.sleep(self.poll_interval_seconds)
            if not job_id:
                # Native scheduler idempotency makes identical resubmission
                # safe.  Exhaustion remains fail-closed, but never changes the
                # key or advances the campaign attempt.
                raise RuntimeError(
                    "scheduler submission outcome is unknown after idempotent retries"
                )
            now = time.time()
            connection.execute(
                """
                INSERT INTO scheduler_bindings(
                    campaign_id,task_id,attempt_no,attempt_id,idempotency_key,
                    scheduler_job_id,request_sha256,scheduler_status,created_ts,updated_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.campaign_id,
                    task_id,
                    attempt_no,
                    attempt["attempt_id"],
                    task["idempotency_key"],
                    job_id,
                    digest,
                    str(submitted.get("status") or "queued"),
                    now,
                    now,
                ),
            )
            connection.commit()
            return job_id

    def _record_scheduler_status(self, job_id: str, state: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE scheduler_bindings SET scheduler_status=?, updated_ts=? WHERE scheduler_job_id=?",
                (state, time.time(), job_id),
            )

    def _poll_terminal(self, job_id: str) -> TaskOutcome:
        deadline = time.monotonic() + self.max_poll_seconds
        while True:
            try:
                status = dict(self.gateway.job(job_id))
            except Exception as exc:
                status = {
                    "error": "scheduler status RPC raised %s" % type(exc).__name__
                }
            status.setdefault("job_id", job_id)
            state = str(status.get("status") or "rpc_error")
            self._record_scheduler_status(job_id, state)
            # A failed status query says nothing about the bound remote job.
            # Keep polling the same ID; never create a duplicate attempt/job.
            outcome = (
                None
                if status.get("error") and not status.get("status")
                else classify_scheduler_status(status)
            )
            if outcome is not None:
                return outcome
            if time.monotonic() >= deadline:
                return TaskOutcome.operational_failure(
                    "scheduler_poll_timeout",
                    {"scheduler_job_id": job_id, "scheduler_status": state},
                )
            time.sleep(self.poll_interval_seconds)

    def __call__(self, task: Mapping[str, Any], attempt_no: int) -> TaskOutcome:
        try:
            job_id = self.bind_or_submit(task, attempt_no)
        except ValueError as exc:
            return TaskOutcome.operational_failure(
                "scheduler_protocol_error", {"message": str(exc)}
            )
        except RuntimeError as exc:
            failure_class = (
                "scheduler_submission_unknown"
                if "outcome is unknown" in str(exc)
                else "scheduler_protocol_error"
            )
            return TaskOutcome.operational_failure(failure_class, {"message": str(exc)})
        return self._poll_terminal(job_id)

    def reconcile_once(self) -> Dict[str, Any]:
        """Reconcile persisted running attempts after a local process restart."""

        active = []
        completed = []
        runner = ExperimentalCampaignRunner(self.store, self)
        attempts = [
            row
            for row in self.store.attempts(self.campaign_id)
            if row["status"] == "running"
        ]
        binding_by_attempt = {row["attempt_id"]: row for row in self.bindings()}
        task_specs = {
            row["task_id"]: json.loads(row["spec_json"])
            for row in self.store.task_rows(self.campaign_id)
        }
        for attempt in attempts:
            binding = binding_by_attempt.get(attempt["attempt_id"])
            runtime_attempt = {
                "attempt_id": attempt["attempt_id"],
                "attempt_no": attempt["attempt_no"],
                "task_id": attempt["task_id"],
                "spec": task_specs[attempt["task_id"]],
            }
            if not binding:
                # A process can die after the scheduler accepted submit but
                # before the local binding committed.  Resubmitting the exact
                # request with the same native key recovers the original job.
                try:
                    job_id = self.bind_or_submit(
                        runtime_attempt["spec"], runtime_attempt["attempt_no"]
                    )
                except (RuntimeError, ValueError):
                    active.append("unresolved:%s" % attempt["attempt_id"])
                    continue
            else:
                job_id = binding["scheduler_job_id"]
            try:
                status = dict(self.gateway.job(job_id))
            except Exception as exc:
                status = {
                    "error": "scheduler status RPC raised %s" % type(exc).__name__
                }
            status.setdefault("job_id", job_id)
            state = str(status.get("status") or "rpc_error")
            self._record_scheduler_status(job_id, state)
            outcome = (
                None
                if status.get("error") and not status.get("status")
                else classify_scheduler_status(status)
            )
            if outcome is None:
                active.append(job_id)
                continue
            runner._finish(self.campaign_id, runtime_attempt, outcome)
            completed.append(attempt["attempt_id"])
        return {"active_job_ids": active, "completed_attempt_ids": completed}

    def run(self) -> Dict[str, Any]:
        reconciliation = self.reconcile_once()
        deadline = time.monotonic() + self.max_poll_seconds
        while reconciliation["active_job_ids"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("active scheduler jobs remain bound; refusing resubmission")
            time.sleep(self.poll_interval_seconds)
            reconciliation = self.reconcile_once()
        return ExperimentalCampaignRunner(self.store, self).run(self.campaign_id)
