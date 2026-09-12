import copy
from pathlib import Path
import tempfile
import unittest

from core.experimental_astrum_campaign_adapter import (
    ExperimentalAstrumCampaignAdapter,
    classify_scheduler_status,
)
from core.experimental_campaign_manager import (
    ExperimentalCampaignRunner,
    ExperimentalCampaignStore,
)


def task(task_id, behavior, retry=1, depends_on=None):
    return {
        "task_id": task_id,
        "idempotency_key": "adapter-%s-v1" % task_id,
        "depends_on": depends_on or {"mode": "afterok", "tasks": []},
        "retry": {"max_attempts": retry, "backoff_seconds": 0},
        "payload": {
            "behavior": behavior,
            "scheduler_request": {
                "code": "print('VERDICT: PASS')",
                "engine": "python",
                "project": "campaign-adapter-pilot",
                "priority": 0,
                "cpu_slots": 1,
                "gpu_slots": 0,
                "memory_mb": 128,
                "timeout_seconds": 30,
            },
        },
    }


MANIFEST = {
    "schema_version": 1,
    "campaign_id": "adapter-pilot",
    "max_concurrency": 2,
    "operational_retry_allowlist": ["scheduler_failed"],
    "tasks": [
        task("operational", "operational_once", retry=2),
        task("scientific", "scientific_fail", retry=5),
        task("plain_a", "success"),
        task("plain_b", "success"),
        task(
            "aggregate",
            "success",
            depends_on={
                "mode": "afterany",
                "tasks": ["operational", "scientific", "plain_a", "plain_b"],
            },
        ),
    ],
}


class FakeSchedulerGateway:
    def __init__(self):
        self.submissions = []
        self.statuses = {}
        self.job_counter = 0
        self.jobs_by_key = {}

    def submit(self, request):
        request = copy.deepcopy(dict(request))
        key = request.get("idempotency_key")
        if key in self.jobs_by_key:
            job_id, original = self.jobs_by_key[key]
            if request != original:
                return {"error": "idempotency_key already exists with a different request"}
            self.submissions.append((job_id, request))
            return {"job_id": job_id, "status": "queued", "idempotent_replay": True}
        self.job_counter += 1
        job_id = "fake-job-%d" % self.job_counter
        self.submissions.append((job_id, request))
        if key:
            self.jobs_by_key[key] = (job_id, request)
        self.statuses[job_id] = [
            {"job_id": job_id, "status": "succeeded", "exit_code": 0, "verdict": "PASS"}
        ]
        return {"job_id": job_id, "status": "queued"}

    def job(self, job_id):
        values = self.statuses[job_id]
        if len(values) > 1:
            return copy.deepcopy(values.pop(0))
        return copy.deepcopy(values[0])


class BehavioralFakeGateway(FakeSchedulerGateway):
    def __init__(self):
        super().__init__()
        self.behavior_counts = {}

    def submit(self, request):
        result = super().submit(request)
        job_id = result["job_id"]
        # Task behavior is carried only by the test's code suffix below.
        behavior = request["code"].split("# behavior:")[-1].strip()
        count = self.behavior_counts.get(behavior, 0) + 1
        self.behavior_counts[behavior] = count
        if behavior == "operational_once" and count == 1:
            self.statuses[job_id] = [
                {"job_id": job_id, "status": "failed", "exit_code": 1, "verdict": "NONE"}
            ]
        elif behavior == "scientific_fail":
            self.statuses[job_id] = [
                {"job_id": job_id, "status": "failed", "exit_code": 1, "verdict": "FAIL"}
            ]
        return result


class ExperimentalAstrumCampaignAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExperimentalCampaignStore(Path(self.temp.name) / "adapter.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_fail_closed_scheduler_classification(self):
        self.assertEqual(
            classify_scheduler_status(
                {"status": "succeeded", "exit_code": 0, "verdict": "PASS"}
            ).kind,
            "success",
        )
        self.assertEqual(
            classify_scheduler_status(
                {"status": "failed", "exit_code": 1, "verdict": "FAIL"}
            ).kind,
            "scientific_failure",
        )
        self.assertEqual(
            classify_scheduler_status(
                {"status": "succeeded", "exit_code": 0, "verdict": "NONE"}
            ).kind,
            "scientific_failure",
        )
        self.assertEqual(
            classify_scheduler_status(
                {"status": "failed", "exit_code": 1, "verdict": "NONE"}
            ).failure_class,
            "scheduler_failed",
        )
        self.assertIsNone(classify_scheduler_status({"status": "running"}))

    def test_binding_is_idempotent_for_one_campaign_task_attempt(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "binding-idempotency"
        manifest["tasks"] = [manifest["tasks"][2]]
        self.store.register(manifest)
        runner = ExperimentalCampaignRunner(self.store, lambda *_: None)
        attempt = runner._start(manifest["campaign_id"], self.store.task_rows(manifest["campaign_id"])[0])
        gateway = FakeSchedulerGateway()
        first_adapter = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        )
        first = first_adapter.bind_or_submit(attempt["spec"], attempt["attempt_no"])
        restarted_adapter = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        )
        second = restarted_adapter.bind_or_submit(attempt["spec"], attempt["attempt_no"])
        self.assertEqual(first, second)
        self.assertEqual(len(gateway.submissions), 1)
        self.assertEqual(len(restarted_adapter.bindings()), 1)

    def test_restart_reconciliation_finishes_existing_job_without_resubmit(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "restart-reconcile"
        manifest["tasks"] = [manifest["tasks"][2]]
        self.store.register(manifest)
        runner = ExperimentalCampaignRunner(self.store, lambda *_: None)
        attempt = runner._start(manifest["campaign_id"], self.store.task_rows(manifest["campaign_id"])[0])
        gateway = FakeSchedulerGateway()
        adapter = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        )
        job_id = adapter.bind_or_submit(attempt["spec"], attempt["attempt_no"])
        gateway.statuses[job_id] = [{"job_id": job_id, "status": "running"}]

        restarted = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        )
        self.assertEqual(restarted.reconcile_once()["active_job_ids"], [job_id])
        gateway.statuses[job_id] = [
            {"job_id": job_id, "status": "succeeded", "exit_code": 0, "verdict": "PASS"}
        ]
        self.assertEqual(len(restarted.reconcile_once()["completed_attempt_ids"]), 1)
        self.assertEqual(self.store.task_rows(manifest["campaign_id"])[0]["status"], "succeeded")
        self.assertEqual(len(gateway.submissions), 1)

    def test_transient_status_rpc_error_keeps_original_binding(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "status-rpc-reconcile"
        manifest["tasks"] = [manifest["tasks"][2]]
        self.store.register(manifest)
        gateway = FakeSchedulerGateway()
        adapter = ExperimentalAstrumCampaignAdapter(
            self.store,
            manifest["campaign_id"],
            gateway,
            poll_interval_seconds=0,
            max_poll_seconds=1,
        )
        original_submit = gateway.submit

        def submit_with_transient_poll(request):
            response = original_submit(request)
            job_id = response["job_id"]
            gateway.statuses[job_id] = [
                {"error": "temporary ssh failure"},
                {"job_id": job_id, "status": "running"},
                {"job_id": job_id, "status": "succeeded", "exit_code": 0, "verdict": "PASS"},
            ]
            return response

        gateway.submit = submit_with_transient_poll
        result = adapter.run()
        self.assertEqual(result["tasks"][0]["status"], "succeeded")
        self.assertEqual(len(gateway.submissions), 1)
        self.assertEqual(len(adapter.bindings()), 1)

    def test_persistently_unknown_submission_stops_after_idempotent_retries(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "submission-unknown"
        manifest["operational_retry_allowlist"].append("scheduler_submission_unknown")
        manifest["tasks"] = [manifest["tasks"][0]]
        manifest["tasks"][0]["retry"]["max_attempts"] = 3
        self.store.register(manifest)

        class UnknownSubmissionGateway(FakeSchedulerGateway):
            def submit(self, request):
                self.submissions.append(("unknown", dict(request)))
                return {"error": "connection dropped"}

        gateway = UnknownSubmissionGateway()
        result = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        ).run()
        self.assertEqual(result["tasks"][0]["status"], "operational_failed")
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(len(gateway.submissions), 2)
        self.assertEqual(len(result["attempts"]), 1)

    def test_lost_submit_response_recovers_same_native_scheduler_job(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "lost-submit-native-recovery"
        manifest["tasks"] = [manifest["tasks"][2]]
        self.store.register(manifest)

        class LostFirstResponseGateway(FakeSchedulerGateway):
            def __init__(self):
                super().__init__()
                self.lost = False

            def submit(self, request):
                response = super().submit(request)
                if not self.lost:
                    self.lost = True
                    return {"error": "response lost after scheduler acceptance"}
                return response

        gateway = LostFirstResponseGateway()
        result = ExperimentalAstrumCampaignAdapter(
            self.store,
            manifest["campaign_id"],
            gateway,
            poll_interval_seconds=0,
            submission_attempts=2,
        ).run()
        self.assertEqual(result["tasks"][0]["status"], "succeeded")
        self.assertEqual(len(gateway.submissions), 2)
        self.assertEqual(gateway.job_counter, 1)
        self.assertEqual(gateway.submissions[0][0], gateway.submissions[1][0])
        self.assertEqual(
            gateway.submissions[0][1]["idempotency_key"],
            gateway.submissions[1][1]["idempotency_key"],
        )

    def test_restart_reconciles_acceptance_lost_before_local_binding(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "restart-before-local-binding"
        manifest["tasks"] = [manifest["tasks"][2]]
        self.store.register(manifest)
        runner = ExperimentalCampaignRunner(self.store, lambda *_: None)
        attempt = runner._start(
            manifest["campaign_id"], self.store.task_rows(manifest["campaign_id"])[0]
        )

        class LostFirstResponseGateway(FakeSchedulerGateway):
            def __init__(self):
                super().__init__()
                self.lost = False

            def submit(self, request):
                response = super().submit(request)
                if not self.lost:
                    self.lost = True
                    return {"error": "response lost after scheduler acceptance"}
                return response

        gateway = LostFirstResponseGateway()
        first_process = ExperimentalAstrumCampaignAdapter(
            self.store,
            manifest["campaign_id"],
            gateway,
            poll_interval_seconds=0,
            submission_attempts=1,
        )
        with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
            first_process.bind_or_submit(attempt["spec"], attempt["attempt_no"])
        self.assertEqual(first_process.bindings(), [])

        restarted = ExperimentalAstrumCampaignAdapter(
            self.store,
            manifest["campaign_id"],
            gateway,
            poll_interval_seconds=0,
        )
        reconciled = restarted.reconcile_once()
        self.assertEqual(len(reconciled["completed_attempt_ids"]), 1)
        self.assertEqual(self.store.task_rows(manifest["campaign_id"])[0]["status"], "succeeded")
        self.assertEqual(gateway.job_counter, 1)
        self.assertEqual(len(gateway.submissions), 2)

    def test_adapter_end_to_end_retries_operational_but_not_scientific_failure(self):
        manifest = copy.deepcopy(MANIFEST)
        for item in manifest["tasks"]:
            behavior = item["payload"]["behavior"]
            item["payload"]["scheduler_request"]["code"] += "\n# behavior:%s" % behavior
        self.store.register(manifest)
        gateway = BehavioralFakeGateway()
        adapter = ExperimentalAstrumCampaignAdapter(
            self.store,
            manifest["campaign_id"],
            gateway,
            poll_interval_seconds=0,
            max_poll_seconds=1,
        )
        result = adapter.run()
        states = {row["task_id"]: row["status"] for row in result["tasks"]}
        self.assertEqual(states["operational"], "succeeded")
        self.assertEqual(states["scientific"], "scientific_failed")
        self.assertEqual(states["aggregate"], "succeeded")
        self.assertEqual(len(self.store.attempts(manifest["campaign_id"], "operational")), 2)
        self.assertEqual(len(self.store.attempts(manifest["campaign_id"], "scientific")), 1)
        self.assertEqual(result["status"], "completed_with_failures")

    def test_cancelled_job_never_retries_even_if_manifest_allowlists_it(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["campaign_id"] = "cancel-never-retry"
        manifest["operational_retry_allowlist"].append("scheduler_cancelled")
        manifest["tasks"] = [manifest["tasks"][0]]
        manifest["tasks"][0]["retry"]["max_attempts"] = 3
        self.store.register(manifest)
        gateway = FakeSchedulerGateway()
        original_submit = gateway.submit

        def submit_cancelled(request):
            response = original_submit(request)
            gateway.statuses[response["job_id"]] = [
                {"job_id": response["job_id"], "status": "cancelled", "exit_code": 130}
            ]
            return response

        gateway.submit = submit_cancelled
        result = ExperimentalAstrumCampaignAdapter(
            self.store, manifest["campaign_id"], gateway, poll_interval_seconds=0
        ).run()
        self.assertEqual(result["tasks"][0]["status"], "operational_failed")
        self.assertEqual(len(result["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
