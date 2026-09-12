import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from core.experimental_campaign_manager import (
    CampaignManifestError,
    ExperimentalCampaignRunner,
    ExperimentalCampaignStore,
    TaskOutcome,
    validate_manifest,
)


PILOT = {
    "schema_version": 1,
    "campaign_id": "pilot-four-plus-aggregate",
    "max_concurrency": 2,
    "operational_retry_allowlist": ["transient_transport"],
    "tasks": [
        {
            "task_id": "small_a",
            "idempotency_key": "pilot-small-a-v1",
            "payload": {"behavior": "success"},
        },
        {
            "task_id": "small_b",
            "idempotency_key": "pilot-small-b-v1",
            "payload": {"behavior": "operational_once"},
            "retry": {"max_attempts": 2, "backoff_seconds": 0},
        },
        {
            "task_id": "small_c",
            "idempotency_key": "pilot-small-c-v1",
            "payload": {"behavior": "scientific_fail"},
            "retry": {"max_attempts": 5, "backoff_seconds": 0},
        },
        {
            "task_id": "small_d",
            "idempotency_key": "pilot-small-d-v1",
            "payload": {"behavior": "success"},
        },
        {
            "task_id": "aggregate",
            "idempotency_key": "pilot-aggregate-v1",
            "depends_on": {
                "mode": "afterany",
                "tasks": ["small_a", "small_b", "small_c", "small_d"],
            },
            "payload": {"behavior": "success", "role": "aggregate"},
        },
    ],
}


class FakeExecutor:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def __call__(self, task, attempt_no):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.015)
            behavior = task["payload"]["behavior"]
            if behavior == "operational_once" and attempt_no == 1:
                return TaskOutcome.operational_failure(
                    "transient_transport", {"retryable": True}
                )
            if behavior == "scientific_fail":
                return TaskOutcome.scientific_failure(
                    {"verdict": "FAIL", "physical_gate": False}
                )
            return TaskOutcome.success({"verdict": "PASS"})
        finally:
            with self.lock:
                self.active -= 1


class ExperimentalCampaignManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExperimentalCampaignStore(Path(self.temp.name) / "pilot.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_pilot_four_tasks_plus_afterany_aggregator(self):
        self.store.register(PILOT)
        executor = FakeExecutor()
        result = ExperimentalCampaignRunner(self.store, executor).run(
            PILOT["campaign_id"]
        )
        states = {task["task_id"]: task["status"] for task in result["tasks"]}
        self.assertEqual(states["small_a"], "succeeded")
        self.assertEqual(states["small_b"], "succeeded")
        self.assertEqual(states["small_c"], "scientific_failed")
        self.assertEqual(states["small_d"], "succeeded")
        self.assertEqual(states["aggregate"], "succeeded")
        self.assertEqual(result["status"], "completed_with_failures")
        self.assertEqual(executor.max_active, 2)

    def test_operational_retry_has_lineage_and_scientific_fail_never_retries(self):
        self.store.register(PILOT)
        ExperimentalCampaignRunner(self.store, FakeExecutor()).run(PILOT["campaign_id"])
        operational = self.store.attempts(PILOT["campaign_id"], "small_b")
        scientific = self.store.attempts(PILOT["campaign_id"], "small_c")
        self.assertEqual(len(operational), 2)
        self.assertEqual(operational[0]["status"], "operational_retry_scheduled")
        self.assertEqual(operational[1]["parent_attempt_id"], operational[0]["attempt_id"])
        self.assertEqual(len(scientific), 1)
        self.assertEqual(scientific[0]["status"], "scientific_failed")

    def test_unregistered_operational_failure_is_not_retried(self):
        manifest = json.loads(json.dumps(PILOT))
        manifest["campaign_id"] = "unregistered-operational"
        manifest["tasks"] = [manifest["tasks"][1]]

        def executor(task, attempt_no):
            return TaskOutcome.operational_failure("unknown_failure", {})

        self.store.register(manifest)
        result = ExperimentalCampaignRunner(self.store, executor).run(
            manifest["campaign_id"]
        )
        self.assertEqual(result["tasks"][0]["status"], "operational_failed")
        self.assertEqual(len(result["attempts"]), 1)

    def test_afterok_dependent_is_blocked_by_scientific_failure(self):
        manifest = json.loads(json.dumps(PILOT))
        manifest["campaign_id"] = "afterok-block"
        manifest["tasks"] = [manifest["tasks"][2], manifest["tasks"][4]]
        manifest["tasks"][1]["depends_on"] = {
            "mode": "afterok",
            "tasks": ["small_c"],
        }
        self.store.register(manifest)
        result = ExperimentalCampaignRunner(self.store, FakeExecutor()).run(
            manifest["campaign_id"]
        )
        states = {task["task_id"]: task["status"] for task in result["tasks"]}
        self.assertEqual(states["small_c"], "scientific_failed")
        self.assertEqual(states["aggregate"], "blocked")

    def test_registration_is_idempotent_but_manifest_mutation_fails_closed(self):
        first = self.store.register(PILOT)
        second = self.store.register(PILOT)
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        changed = json.loads(json.dumps(PILOT))
        changed["max_concurrency"] = 3
        with self.assertRaises(CampaignManifestError):
            self.store.register(changed)

    def test_manifest_rejects_duplicate_keys_cycles_and_bad_dependency_mode(self):
        duplicate = json.loads(json.dumps(PILOT))
        duplicate["tasks"][1]["idempotency_key"] = duplicate["tasks"][0][
            "idempotency_key"
        ]
        with self.assertRaises(CampaignManifestError):
            validate_manifest(duplicate)

        cycle = json.loads(json.dumps(PILOT))
        cycle["tasks"][0]["depends_on"] = {"mode": "afterok", "tasks": ["aggregate"]}
        with self.assertRaises(CampaignManifestError):
            validate_manifest(cycle)

        bad_mode = json.loads(json.dumps(PILOT))
        bad_mode["tasks"][0]["depends_on"] = {"mode": "unless", "tasks": []}
        with self.assertRaises(CampaignManifestError):
            validate_manifest(bad_mode)

        typo = json.loads(json.dumps(PILOT))
        typo["max_concurency"] = 3
        with self.assertRaises(CampaignManifestError):
            validate_manifest(typo)

    def test_documented_pilot_manifest_matches_the_executable_fixture(self):
        path = Path(__file__).resolve().parents[1] / "docs" / "ASTRUM_CAMPAIGN_MANAGER_PILOT.json"
        documented = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(validate_manifest(documented), validate_manifest(PILOT))


if __name__ == "__main__":
    unittest.main()
