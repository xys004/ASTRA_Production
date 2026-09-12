"""Shared cleanup for tests that run the real deliberative cycle.

``astra_tool._do_cycle`` leaves two files per run: the checkpoint it reports in
``result["checkpoint"]`` and the heartbeat ``<workspace>/progress/cycle_<pid>.json``
(see ``astra_tool._progress_path``).  Both are read back as production history
by core/cycle_telemetry.py, astra_probe, astra_telemetry and
scripts/astra_progress.py.

Under pytest the session fixture in conftest.py already points
``ASTRA_WORKSPACE_ROOT`` at a temporary directory, so nothing reaches the
checkout's workspace/.  This helper removes both files regardless of the
runner, so a plain ``python -m unittest`` run does not seed the real workspace
with 0 s cycles and orphan heartbeats either.  Until 2026-09-09 the tests
unlinked only the checkpoint, which is exactly how the orphan heartbeats
pointing at missing checkpoints came to exist.
"""
from __future__ import annotations

from pathlib import Path

from astra_tool import _progress_path


def remove_cycle_artifacts(result: dict) -> list:
    """Delete the checkpoint named in ``result`` and this process's heartbeat.

    Returns the paths that were actually removed.  Missing files are fine: a
    cycle that returned BUSY has no checkpoint, and a test may call this twice.
    """
    removed = []
    for candidate in ((result or {}).get("checkpoint"), _progress_path()):
        if not candidate:
            continue
        path = Path(candidate)
        # _save_cycle_checkpoint writes <checkpoint>.tmp and os.replace()s it;
        # on Windows the replace can fail while a reader holds the target, so
        # the .tmp sibling is part of the same artefact.
        for target in (path, path.with_name(path.name + ".tmp")):
            try:
                target.unlink()
            except FileNotFoundError:
                continue
            removed.append(str(target))
    return removed
