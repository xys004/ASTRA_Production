"""The one-off pruner must only ever select proven test leftovers.

Synthetic workspace with one file per class boundary.  The rules are in the
script's docstring; each case here pins one of them, and --apply is checked to
delete exactly the TEST class and nothing else.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import prune_test_cycle_artifacts as pruner  # noqa: E402


def _checkpoint(directory: Path, name: str, *, wall, elapsed, timings, intuition,
                stage="tool_error", status=None):
    payload = {
        "schema_version": "1.0",
        "pid": int(name.rsplit("_", 1)[1].split(".")[0]),   # <key>_<pid>.json
        "intuition": intuition,
        "shared_goal": intuition,
        "stage": stage,
        "created_ts": 1_788_900_000,
        "timings": timings,
        "budget": {
            "mode": "persistent" if wall is None else "synchronous",
            "total_seconds": wall,
            "elapsed_seconds": elapsed,
            "remaining_seconds": None if wall is None else wall - elapsed,
            "return_buffer_seconds": 60,
        },
    }
    if status:
        payload["result"] = {"status": status}
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _heartbeat(directory: Path, pid: int, *, stage, timings=None, checkpoint=None, **extra):
    payload = {"pid": pid, "stage": stage, "ts": 1_788_900_000, **extra}
    if timings is not None:
        payload["timings"] = timings
    if checkpoint is not None:
        payload["checkpoint"] = str(checkpoint)
    path = directory / f"cycle_{pid}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _build(workspace: Path) -> dict:
    ck = workspace / "cycle_checkpoints"
    pr = workspace / "progress"
    ck.mkdir(parents=True)
    pr.mkdir(parents=True)
    files = {}
    # Real production cycles: minutes long, real goals.
    files["real_done"] = _checkpoint(
        ck, "aaaa_100.json", wall=3600.0, elapsed=1398.5,
        timings={"conjecture": 300.0, "translate": 500.0, "execute": 598.5},
        intuition="Audit these precise claims about the reservoir ring.",
        stage="done", status="VALIDATED")
    files["real_persistent"] = _checkpoint(
        ck, "bbbb_101.json", wall=None, elapsed=1630.7,
        timings={"conjecture": 800.0, "translate": 830.7},
        intuition="Evidencia nueva y acotada en OpenFOAM v2412.")
    # The August benchmark cycles start with "Test" but are real.
    files["benchmark"] = _checkpoint(
        ck, "cccc_102.json", wall=1500.0, elapsed=191.2,
        timings={"conjecture": 60.0, "translate": 131.2},
        intuition="Test the dimensional character of the Reynolds number.",
        stage="done", status="VALIDATED")
    # Suite leftovers.
    files["test_120"] = _checkpoint(
        ck, "dddd_200.json", wall=120.0, elapsed=0.02, timings={"conjecture": 0.0, "translate": 0.02},
        intuition="Test author quota failure during regeneration.")
    files["test_1500_literal"] = _checkpoint(
        ck, "eeee_201.json", wall=1500.0, elapsed=0.03, timings={"conjecture": 0.0, "execute": 0.03},
        intuition="Check one bounded identity.", stage="done", status="VALIDATED")
    files["test_persistent_literal"] = _checkpoint(
        ck, "ffff_202.json", wall=None, elapsed=0.01, timings={"conjecture": 0.0},
        intuition="Test the persistent deadline.", stage="partial")
    # Sub-second but no corroboration: a real cycle whose CLI died at once.
    files["ambiguous_fast"] = _checkpoint(
        ck, "0000_300.json", wall=1500.0, elapsed=0.05, timings={"conjecture": 0.05},
        intuition="Real intuition whose CLI binary was missing.")
    # A short wall alone is not enough: astra_cycle(timeout=90) killed at 'start'.
    files["ambiguous_short_wall"] = _checkpoint(
        ck, "2222_302.json", wall=90.0, elapsed=0.0, timings={},
        intuition="Real ninety-second probe killed at start.", stage="start")
    # A live cycle's fresh 'start' checkpoint reads exactly like a test one.
    files["live_start"] = _checkpoint(
        ck, "3333_777.json", wall=120.0, elapsed=0.0, timings={},
        intuition="Test the deadline.", stage="start")
    # Unfinished .tmp is never classified.
    files["tmp"] = ck / "1111_301.json.tmp"
    files["tmp"].write_text(json.dumps({"stage": "tool_error", "intuition": "Test the deadline.",
                                        "budget": {"elapsed_seconds": 0.0, "total_seconds": 120.0}}),
                            encoding="utf-8")
    # Heartbeats.
    files["hb_of_test"] = _heartbeat(pr, 200, stage="failed", phase="translator",
                                     timings={"total": 0.02}, checkpoint=files["test_120"])
    files["hb_orphan_fast"] = _heartbeat(pr, 15960, stage="done", status="VALIDATED",
                                         timings={"total": 0.48}, checkpoint=ck / "gone_15960.json")
    files["hb_orphan_slow"] = _heartbeat(pr, 15961, stage="done", status="VALIDATED",
                                         timings={"total": 1203.4}, checkpoint=ck / "gone_15961.json")
    files["hb_of_real"] = _heartbeat(pr, 100, stage="done", status="VALIDATED",
                                     timings={"total": 1398.5}, checkpoint=files["real_done"])
    files["hb_queued"] = _heartbeat(pr, 24184, stage="queued", waited_s=7197.9, active_cycles=[])
    files["hb_killed"] = _heartbeat(pr, 24185, stage="translation_complete", timings={"total": 400.0},
                                    checkpoint=ck / "gone_24185.json")
    files["hb_alive"] = _heartbeat(pr, 777, stage="done", status="VALIDATED",
                                   timings={"total": 0.01}, checkpoint=ck / "gone_777.json")
    return files


def _classes(records) -> dict:
    return {os.path.basename(r["path"]): r["cls"] for r in records}


def test_classification_pins_every_rule(tmp_path):
    files = _build(tmp_path)
    alive = lambda pid: int(pid or 0) == 777        # noqa: E731
    classes = _classes(pruner.classify_workspace(str(tmp_path), alive=alive))
    expected = {
        files["real_done"].name: pruner.KEEP,
        files["real_persistent"].name: pruner.KEEP,
        files["benchmark"].name: pruner.KEEP,
        files["test_120"].name: pruner.TEST,
        files["test_1500_literal"].name: pruner.TEST,
        files["test_persistent_literal"].name: pruner.TEST,
        files["ambiguous_fast"].name: pruner.AMBIGUOUS,
        files["ambiguous_short_wall"].name: pruner.AMBIGUOUS,
        files["live_start"].name: pruner.KEEP,
        files["tmp"].name: pruner.KEEP,
        files["hb_of_test"].name: pruner.TEST,
        files["hb_orphan_fast"].name: pruner.TEST,
        files["hb_orphan_slow"].name: pruner.AMBIGUOUS,
        files["hb_of_real"].name: pruner.KEEP,
        files["hb_queued"].name: pruner.AMBIGUOUS,
        files["hb_killed"].name: pruner.AMBIGUOUS,
        files["hb_alive"].name: pruner.KEEP,
    }
    assert classes == expected


def test_dry_run_deletes_nothing_and_apply_deletes_only_test(tmp_path, capsys):
    files = _build(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert pruner.main(["--workspace", str(tmp_path)]) == 0
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == before
    out = capsys.readouterr().out
    assert "Dry run: nothing deleted" in out
    assert "would delete" in out

    # A live pid must survive --apply; fake liveness for pid 777 only.
    original = pruner._pid_alive
    pruner._pid_alive = lambda pid: int(pid or 0) == 777
    try:
        assert pruner.main(["--workspace", str(tmp_path), "--apply"]) == 0
    finally:
        pruner._pid_alive = original
    remaining = {p for p in tmp_path.rglob("*") if p.is_file()}
    deleted = before - remaining
    assert deleted == {
        files["test_120"], files["test_1500_literal"], files["test_persistent_literal"],
        files["hb_of_test"], files["hb_orphan_fast"],
    }


def test_known_intuitions_cover_every_cycle_the_suite_runs():
    """A new test cycle with a new intuition must be registered here too."""
    import re

    suite = ROOT / "tests"
    seen = set()
    for path in suite.glob("test_*.py"):
        if path.name == Path(__file__).name:       # this file quotes literals itself
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "_do_cycle(" not in text:
            continue
        # Only intuitions passed to a real _do_cycle call, not to mocks.
        for match in re.finditer(r'"intuition":\s*"([^"]+)"', text):
            seen.add(match.group(1))
    # Mocked cycles (campaign executor, GUI adapter) never reach astra_tool.
    seen.discard("Audit the invariant.")
    missing = seen - pruner.KNOWN_TEST_INTUITIONS
    assert not missing, f"register these in KNOWN_TEST_INTUITIONS: {sorted(missing)}"
