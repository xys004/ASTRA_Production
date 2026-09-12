"""The other provenance callers must also resolve HEAD without a git subprocess.

`core/client_validation.py::_git_commit` and
`core/external_benchmarks.py::_git_commit` used to shell out to
`git rev-parse HEAD`, which can wedge the MCP server's hot path indefinitely
(a stuck `git rev-parse HEAD` was seen alive 30+ min despite a timeout). Both
now go through `core.git_head`. These tests pin that: each reads a real repo's
HEAD by file, spawns no git subprocess, and keeps its original sentinel when
HEAD cannot be resolved.
"""
import unittest
from pathlib import Path

import core.git_head as git_head
from core.client_validation import _git_commit as client_git_commit
from core.external_benchmarks import _git_commit as benchmarks_git_commit


class _NoGitSubprocess:
    def __init__(self):
        self.calls = 0

    def __enter__(self):
        self._orig = git_head.subprocess.run

        def _boom(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"git subprocess must not run: {args!r}")

        git_head.subprocess.run = _boom
        return self

    def __exit__(self, *exc):
        git_head.subprocess.run = self._orig
        return False


REPO_ROOT = Path(__file__).resolve().parents[1]


class ClientValidationGitCommitTests(unittest.TestCase):
    def test_reads_real_repo_head_without_subprocess(self):
        with _NoGitSubprocess() as guard:
            commit = client_git_commit(REPO_ROOT)
        self.assertEqual(guard.calls, 0)
        self.assertRegex(commit, r"^[0-9a-f]{7,40}$")

    def test_missing_repo_returns_empty_string(self):
        # No refs to read, so the pure reader returns None; the caller yields
        # its sentinel. (The hardened last-resort subprocess may run here, off
        # the hot path, which is fine -- it is bounded and prompt-free.)
        import tempfile

        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(git_head.read_head_commit(Path(empty)))
            self.assertEqual(client_git_commit(Path(empty)), "")


class ExternalBenchmarksGitCommitTests(unittest.TestCase):
    def test_reads_real_repo_head_without_subprocess(self):
        with _NoGitSubprocess() as guard:
            commit = benchmarks_git_commit(REPO_ROOT)
        self.assertEqual(guard.calls, 0)
        self.assertRegex(commit, r"^[0-9a-f]{7,40}$")

    def test_missing_repo_returns_unknown(self):
        import tempfile

        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(git_head.read_head_commit(Path(empty)))
            self.assertEqual(benchmarks_git_commit(Path(empty)), "unknown")


if __name__ == "__main__":
    unittest.main()
