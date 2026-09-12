"""Resolve a git repository's HEAD commit without a fragile subprocess.

Shelling out to ``git rev-parse HEAD`` on the MCP server's hot path can wedge
indefinitely (HANDOFF.md section 12): the subprocess inherits the server's
stdio transport handles and, on Windows, ``subprocess.run``'s ``timeout`` does
not reliably reap it -- a stuck ``git rev-parse HEAD`` was observed alive for
30+ minutes despite ``timeout=10``. Reading the ref files directly is pure
local I/O and cannot hang. This module centralizes that reader plus a hardened
last-resort subprocess so every provenance-stamping caller shares one correct
path (campaign_api, client_validation, external_benchmarks).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")


def git_dir(root: Path | str) -> Path | None:
    """Resolve ``root``'s git directory, handling the worktree/submodule
    ``gitdir: <path>`` file form. Pure filesystem, never a subprocess."""
    root = Path(root)
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            text = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            target = text[len("gitdir:") :].strip()
            path = Path(target) if os.path.isabs(target) else (root / target).resolve()
            return path if path.exists() else None
    return None


def read_head_commit(root: Path | str) -> str | None:
    """Return HEAD's commit id by reading git ref files directly, or ``None``.

    Never shells out to ``git`` (see the module docstring). Handles a symbolic
    or detached HEAD, a loose or packed ref, the ``.git``-file worktree form,
    and a linked worktree's ``commondir``.
    """
    gitdir = git_dir(root)
    if gitdir is None:
        return None
    # In a linked worktree, loose/packed refs live in the common dir.
    commondir = gitdir
    commondir_file = gitdir / "commondir"
    if commondir_file.is_file():
        try:
            rel = commondir_file.read_text(encoding="utf-8").strip()
            commondir = Path(rel) if os.path.isabs(rel) else (gitdir / rel).resolve()
        except OSError:
            commondir = gitdir
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        # Detached HEAD: the file holds the raw object id.
        return head.lower() if _HEX_RE.match(head) else None
    ref = head[len("ref:") :].strip()
    # 1) loose ref, checked in the worktree gitdir then the common dir
    for base in (gitdir, commondir):
        loose = base / ref
        try:
            if loose.is_file():
                sha = loose.read_text(encoding="utf-8").strip()
                if _HEX_RE.match(sha):
                    return sha.lower()
        except OSError:
            pass
    # 2) packed-refs
    try:
        for raw in (commondir / "packed-refs").read_text(
            encoding="utf-8"
        ).splitlines():
            line = raw.strip()
            if not line or line[0] in "#^":
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref and _HEX_RE.match(parts[0]):
                return parts[0].lower()
    except OSError:
        pass
    return None


def _hardened_git_head(root: Path | str) -> str | None:
    """Last-resort ``git rev-parse HEAD`` for an exotic layout the direct
    reader missed. Hardened so it cannot reproduce the hang: stdin is
    ``/dev/null`` (git can neither block on nor inherit the MCP stdio
    transport), interactive prompts and credential UIs are disabled, and the
    timeout is short."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "GCM_INTERACTIVE": "never",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = completed.stdout.strip()
    return sha.lower() if _HEX_RE.match(sha) else None


def resolve_head_commit(
    root: Path | str,
    *,
    explicit: str | None = None,
    env_var: str | None = None,
    allow_subprocess: bool = True,
) -> str | None:
    """HEAD commit via, in order: an explicit value, an environment override,
    a direct ref-file read, then (unless disabled) a hardened subprocess.

    Returns ``None`` when every source fails; callers choose their own
    sentinel (``""``, ``"unknown"``) or raise.
    """
    if explicit:
        return explicit
    if env_var:
        env = (os.environ.get(env_var) or "").strip()
        if env:
            return env
    commit = read_head_commit(root)
    if commit:
        return commit
    if allow_subprocess:
        return _hardened_git_head(root)
    return None
