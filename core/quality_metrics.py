"""Metrics for ASTRA Quality Benchmark v1."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable


OPERATIONAL_STATUSES = {
    "API_ERROR", "CODE_ERROR", "ERROR", "TIMEOUT", "NO_VERDICT", "TOOL_ERROR",
}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def wilson_interval(successes: int, total: int, z: float = 1.959964) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / den
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def percentile(values: Iterable[float], q: float) -> float | None:
    values = sorted(float(value) for value in values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return round(values[lower], 3)
    value = values[lower] * (upper - pos) + values[upper] * (pos - lower)
    return round(value, 3)


def _scientific_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    truth = [r for r in records if r["track"] == "cycle"]
    decidable = [r for r in truth if r["expected"] in {"VALIDATED", "REFUTED"}]
    correct = sum(bool(r.get("correct")) for r in decidable)
    validated = [r for r in decidable if r["expected"] == "VALIDATED"]
    refuted = [r for r in decidable if r["expected"] == "REFUTED"]
    tpr = _rate(sum(bool(r.get("correct")) for r in validated), len(validated))
    tnr = _rate(sum(bool(r.get("correct")) for r in refuted), len(refuted))
    balanced = None if tpr is None or tnr is None else round((tpr + tnr) / 2, 4)
    false_accepts = sum(
        r["expected"] == "REFUTED" and r.get("observed") == "VALIDATED"
        for r in decidable
    )
    false_rejects = sum(
        r["expected"] == "VALIDATED" and r.get("observed") == "REFUTED"
        for r in decidable
    )
    by_case: dict[str, list[str]] = defaultdict(list)
    for record in decidable:
        by_case[record["id"]].append(record.get("observed", ""))
    repeated = [values for values in by_case.values() if len(values) > 1]
    return {
        "cases": len(decidable),
        "strict_accuracy": _rate(correct, len(decidable)),
        "accuracy_95ci": wilson_interval(correct, len(decidable)),
        "balanced_accuracy": balanced,
        "false_acceptance_rate": _rate(false_accepts, len(refuted)),
        "false_rejection_rate": _rate(false_rejects, len(validated)),
        "repeat_or_oracle_agreement": _rate(
            sum(len(set(values)) == 1 for values in repeated),
            len(repeated),
        ),
        "operational_failure_rate": _rate(
            sum(r.get("observed") in OPERATIONAL_STATUSES for r in truth),
            len(truth),
        ),
    }


def _audit_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    audit = [r for r in records if r["track"] == "validator_audit"]
    flawed = [r for r in audit if r.get("expected_defects")]
    sound = [r for r in audit if not r.get("expected_defects")]
    caught = sum(r.get("observed") in {"REVISE", "REJECT"} for r in flawed)
    false_alarms = sum(r.get("observed") != "APPROVED" for r in sound)
    expected_labels = sum(len(r.get("expected_defects", [])) for r in flawed)
    found_labels = sum(
        len(set(r.get("expected_defects", [])) & set(r.get("observed_defects", [])))
        for r in flawed
    )
    critical = [r for r in flawed if r.get("severity") == "critical"]
    critical_caught = sum(r.get("observed") in {"REVISE", "REJECT"} for r in critical)
    return {
        "cases": len(audit),
        "defect_detection_recall": _rate(caught, len(flawed)),
        "critical_defect_recall": _rate(critical_caught, len(critical)),
        "defect_label_recall": _rate(found_labels, expected_labels),
        "sound_validator_false_alarm_rate": _rate(false_alarms, len(sound)),
    }


def _execution_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    execution = [r for r in records if r["track"] == "execution"]
    correct = sum(bool(r.get("correct")) for r in execution)
    by_case: dict[str, list[str]] = defaultdict(list)
    for record in execution:
        by_case[record["id"]].append(record.get("observed", ""))
    repeated = [values for values in by_case.values() if len(values) > 1]
    agreement = _rate(sum(len(set(values)) == 1 for values in repeated), len(repeated))
    return {
        "runs": len(execution),
        "verdict_accuracy": _rate(correct, len(execution)),
        "cross_run_agreement": agreement,
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [r["duration_s"] for r in records if r.get("duration_s") is not None]
    evidence_counts: dict[str, int] = defaultdict(int)
    for record in records:
        if record.get("evidence_grade"):
            evidence_counts[str(record["evidence_grade"])] += 1
    by_config: dict[str, Any] = {}
    for config in sorted({str(r.get("configuration", "full")) for r in records}):
        subset = [r for r in records if str(r.get("configuration", "full")) == config]
        by_config[config] = {
            "scientific": _scientific_metrics(subset),
            "audit": _audit_metrics(subset),
            "execution": _execution_metrics(subset),
        }
    return {
        "runs": len(records),
        "scientific": _scientific_metrics(records),
        "audit": _audit_metrics(records),
        "execution": _execution_metrics(records),
        "latency_s": {
            "p50": percentile(durations, 0.50),
            "p95": percentile(durations, 0.95),
            "median": round(median(durations), 3) if durations else None,
        },
        "evidence_grades": dict(sorted(evidence_counts.items())),
        "by_configuration": by_config,
    }
