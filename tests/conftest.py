"""Test-session isolation for machine-wide resources.

The deliberative-cycle slot became machine-wide on 2026-08-13 so the 2.0 line
and production cannot deliberate against the same subscription at once. That
is right for real runs and wrong for tests: a handful of cycle tests patch the
model client and never touch a model, yet they still acquire the slot, so they
failed with BUSY the moment production started a genuine cycle on this
machine. A suite whose result depends on unrelated activity is not measuring
what it claims to.

Pointing ASTRA_LOCK_ROOT at a per-session temporary directory keeps the tests
hermetic while leaving the production semantics intact. The lock behaviour
itself is still covered, by test_cycle_lock_root.py, which sets its own roots
explicitly.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_cycle_lock_root():
    """Give the whole test session its own cycle-lock directory."""
    previous = os.environ.get("ASTRA_LOCK_ROOT")
    with tempfile.TemporaryDirectory(prefix="astra_test_locks_") as tmp:
        os.environ["ASTRA_LOCK_ROOT"] = tmp
        try:
            yield tmp
        finally:
            if previous is None:
                os.environ.pop("ASTRA_LOCK_ROOT", None)
            else:
                os.environ["ASTRA_LOCK_ROOT"] = previous


@pytest.fixture(scope="session", autouse=True)
def isolated_workspace_root():
    """Send every cycle's heartbeat, checkpoint, cache and job files to a temp dir.

    astra_tool.py writes them under <checkout>/workspace by default, the pool
    core/cycle_telemetry.py, astra_probe and astra_telemetry read as production
    history. The suite's fake cycles (0.02 s, "Test author quota failure ...")
    were landing there and dragging every mean duration and outcome count.
    ASTRA_WORKSPACE_ROOT is the writer-side override astra_tool._workspace_root
    honours; tests/test_workspace_isolation.py proves the redirection and the
    byte-for-byte default. The directory is removed at session end; on Windows
    a straggling handle must not turn that into a session error, hence the
    tolerant rmtree instead of TemporaryDirectory's strict cleanup.
    """
    previous = os.environ.get("ASTRA_WORKSPACE_ROOT")
    previous_window = os.environ.get("ASTRA_PROGRESS_WINDOW")
    tmp = tempfile.mkdtemp(prefix="astra_test_workspace_")
    os.environ["ASTRA_WORKSPACE_ROOT"] = tmp
    # core/progress_window.py opens one console per cycle on Windows; a test
    # session must never pop windows (belt: it also detects pytest itself).
    os.environ["ASTRA_PROGRESS_WINDOW"] = "0"
    try:
        yield tmp
    finally:
        if previous is None:
            os.environ.pop("ASTRA_WORKSPACE_ROOT", None)
        else:
            os.environ["ASTRA_WORKSPACE_ROOT"] = previous
        if previous_window is None:
            os.environ.pop("ASTRA_PROGRESS_WINDOW", None)
        else:
            os.environ["ASTRA_PROGRESS_WINDOW"] = previous_window
        shutil.rmtree(tmp, ignore_errors=True)
