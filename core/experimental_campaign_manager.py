"""Experimental campaign layer for the existing ASTRUM scheduler contract.

This module is intentionally local and backend-agnostic.  It does not submit
remote work, start a daemon, or modify ``remote/astra_cluster_manager.py``.
Instead it exercises the campaign semantics that may later wrap the existing
``astra_cluster_submit``/``astra_cluster_job`` API.

The safety boundary is explicit: only preregistered *operational* failure
classes may be retried.  A scientific FAIL is terminal on its first attempt.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
TERMINAL_TASK_STATES = {
    "succeeded",
    "scientific_failed",
    "operational_failed",
    "blocked",
}
FAILURE_KINDS = {"success", "operational_failure", "scientific_failure"}
NEVER_RETRY_OPERATIONAL_CLASSES = {
    "scheduler_binding_missing",
    "scheduler_cancelled",
    "scheduler_poll_timeout",
    "scheduler_protocol_error",
    "scheduler_submission_unknown",
}


class CampaignManifestError(ValueError):
    """Raised when a campaign manifest violates the fail-closed contract."""


@dataclass(frozen=True)
class TaskOutcome:
    kind: str
    result: Mapping[str, Any]
    failure_class: str = ""

    def __post_init__(self) -> None:
        if self.kind not in FAILURE_KINDS:
            raise ValueError("unknown task outcome kind: %s" % self.kind)
        if self.kind == "operational_failure" and not self.failure_class:
            raise ValueError("operational failures require a failure_class")
        if self.kind != "operational_failure" and self.failure_class:
            raise ValueError("failure_class is reserved for operational failures")

    @classmethod
    def success(cls, result: Optional[Mapping[str, Any]] = None) -> "TaskOutcome":
        return cls("success", dict(result or {}))

    @classmethod
    def operational_failure(
        cls, failure_class: str, result: Optional[Mapping[str, Any]] = None
    ) -> "TaskOutcome":
        return cls("operational_failure", dict(result or {}), failure_class)

    @classmethod
    def scientific_failure(
        cls, result: Optional[Mapping[str, Any]] = None
    ) -> "TaskOutcome":
        return cls("scientific_failure", dict(result or {}))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(manifest).encode("utf-8")).hexdigest()


def _require_identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if not IDENTIFIER_RE.fullmatch(text):
        raise CampaignManifestError("invalid %s" % field)
    return text


def _reject_unknown_keys(
    value: Mapping[str, Any], allowed: set, field: str
) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise CampaignManifestError(
            "unknown keys in %s: %s" % (field, sorted(unknown))
        )


def validate_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize an immutable experimental campaign manifest."""

    if not isinstance(manifest, Mapping):
        raise CampaignManifestError("manifest must be an object")
    _reject_unknown_keys(
        manifest,
        {
            "schema_version",
            "campaign_id",
            "max_concurrency",
            "operational_retry_allowlist",
            "tasks",
        },
        "manifest",
    )
    if manifest.get("schema_version") != 1:
        raise CampaignManifestError("schema_version must be exactly 1")
    campaign_id = _require_identifier(manifest.get("campaign_id"), "campaign_id")
    max_concurrency = manifest.get("max_concurrency")
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
        raise CampaignManifestError("max_concurrency must be an integer")
    if not 1 <= max_concurrency <= 64:
        raise CampaignManifestError("max_concurrency must be in 1..64")

    allowlist_raw = manifest.get("operational_retry_allowlist", [])
    if not isinstance(allowlist_raw, list):
        raise CampaignManifestError("operational_retry_allowlist must be a list")
    allowlist = []
    for item in allowlist_raw:
        allowlist.append(_require_identifier(item, "operational failure class"))
    if len(set(allowlist)) != len(allowlist):
        raise CampaignManifestError("duplicate operational failure class")

    tasks_raw = manifest.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise CampaignManifestError("tasks must be a non-empty list")
    tasks: List[Dict[str, Any]] = []
    task_ids = set()
    idempotency_keys = set()
    for raw in tasks_raw:
        if not isinstance(raw, Mapping):
            raise CampaignManifestError("each task must be an object")
        _reject_unknown_keys(
            raw,
            {"task_id", "idempotency_key", "depends_on", "retry", "payload"},
            "task",
        )
        task_id = _require_identifier(raw.get("task_id"), "task_id")
        key = _require_identifier(raw.get("idempotency_key"), "idempotency_key")
        if task_id in task_ids:
            raise CampaignManifestError("duplicate task_id: %s" % task_id)
        if key in idempotency_keys:
            raise CampaignManifestError("duplicate idempotency_key: %s" % key)
        task_ids.add(task_id)
        idempotency_keys.add(key)

        dependency = raw.get("depends_on", {"mode": "afterok", "tasks": []})
        if not isinstance(dependency, Mapping):
            raise CampaignManifestError("depends_on must be an object")
        _reject_unknown_keys(dependency, {"mode", "tasks"}, "depends_on")
        mode = dependency.get("mode", "afterok")
        dependencies = dependency.get("tasks", [])
        if mode not in {"afterok", "afterany"}:
            raise CampaignManifestError("depends_on.mode must be afterok or afterany")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) for item in dependencies
        ):
            raise CampaignManifestError("depends_on.tasks must be a list of task ids")
        if len(set(dependencies)) != len(dependencies) or task_id in dependencies:
            raise CampaignManifestError("invalid dependency set for %s" % task_id)

        retry = raw.get("retry", {"max_attempts": 1, "backoff_seconds": 0})
        if not isinstance(retry, Mapping):
            raise CampaignManifestError("retry must be an object")
        _reject_unknown_keys(retry, {"max_attempts", "backoff_seconds"}, "retry")
        max_attempts = retry.get("max_attempts", 1)
        backoff_seconds = retry.get("backoff_seconds", 0)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise CampaignManifestError("max_attempts must be an integer")
        if not 1 <= max_attempts <= 10:
            raise CampaignManifestError("max_attempts must be in 1..10")
        if isinstance(backoff_seconds, bool) or not isinstance(
            backoff_seconds, (int, float)
        ):
            raise CampaignManifestError("backoff_seconds must be numeric")
        if not 0 <= float(backoff_seconds) <= 86400:
            raise CampaignManifestError("backoff_seconds out of range")

        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise CampaignManifestError("payload must be an object")
        tasks.append(
            {
                "task_id": task_id,
                "idempotency_key": key,
                "depends_on": {"mode": mode, "tasks": list(dependencies)},
                "retry": {
                    "max_attempts": max_attempts,
                    "backoff_seconds": float(backoff_seconds),
                },
                "payload": dict(payload),
            }
        )

    for task in tasks:
        unknown = set(task["depends_on"]["tasks"]) - task_ids
        if unknown:
            raise CampaignManifestError(
                "unknown dependencies for %s: %s"
                % (task["task_id"], sorted(unknown))
            )

    graph = {task["task_id"]: task["depends_on"]["tasks"] for task in tasks}
    visiting = set()
    visited = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise CampaignManifestError("dependency cycle detected")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_id in graph[task_id]:
            visit(dependency_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)

    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "max_concurrency": max_concurrency,
        "operational_retry_allowlist": sorted(allowlist),
        "tasks": tasks,
    }


