import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remote.astra_cluster_manager import ClusterStore, rpc, run_job


class ClusterManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "ASTRA_CLUSTER_CPU_SLOTS": "8",
                "ASTRA_CLUSTER_CPU_RESERVE": "1",
                "ASTRA_CLUSTER_GPU_SLOTS": "1",
                "ASTRA_CLUSTER_MEMORY_TOTAL_MB": "32768",
                "ASTRA_CLUSTER_MEMORY_RESERVE_MB": "4096",
            },
            clear=False,
        )
        self.environment.start()
        self.store = ClusterStore(self.root)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def submit(self, client_id="nelson", code="print('VERDICT: PASS')", **extra):
        request = {
            "action": "submit",
            "client_id": client_id,
            "project": "shared-test",
            "code": code,
            "timeout_seconds": 30,
            **extra,
        }
        return rpc(self.store, request)

    def test_submit_persists_attribution_resources_and_isolated_input(self):
        with patch.dict(
            os.environ,
            {"SSH_CONNECTION": "100.64.0.7 43210 100.64.0.8 22"},
            clear=False,
        ):
            job = self.submit(
                client_id="Gabriel Abellan",
                code="# ASTRA_ENGINE: sage\nprint('VERDICT: PASS')",
            )
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["client_id"], "gabriel-abellan")
        self.assertEqual(job["project"], "shared-test")
        self.assertEqual(job["engine"], "sage")
        self.assertEqual(job["cpu_slots"], 4)
        self.assertEqual(job["source_ip"], "100.64.0.7")
        request_path = Path(job["artifact_dir"]) / "request.json"
        persisted = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["job_id"], job["job_id"])
        self.assertEqual(persisted["client_id"], "gabriel-abellan")

    def test_native_idempotency_replays_same_job_after_store_restart(self):
        first = self.submit(idempotency_key="campaign-a-task-1-attempt-1")
        restarted = ClusterStore(self.root)
        replay = rpc(
            restarted,
            {
                "action": "submit",
                "client_id": "nelson",
                "project": "shared-test",
                "code": "print('VERDICT: PASS')",
                "timeout_seconds": 30,
                "idempotency_key": "campaign-a-task-1-attempt-1",
            },
        )
        self.assertEqual(replay["job_id"], first["job_id"])
        self.assertTrue(replay["idempotent_replay"])
        with restarted.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.assertEqual(count, 1)

    def test_native_idempotency_rejects_changed_request(self):
        first = self.submit(idempotency_key="immutable-request")
        conflict = self.submit(
            code="print('different')", idempotency_key="immutable-request"
        )
        self.assertIn("different request", conflict["error"])
        with self.store.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(self.store.status(first["job_id"])["status"], "queued")

    def test_callers_without_idempotency_key_remain_non_deduplicated(self):
        first = self.submit()
        second = self.submit()
        self.assertNotEqual(first["job_id"], second["job_id"])

    def test_scheduler_rotates_between_clients(self):
        first_nelson = self.submit("nelson")
        self.submit("nelson")
        gabriel = self.submit("gabriel")
        first = self.store.reserve_next()
        self.assertEqual(first["job_id"], first_nelson["job_id"])
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='succeeded', finished_ts=? WHERE job_id=?",
                (first["started_ts"] + 1, first["job_id"]),
            )
        second = self.store.reserve_next()
        self.assertEqual(second["job_id"], gabriel["job_id"])

    def test_queued_job_can_be_cancelled(self):
        submitted = self.submit("gabriel")
        cancelled = rpc(
            self.store,
            {
                "action": "cancel",
                "job_id": submitted["job_id"],
                "client_id": "nelson",
            },
        )
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])

    def test_gpu_slot_blocks_another_gpu_job_but_not_cpu_work(self):
        first_gpu = self.submit(
            "nelson",
            code="import torch\nprint(torch.cuda.is_available())",
        )
        self.submit(
            "gabriel",
            code="import cupy\nprint(cupy.cuda.runtime.getDeviceCount())",
        )
        cpu_job = self.submit("gabriel", code="print(2 + 2)")
        reserved_gpu = self.store.reserve_next()
        self.assertEqual(reserved_gpu["job_id"], first_gpu["job_id"])
        self.assertEqual(reserved_gpu["gpu_slots"], 1)
        reserved_cpu = self.store.reserve_next()
        self.assertEqual(reserved_cpu["job_id"], cpu_job["job_id"])
        self.assertEqual(reserved_cpu["gpu_slots"], 0)

    def test_memory_reservation_blocks_oversubscription_but_not_smaller_work(self):
        first_large = self.submit("nelson", memory_mb=24000)
        second_large = self.submit("gabriel", memory_mb=8000)
        small = self.submit("gabriel", memory_mb=2048)

        reserved_large = self.store.reserve_next()
        self.assertEqual(reserved_large["job_id"], first_large["job_id"])
        reserved_small = self.store.reserve_next()
        self.assertEqual(reserved_small["job_id"], small["job_id"])
        self.assertEqual(self.store.status(second_large["job_id"])["status"], "queued")

        capacity = self.store.capacity()
        self.assertEqual(capacity["memory_slots_mb"], 28672)
        self.assertEqual(capacity["used_memory_mb"], 26048)
        self.assertEqual(capacity["available_memory_mb"], 2624)

    def test_submit_rejects_memory_request_above_allocatable_capacity(self):
        rejected = self.submit("nelson", memory_mb=28673)
        self.assertIn("exceeds allocatable ASTRUM memory", rejected["error"])

    def test_runner_writes_terminal_result_and_verdict(self):
        submitted = self.submit("nelson")
        reserved = self.store.reserve_next()
        self.assertEqual(reserved["job_id"], submitted["job_id"])
        worker = Path(__file__).resolve().parents[1] / "remote" / "astra_remote_worker.py"
        with patch.dict(
            os.environ,
            {
                "ASTRA_CLUSTER_WORKER": str(worker),
                "ASTRA_CLUSTER_PYTHON": os.sys.executable,
            },
            clear=False,
        ):
            exit_code = run_job(self.store, submitted["job_id"])
        self.assertEqual(exit_code, 0)
        status = self.store.status(submitted["job_id"])
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["verdict"], "PASS")
        self.assertEqual(status["result"]["cluster_job_id"], submitted["job_id"])
        self.assertEqual(status["result"]["client_id"], "nelson")

    def test_successful_lean_typecheck_is_a_pass_verdict(self):
        submitted = self.submit(
            "nelson",
            code="# ASTRA_ENGINE: lean\nexample : True := by trivial",
        )
        self.store.reserve_next()
        fake_worker = self.root / "fake_lean_worker.py"
        fake_worker.write_text(
            "import json, sys\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'stdout':'','stderr':'','exit_code':0,'engine':'lean4'}))\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {
                "ASTRA_CLUSTER_WORKER": str(fake_worker),
                "ASTRA_CLUSTER_PYTHON": os.sys.executable,
            },
            clear=False,
        ):
            self.assertEqual(run_job(self.store, submitted["job_id"]), 0)
        status = self.store.status(submitted["job_id"])
        self.assertEqual(status["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
