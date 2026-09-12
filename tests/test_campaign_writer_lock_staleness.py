"""A crashed writer must not wedge a campaign forever.

Hit twice on 2026-08-16 while driving the travelling-wave campaign: one script
raised mid-append and another never called close(), and each left a writer.lock
behind that blocked every subsequent step until the file was deleted by hand. A
long-running research programme cannot depend on someone noticing.

The cycle lock in core/runtime_resources.py already reclaims dead holders, so
this makes the two locks behave the same way rather than inventing a rule.
"""
import os
import tempfile
import unittest
from pathlib import Path

from core.campaign_store import CampaignStore, SingleWriterError

COMMIT = "0" * 40


def store(root: Path) -> CampaignStore:
    return CampaignStore(root, "cmp_" + "a" * 16, source_commit=COMMIT)


class StaleLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = store(self.root)
        self.lock = self.store.campaign_dir / "writer.lock"
        self.store.campaign_dir.mkdir(parents=True, exist_ok=True)

    def _write_lock(self, body: str):
        self.lock.write_text(body, encoding="utf-8")

    def test_a_dead_holder_is_reclaimed(self):
        # A pid that cannot be running: the lock is debris from a crash.
        self._write_lock("pid=999999999\nacquired=2026-08-16T00:00:00Z\n")
        self.store._acquire_writer()
        self.addCleanup(self.store.close)
        self.assertIsNotNone(self.store._lock_fd)

    def test_an_unreadable_lock_is_reclaimed(self):
        """Debris with no pid line is still debris."""
        self._write_lock("garbage\n")
        self.store._acquire_writer()
        self.addCleanup(self.store.close)
        self.assertIsNotNone(self.store._lock_fd)

    def test_a_live_holder_is_still_refused(self):
        """Reclaiming dead locks must not make the lock meaningless."""
        self._write_lock(f"pid={os.getpid()}\nacquired=2026-08-16T00:00:00Z\n")
        with self.assertRaises(SingleWriterError) as caught:
            self.store._acquire_writer()
        self.assertIn(str(os.getpid()), str(caught.exception))

    def test_a_second_writer_in_process_is_still_refused(self):
        first = store(self.root)
        first._acquire_writer()
        self.addCleanup(first.close)
        second = store(self.root)
        with self.assertRaises(SingleWriterError):
            second._acquire_writer()

    def test_close_releases_so_the_next_writer_proceeds(self):
        first = store(self.root)
        first._acquire_writer()
        first.close()
        second = store(self.root)
        second._acquire_writer()
        self.addCleanup(second.close)
        self.assertIsNotNone(second._lock_fd)


if __name__ == "__main__":
    unittest.main()
