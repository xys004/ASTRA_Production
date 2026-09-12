"""Regression test: campaign calls must never wedge on a git subprocess.

`_resolve_source_commit` used to shell out to `git rev-parse HEAD` on the hot
path of every `astra_campaign_*` call, before any disk access. In the MCP
server context that subprocess could wedge indefinitely (a `git rev-parse HEAD`
was observed stuck for 30+ minutes despite a 10 s timeout), and because the
tool body runs inside `asyncio.to_thread`, a wedged subprocess hangs the whole
call until the client's wall timeout — for BOTH `astra_campaign_start` (new id,
before mkdir) and the read-only `astra_campaign_list`, which funnels through the
same resolver via `astra_campaign_status`.

The fix reads git ref files directly (pure local I/O, no child process). These
tests pin that down: the resolver produces the right commit, and neither
`astra_campaign_start` nor `astra_campaign_list` spawns a subprocess in a normal
checkout.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import core.campaign_api as api
import core.git_head as git_head
from core.campaign_api import (
    _git_dir,
    _read_head_commit,
    _resolve_source_commit,
    astra_campaign_list,
    astra_campaign_start,
)


class _NoGitSubprocess:
    """Context manager that fails loudly if a git subprocess is spawned.

    The HEAD resolver is centralized in ``core.git_head``; that module holds
    the only subprocess any provenance caller can reach, so guarding
    ``git_head.subprocess.run`` catches a regression from every caller
    (campaign_api, client_validation, external_benchmarks) at the source.
    """

    def __init__(self):
        self.calls = 0

    def __enter__(self):
        self._orig = git_head.subprocess.run

        def _boom(*args, **kwargs):
            self.calls += 1
            raise AssertionError(
                f"git subprocess must not run on the hot path: {args!r}"
            )

        git_head.subprocess.run = _boom
        return self

    def __exit__(self, *exc):
        git_head.subprocess.run = self._orig
        return False


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ReadHeadCommitTests(unittest.TestCase):
    def test_matches_the_real_repo_head(self):
        # The checkout under test is a real git repo; the direct reader must
        # agree with git itself.
        truth = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=api.ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(truth)
        self.assertEqual(_read_head_commit(api.ROOT), truth)

    def test_loose_ref(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            _write(root / ".git" / "HEAD", "ref: refs/heads/topic\n")
            _write(root / ".git" / "refs" / "heads" / "topic", sha + "\n")
            self.assertEqual(_read_head_commit(root), sha)

    def test_packed_refs_fallback(self):
        sha = "fedcba9876543210fedcba9876543210fedcba98"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            _write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
            _write(
                root / ".git" / "packed-refs",
                "# pack-refs with: peeled fully-peeled sorted\n"
                f"{sha} refs/heads/main\n"
                "^aaaabbbbccccddddeeeeffff0000111122223333\n",
            )
            self.assertEqual(_read_head_commit(root), sha)

    def test_detached_head(self):
        sha = "abcabcabcabcabcabcabcabcabcabcabcabcabca"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            _write(root / ".git" / "HEAD", sha + "\n")
            self.assertEqual(_read_head_commit(root), sha)

    def test_worktree_gitdir_file_form(self):
        sha = "1111222233334444555566667777888899990000"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            real_gitdir = root / "realgit"
            _write(real_gitdir / "HEAD", "ref: refs/heads/wt\n")
            _write(real_gitdir / "refs" / "heads" / "wt", sha + "\n")
            # .git is a file pointing at the real git dir (worktree/submodule).
            _write(root / ".git", f"gitdir: {real_gitdir}\n")
            self.assertEqual(_git_dir(root), real_gitdir)
            self.assertEqual(_read_head_commit(root), sha)

    def test_missing_git_returns_none(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(_read_head_commit(Path(root)))


class ResolveSourceCommitTests(unittest.TestCase):
    def test_explicit_wins_without_touching_git(self):
        sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        with _NoGitSubprocess():
            self.assertEqual(_resolve_source_commit(sha), sha)

    def test_env_override_without_touching_git(self):
        sha = "cafebabecafebabecafebabecafebabecafebabe"
        prev = os.environ.get("ASTRA_SOURCE_COMMIT")
        os.environ["ASTRA_SOURCE_COMMIT"] = sha
        try:
            with _NoGitSubprocess():
                self.assertEqual(_resolve_source_commit(None), sha)
        finally:
            if prev is None:
                os.environ.pop("ASTRA_SOURCE_COMMIT", None)
            else:
                os.environ["ASTRA_SOURCE_COMMIT"] = prev

    def test_normal_checkout_resolves_with_no_subprocess(self):
        prev = os.environ.pop("ASTRA_SOURCE_COMMIT", None)
        try:
            with _NoGitSubprocess():
                commit = _resolve_source_commit(None)
        finally:
            if prev is not None:
                os.environ["ASTRA_SOURCE_COMMIT"] = prev
        self.assertRegex(commit, r"^[0-9a-f]{7,40}$")


class CampaignHotPathNoSubprocessTests(unittest.TestCase):
    def test_start_and_list_spawn_no_git(self):
        with tempfile.TemporaryDirectory() as campaigns_root:
            campaigns_root = Path(campaigns_root)
            with _NoGitSubprocess() as guard:
                started = astra_campaign_start(
                    objective="Prove the bound holds under the stated hypotheses.",
                    success_definition="A cross-verified proof or a counterexample.",
                    deliverables=["A short note stating the exact bound"],
                    allowed_evidence_classes=[
                        "SYMBOLIC",
                        "NUMERICAL",
                        "COUNTEREXAMPLE",
                        "FORMAL",
                    ],
                    budget={
                        "cycles": 6,
                        "model_calls": 72,
                        "wall_seconds": 21600,
                        "execution_seconds": 3600,
                        "human_interventions": 1,
                        "remote_jobs": 0,
                    },
                    root=campaigns_root,
                )
                listed = astra_campaign_list(root=campaigns_root)
            self.assertEqual(guard.calls, 0)
            cid = started["campaign_id"]
            self.assertTrue(any(e.get("campaign_id") == cid for e in listed))


if __name__ == "__main__":
    unittest.main()
