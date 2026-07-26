#!/usr/bin/env python3
"""Measure vNext.1 deterministic repair on frozen adversarial validators.

This is a fast evidence gate, not a substitute for the long research-trajectory
canary. It measures only the defect classes ASTRA claims to repair without a
model call and calibrates them against sound validators that must not be blocked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.validator_preflight import (
    audit_validation_code,
    repair_validation_code,
    smoke_validation_code,
)


DEFAULT_CASES = (
    ROOT
    / "benchmarks"
    / "quality"
    / "validator_audit"
    / "adversarial_validators.json"
)
DEFAULT_HISTORICAL_RUN = (
    ROOT
    / "workspace"
    / "research_trajectory_runs"
    / "research_trajectory_20260726_035736"
    / "checkpoint.json"
)
DEFAULT_OUTPUT = ROOT / "workspace" / "quick_evidence"
SUPPORTED_LOCAL_LABELS = {
    "unknown_as_pass",
    "swallowed_exception",
    "unsimplified_symbolic_zero",
}


def _target_patterns(case: dict[str, Any]) -> set[str]:
    """Select exact source patterns, not broad semantic defect families."""
    code = str(case.get("code") or "")
    expected = {
        str(label)
        for label in case.get("expected_defects") or []
    }
    target: set[str] = set()
    if (
        "unknown_as_pass" in expected
        and re.search(r"\.is_zero\s+(?:is\s+not|!=)\s+True\b", code)
    ):
        target.add("unknown_as_pass")
    if (
        "swallowed_exception" in expected
        and re.search(r"^\s*except\s+(?:Exception|BaseException)", code, re.M)
    ):
        target.add("swallowed_exception")
    if (
        "unsimplified_symbolic_zero" in expected
        and re.search(
            r"def\s+(?:all_zero|tensor_all_zero|tensor_is_zero)\b[\s\S]*?"
            r"\[[^\n]+\]\s*==\s*0",
            code,
        )
    ):
        target.add("unsimplified_symbolic_zero")
    return target


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _historical_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cycles = [
        cycle
        for record in payload.get("records") or payload.get("cells") or []
        for cycle in record.get("cycles") or []
    ]
    totals = [
        float(((cycle.get("result") or {}).get("timings") or {}).get("total") or 0)
        for cycle in cycles
    ]
    statuses = [
        str(
            (cycle.get("result") or {}).get("status")
            or cycle.get("status")
            or "UNKNOWN"
        )
        for cycle in cycles
    ]
    credible = sum(
        status in {"VALIDATED", "REFUTED"}
        for status in statuses
    )
    return {
        "available": True,
        "path": str(path),
        "run_id": payload.get("run_id") or path.parent.name,
        "cycles": len(cycles),
        "credible_cycles": credible,
        "conversion_rate": round(credible / len(cycles), 6) if cycles else None,
        "mean_cycle_seconds": (
            round(statistics.mean(totals), 3) if totals else None
        ),
        "total_cycle_seconds": round(sum(totals), 3),
        "statuses": statuses,
    }


def build_report(
    cases: list[dict[str, Any]],
    *,
    repeats: int = 200,
    historical_run: Path = DEFAULT_HISTORICAL_RUN,
) -> dict[str, Any]:
    records = []
    timings_ms: list[float] = []
    for case in cases:
        code = str(case.get("code") or "")
        before = audit_validation_code(code)
        started = time.perf_counter()
        repair = repair_validation_code(code, before)
        for _ in range(max(0, repeats - 1)):
            repair_validation_code(code, before)
        elapsed_ms = (time.perf_counter() - started) * 1000 / max(1, repeats)
        timings_ms.append(elapsed_ms)
        after = audit_validation_code(repair["code"])
        smoke = smoke_validation_code(repair["code"])
        target = _target_patterns(case)
        detected = {
            str(item.get("label") or "")
            for item in before.get("findings") or []
        }
        records.append(
            {
                "id": case.get("id"),
                "expected_review": case.get("expected"),
                "target_labels": sorted(target),
                "detected_labels": sorted(detected),
                "target_detected": target <= detected if target else None,
                "repair_changed": bool(repair.get("changed")),
                "repair_labels": sorted(
                    {
                        str(item.get("label") or "")
                        for item in repair.get("repairs") or []
                    }
                ),
                "postflight_status": after.get("status"),
                "compile_status": smoke.get("status"),
                "mean_repair_ms": round(elapsed_ms, 6),
            }
        )

    targeted = [item for item in records if item["target_labels"]]
    sound = [
        item
        for item in records
        if str(item.get("expected_review") or "").upper() == "APPROVED"
    ]
    summary = {
        "cases": len(records),
        "targeted_cases": len(targeted),
        "target_detection_rate": (
            round(
                sum(bool(item["target_detected"]) for item in targeted)
                / len(targeted),
                6,
            )
            if targeted
            else None
        ),
        "target_local_repair_rate": (
            round(
                sum(
                    item["repair_changed"]
                    and item["postflight_status"] == "APPROVED"
                    for item in targeted
                )
                / len(targeted),
                6,
            )
            if targeted
            else None
        ),
        "sound_calibration_cases": len(sound),
        "sound_false_block_rate": (
            round(
                sum(item["postflight_status"] != "APPROVED" for item in sound)
                / len(sound),
                6,
            )
            if sound
            else None
        ),
        "median_repair_ms": round(statistics.median(timings_ms), 6),
        "p95_repair_ms": round(_percentile(timings_ms, 0.95) or 0.0, 6),
    }
    return {
        "schema_version": "1.0",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": (
            "Deterministic vNext.1 defect detection and local repair only; "
            "not a scientific-quality or end-to-end trajectory benchmark."
        ),
        "supported_local_labels": sorted(SUPPORTED_LOCAL_LABELS),
        "repeats_per_case": repeats,
        "summary": summary,
        "historical_vnext0": _historical_summary(historical_run),
        "records": records,
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    historical = report["historical_vnext0"]
    lines = [
        "# ASTRA Validator Repair vNext.1 - Quick Evidence",
        "",
        f"- Created: {report['created_at']}",
        f"- Targeted defect cases: {summary['targeted_cases']}",
        f"- Detection rate: {summary['target_detection_rate']}",
        f"- Safe local repair rate: {summary['target_local_repair_rate']}",
        f"- Sound calibration false-block rate: {summary['sound_false_block_rate']}",
        f"- Median deterministic repair: {summary['median_repair_ms']} ms",
        f"- P95 deterministic repair: {summary['p95_repair_ms']} ms",
        "",
        "This gate measures only the three source patterns vNext.1 claims to repair",
        "without a model call. It does not measure scientific correctness.",
        "",
    ]
    if historical.get("available"):
        lines.extend(
            [
                "## Historical vNext.0 context",
                "",
                f"- Run: `{historical['run_id']}`",
                f"- Cycles: {historical['cycles']}",
                f"- Credible conversion: {historical['conversion_rate']}",
                f"- Mean cycle seconds: {historical['mean_cycle_seconds']}",
                "",
            ]
        )
    lines.extend(
        [
            "| Case | Target | Detected | Repaired | Postflight | Mean ms |",
            "|---|---|---|---:|---|---:|",
        ]
    )
    for item in report["records"]:
        if not item["target_labels"] and item["expected_review"] != "APPROVED":
            continue
        lines.append(
            f"| `{item['id']}` | {', '.join(item['target_labels']) or 'sound'} | "
            f"{', '.join(item['detected_labels']) or '-'} | "
            f"{item['repair_changed']} | {item['postflight_status']} | "
            f"{item['mean_repair_ms']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fast deterministic benchmark for Validator Repair vNext.1"
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--historical-run", type=Path, default=DEFAULT_HISTORICAL_RUN)
    parser.add_argument("--repeats", type=int, default=200)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    report = build_report(
        cases,
        repeats=max(1, args.repeats),
        historical_run=args.historical_run,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"validator_repair_quick_{stamp}.json"
    md_path = args.output_dir / f"validator_repair_quick_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "historical_vnext0": report["historical_vnext0"],
                "json_report": str(json_path),
                "markdown_report": str(md_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
