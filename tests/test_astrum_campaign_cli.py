import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.astrum_campaign import load_and_preflight, main


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "docs" / "ASTRUM_CAMPAIGN_REMOTE_SMOKE_V1.json"


class FakeGateway:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []
        self.jobs = {}

    def submit(self, request):
        request = copy.deepcopy(dict(request))
        key = request["idempotency_key"]
        with self.lock:
            self.calls.append(request)
            if key in self.jobs:
                job_id, original = self.jobs[key]
                if request != original:
                    return {"error": "idempotency_key already exists with a different request"}
                return {"job_id": job_id, "status": "queued", "idempotent_replay": True}
            job_id = "cli-fake-%d" % (len(self.jobs) + 1)
            self.jobs[key] = (job_id, request)
            return {"job_id": job_id, "status": "queued"}

    def job(self, job_id):
        return {
            "job_id": job_id,
            "status": "succeeded",
            "exit_code": 0,
            "verdict": "PASS",
        }


def invoke(argv, gateway_factory=lambda: None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv, gateway_factory=gateway_factory)
    return code, stdout.getvalue(), stderr.getvalue()


class AstrumCampaignCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "campaign.sqlite3"

    def tearDown(self):
        self.temporary.cleanup()

    def test_preregistered_remote_smoke_is_small_and_fail_closed(self):
        report = load_and_preflight(SMOKE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["task_count"], 5)
        self.assertEqual(report["max_concurrency"], 2)
        aggregate = next(
            task for task in report["manifest"]["tasks"] if task["task_id"] == "aggregate"
        )
        self.assertEqual(aggregate["depends_on"]["mode"], "afterany")
        self.assertEqual(len(aggregate["depends_on"]["tasks"]), 4)
        for request in report["scheduler_requests"].values():
            self.assertEqual(request["project"], "campaign-manager-smoke")
            self.assertEqual(request["cpu_slots"], 1)
            self.assertEqual(request["gpu_slots"], 0)
            self.assertEqual(request["memory_mb"], 128)
            self.assertEqual(request["timeout_seconds"], 60)

    def test_register_status_and_resume_without_network(self):
        factory_calls = []
        gateway = FakeGateway()

        def factory():
            factory_calls.append(True)
            return gateway

        code, stdout, stderr = invoke(
            ["register", "--manifest", str(SMOKE), "--db", str(self.db)], factory
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "registered")
        self.assertEqual(factory_calls, [])

        code, stdout, stderr = invoke(
            [
                "resume",
                "--campaign-id",
                "astrum-remote-smoke-v1",
                "--db",
                str(self.db),
                "--execute-remote",
                "--poll-interval-seconds",
                "0",
                "--max-poll-seconds",
                "1",
            ],
            factory,
        )
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(gateway.jobs), 5)
        self.assertEqual(len(factory_calls), 1)

        code, stdout, stderr = invoke(
            [
                "status",
                "--campaign-id",
                "astrum-remote-smoke-v1",
                "--db",
                str(self.db),
            ],
            factory,
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "succeeded")
        self.assertEqual(len(factory_calls), 1)

    def test_resume_requires_explicit_remote_acknowledgement(self):
        self.assertEqual(
            invoke(["register", "--manifest", str(SMOKE), "--db", str(self.db)])[0],
            0,
        )
        code, _, stderr = invoke(
            [
                "resume",
                "--campaign-id",
                "astrum-remote-smoke-v1",
                "--db",
                str(self.db),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--execute-remote", stderr)

    def test_preflight_rejects_invalid_scheduler_payload_without_gateway(self):
        manifest = json.loads(SMOKE.read_text(encoding="utf-8"))
        manifest["campaign_id"] = "invalid-smoke"
        manifest["tasks"][0]["payload"]["scheduler_request"]["unknown"] = True
        path = self.root / "invalid.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        factory_calls = []
        code, _, stderr = invoke(
            ["preflight", "--manifest", str(path)],
            lambda: factory_calls.append(True),
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown scheduler request keys", stderr)
        self.assertEqual(factory_calls, [])


if __name__ == "__main__":
    unittest.main()