class ExperimentalCampaignStore:
    """Small SQLite store used only by the reversible campaign pilot."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id TEXT PRIMARY KEY,
                manifest_sha256 TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                max_concurrency INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_ts REAL NOT NULL,
                updated_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                campaign_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_eligible_ts REAL NOT NULL DEFAULT 0,
                result_json TEXT,
                failure_class TEXT,
                PRIMARY KEY(campaign_id, task_id),
                UNIQUE(campaign_id, idempotency_key),
                FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                attempt_no INTEGER NOT NULL,
                parent_attempt_id TEXT,
                status TEXT NOT NULL,
                failure_kind TEXT,
                failure_class TEXT,
                result_json TEXT,
                started_ts REAL NOT NULL,
                finished_ts REAL,
                UNIQUE(campaign_id, task_id, attempt_no),
                FOREIGN KEY(campaign_id, task_id) REFERENCES tasks(campaign_id, task_id)
            );
            """
        )
        self.connection.commit()

    def register(self, manifest: Mapping[str, Any]) -> Dict[str, Any]:
        normalized = validate_manifest(manifest)
        digest = _manifest_digest(normalized)
        campaign_id = normalized["campaign_id"]
        existing = self.connection.execute(
            "SELECT manifest_sha256 FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if existing:
            if existing["manifest_sha256"] != digest:
                raise CampaignManifestError(
                    "campaign_id already exists with a different immutable manifest"
                )
            return self.snapshot(campaign_id)
        now = time.time()
        with self.connection:
            self.connection.execute(
                "INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)",
                (
                    campaign_id,
                    digest,
                    _canonical_json(normalized),
                    normalized["max_concurrency"],
                    "pending",
                    now,
                    now,
                ),
            )
            for task in normalized["tasks"]:
                self.connection.execute(
                    "INSERT INTO tasks(campaign_id,task_id,idempotency_key,spec_json,status) VALUES (?,?,?,?,?)",
                    (
                        campaign_id,
                        task["task_id"],
                        task["idempotency_key"],
                        _canonical_json(task),
                        "pending",
                    ),
                )
        return self.snapshot(campaign_id)

    def manifest(self, campaign_id: str) -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT manifest_json FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if not row:
            raise KeyError(campaign_id)
        return json.loads(row["manifest_json"])

    def task_rows(self, campaign_id: str) -> List[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM tasks WHERE campaign_id=? ORDER BY rowid", (campaign_id,)
        ).fetchall()

    def attempts(self, campaign_id: str, task_id: str = "") -> List[Dict[str, Any]]:
        params: List[Any] = [campaign_id]
        where = "campaign_id=?"
        if task_id:
            where += " AND task_id=?"
            params.append(task_id)
        rows = self.connection.execute(
            "SELECT * FROM attempts WHERE %s ORDER BY started_ts, attempt_no" % where,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def snapshot(self, campaign_id: str) -> Dict[str, Any]:
        campaign = self.connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if not campaign:
            raise KeyError(campaign_id)
        tasks = []
        for row in self.task_rows(campaign_id):
            task = dict(row)
            task["spec"] = json.loads(task.pop("spec_json"))
            if task.get("result_json"):
                task["result"] = json.loads(task.pop("result_json"))
            tasks.append(task)
        result = dict(campaign)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        result["tasks"] = tasks
        result["attempts"] = self.attempts(campaign_id)
        return result


Executor = Callable[[Mapping[str, Any], int], TaskOutcome]


class ExperimentalCampaignRunner:
    """Run a manifest through a supplied fake/adapter executor."""

    def __init__(self, store: ExperimentalCampaignStore, executor: Executor):
        self.store = store
        self.executor = executor

    def _mark_blocked(self, campaign_id: str) -> bool:
        rows = {row["task_id"]: row for row in self.store.task_rows(campaign_id)}
        changed = False
        with self.store.connection:
            for row in rows.values():
                if row["status"] != "pending":
                    continue
                spec = json.loads(row["spec_json"])
                dependency = spec["depends_on"]
                if dependency["mode"] != "afterok":
                    continue
                states = [rows[item]["status"] for item in dependency["tasks"]]
                if any(state in TERMINAL_TASK_STATES - {"succeeded"} for state in states):
                    self.store.connection.execute(
                        "UPDATE tasks SET status='blocked' WHERE campaign_id=? AND task_id=?",
                        (campaign_id, row["task_id"]),
                    )
                    changed = True
        return changed

    def _ready(self, campaign_id: str, now: float) -> List[sqlite3.Row]:
        rows = {row["task_id"]: row for row in self.store.task_rows(campaign_id)}
        ready = []
        for row in rows.values():
            if row["status"] != "pending" or row["next_eligible_ts"] > now:
                continue
            spec = json.loads(row["spec_json"])
            dependency = spec["depends_on"]
            states = [rows[item]["status"] for item in dependency["tasks"]]
            if dependency["mode"] == "afterok" and all(
                state == "succeeded" for state in states
            ):
                ready.append(row)
            elif dependency["mode"] == "afterany" and all(
                state in TERMINAL_TASK_STATES for state in states
            ):
                ready.append(row)
        return ready

    def _start(self, campaign_id: str, row: sqlite3.Row) -> Dict[str, Any]:
        previous = self.store.connection.execute(
            "SELECT attempt_id FROM attempts WHERE campaign_id=? AND task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (campaign_id, row["task_id"]),
        ).fetchone()
        attempt_no = int(row["attempt_count"]) + 1
        attempt_id = "%s.%s.%d.%s" % (
            campaign_id,
            row["task_id"],
            attempt_no,
            uuid.uuid4().hex[:8],
        )
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET status='running', attempt_count=? WHERE campaign_id=? AND task_id=?",
                (attempt_no, campaign_id, row["task_id"]),
            )
            self.store.connection.execute(
                "INSERT INTO attempts(attempt_id,campaign_id,task_id,attempt_no,parent_attempt_id,status,started_ts) VALUES (?,?,?,?,?,'running',?)",
                (
                    attempt_id,
                    campaign_id,
                    row["task_id"],
                    attempt_no,
                    previous["attempt_id"] if previous else None,
                    time.time(),
                ),
            )
        return {
            "attempt_id": attempt_id,
            "attempt_no": attempt_no,
            "task_id": row["task_id"],
            "spec": json.loads(row["spec_json"]),
        }

    def _finish(
        self, campaign_id: str, attempt: Mapping[str, Any], outcome: TaskOutcome
    ) -> None:
        manifest = self.store.manifest(campaign_id)
        spec = attempt["spec"]
        failure_class = outcome.failure_class
        if outcome.kind == "success":
            task_state = "succeeded"
            attempt_state = "succeeded"
            next_eligible = 0.0
        elif outcome.kind == "scientific_failure":
            # This branch is deliberately terminal regardless of max_attempts.
            task_state = "scientific_failed"
            attempt_state = "scientific_failed"
            next_eligible = 0.0
        else:
            preregistered = (
                failure_class in manifest["operational_retry_allowlist"]
                and failure_class not in NEVER_RETRY_OPERATIONAL_CLASSES
            )
            retry_available = int(attempt["attempt_no"]) < int(
                spec["retry"]["max_attempts"]
            )
            if preregistered and retry_available:
                task_state = "pending"
                attempt_state = "operational_retry_scheduled"
                next_eligible = time.time() + float(spec["retry"]["backoff_seconds"])
            else:
                task_state = "operational_failed"
                attempt_state = "operational_failed"
                next_eligible = 0.0
        result_json = _canonical_json(dict(outcome.result))
        now = time.time()
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE attempts SET status=?, failure_kind=?, failure_class=?, result_json=?, finished_ts=? WHERE attempt_id=?",
                (
                    attempt_state,
                    outcome.kind,
                    failure_class or None,
                    result_json,
                    now,
                    attempt["attempt_id"],
                ),
            )
            self.store.connection.execute(
                "UPDATE tasks SET status=?, next_eligible_ts=?, result_json=?, failure_class=? WHERE campaign_id=? AND task_id=?",
                (
                    task_state,
                    next_eligible,
                    result_json,
                    failure_class or None,
                    campaign_id,
                    attempt["task_id"],
                ),
            )

    def run(self, campaign_id: str) -> Dict[str, Any]:
        manifest = self.store.manifest(campaign_id)
        max_concurrency = int(manifest["max_concurrency"])
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE campaigns SET status='running', updated_ts=? WHERE campaign_id=?",
                (time.time(), campaign_id),
            )
        active = {}
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            while True:
                self._mark_blocked(campaign_id)
                for row in self._ready(campaign_id, time.time()):
                    if len(active) >= max_concurrency:
                        break
                    attempt = self._start(campaign_id, row)
                    future = pool.submit(
                        self.executor, attempt["spec"], attempt["attempt_no"]
                    )
                    active[future] = attempt

                if active:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        attempt = active.pop(future)
                        try:
                            outcome = future.result()
                            if not isinstance(outcome, TaskOutcome):
                                raise TypeError("executor must return TaskOutcome")
                        except Exception as exc:
                            outcome = TaskOutcome.operational_failure(
                                "executor_exception",
                                {"exception_type": type(exc).__name__, "message": str(exc)},
                            )
                        self._finish(campaign_id, attempt, outcome)
                    continue

                rows = self.store.task_rows(campaign_id)
                if all(row["status"] in TERMINAL_TASK_STATES for row in rows):
                    break
                eligible = [
                    float(row["next_eligible_ts"])
                    for row in rows
                    if row["status"] == "pending" and row["next_eligible_ts"] > 0
                ]
                if eligible:
                    time.sleep(max(0.0, min(eligible) - time.time()))
                    continue
                raise RuntimeError("campaign made no progress")

        rows = self.store.task_rows(campaign_id)
        final_status = (
            "succeeded"
            if all(row["status"] == "succeeded" for row in rows)
            else "completed_with_failures"
        )
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE campaigns SET status=?, updated_ts=? WHERE campaign_id=?",
                (final_status, time.time(), campaign_id),
            )
        return self.store.snapshot(campaign_id)
