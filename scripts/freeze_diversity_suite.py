"""Create or verify ASTRA's preregistered 40-case diversity suite."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.external_benchmarks import (  # noqa: E402
    ExternalCase,
    audit_external_sources,
    load_ainsteinbench,
    load_frontierscience,
    load_minif2f,
    load_scicode,
)


SEED = "ASTRA-diversity-v1-20260724"
CALIBRATION = (
    ROOT / "benchmarks" / "external" / "comparison_calibration_v1.json"
)
OUTPUT = ROOT / "benchmarks" / "external" / "diversity_frozen_v1.json"
CONFIGURATIONS = ["full", "homogeneous-proposers"]

PILOTS = {
    "scicode": ("scicode", "official numerical tests"),
    "minif2f": ("minif2f", "Lean 3 kernel compilation"),
    "frontierscience": ("frontier", "official-answer equivalence"),
    "ainsteinbench": ("ainstein", "official hidden tests and resolve points"),
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rank(namespace: str, value: str) -> str:
    return _digest(f"{SEED}|{namespace}|{value}")


def _mini_stratum(case: ExternalCase) -> str:
    name = str(case.metadata["theorem_name"])
    if name.startswith("mathd_"):
        return "_".join(name.split("_")[:2])
    return name.split("_")[0]


def _case_entry(
    case: ExternalCase,
    *,
    stratum: str,
    namespace: str,
) -> dict[str, Any]:
    pilot, metric = PILOTS[case.benchmark]
    return {
        "benchmark": case.benchmark,
        "id": case.id,
        "pilot": pilot,
        "native_metric": metric,
        "stratum": stratum,
        "selection_digest": _rank(namespace, case.id)[:16],
        "prompt_sha256": _digest(case.prompt),
        "reference_sha256": _digest(case.reference),
    }


def _choose_scicode(calibration_ids: set[str]) -> list[dict[str, Any]]:
    cases = [
        case
        for case in load_scicode()
        if case.split == "development"
    ]
    calibration_problem_ids = {
        str(case.metadata["problem_id"])
        for case in cases
        if case.id in calibration_ids
    }
    grouped: dict[str, list[ExternalCase]] = defaultdict(list)
    for case in cases:
        problem_id = str(case.metadata["problem_id"])
        if problem_id not in calibration_problem_ids:
            grouped[problem_id].append(case)
    representatives = [
        sorted(
            values,
            key=lambda case: (
                tuple(
                    int(part)
                    for part in str(case.metadata["step_number"]).split(".")
                ),
                case.id,
            ),
        )[0]
        for values in grouped.values()
    ]
    chosen = sorted(
        representatives,
        key=lambda case: _rank("scicode-problem", case.id),
    )[:12]
    if len(chosen) != 12 or len({case.domain for case in chosen}) != 12:
        raise RuntimeError("SciCode selection must cover 12 distinct problems")
    return [
        _case_entry(
            case,
            stratum=f"problem:{case.metadata['problem_id']}:{case.domain}",
            namespace="scicode-problem",
        )
        for case in chosen
    ]


def _choose_minif2f(calibration_ids: set[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ExternalCase]] = defaultdict(list)
    for case in load_minif2f():
        if case.split == "validation" and case.id not in calibration_ids:
            grouped[_mini_stratum(case)].append(case)
    expected_strata = {
        "aime",
        "aimeI",
        "aimeII",
        "algebra",
        "amc12",
        "amc12a",
        "amc12b",
        "imo",
        "induction",
        "mathd_algebra",
        "mathd_numbertheory",
        "numbertheory",
    }
    if set(grouped) != expected_strata:
        raise RuntimeError(
            f"Unexpected miniF2F strata: {sorted(set(grouped) ^ expected_strata)}"
        )
    chosen = [
        min(
            grouped[stratum],
            key=lambda case: _rank(f"minif2f:{stratum}", case.id),
        )
        for stratum in sorted(expected_strata)
    ]
    return [
        _case_entry(
            case,
            stratum=_mini_stratum(case),
            namespace=f"minif2f:{_mini_stratum(case)}",
        )
        for case in chosen
    ]


def _choose_frontier(calibration_ids: set[str]) -> list[dict[str, Any]]:
    quotas = {"physics": 6, "chemistry": 5, "biology": 1}
    grouped: dict[str, list[ExternalCase]] = defaultdict(list)
    for case in load_frontierscience():
        if case.split == "olympiad" and case.id not in calibration_ids:
            grouped[case.domain.lower()].append(case)
    chosen: list[ExternalCase] = []
    for subject, count in quotas.items():
        chosen.extend(
            sorted(
                grouped[subject],
                key=lambda case: _rank(f"frontier:{subject}", case.id),
            )[:count]
        )
    if len(chosen) != 12:
        raise RuntimeError("FrontierScience selection must contain 12 cases")
    return [
        _case_entry(
            case,
            stratum=case.domain.lower(),
            namespace=f"frontier:{case.domain.lower()}",
        )
        for case in chosen
    ]


def _choose_ainstein(calibration_ids: set[str]) -> list[dict[str, Any]]:
    cases = load_ainsteinbench()
    calibration_repos = {
        case.domain for case in cases if case.id in calibration_ids
    }
    grouped: dict[str, list[ExternalCase]] = defaultdict(list)
    for case in cases:
        if case.domain not in calibration_repos:
            grouped[case.domain].append(case)
    repos = sorted(
        grouped,
        key=lambda repo: _rank("ainstein-repository", repo),
    )[:4]
    chosen = [
        min(
            grouped[repo],
            key=lambda case: _rank(f"ainstein:{repo}", case.id),
        )
        for repo in repos
    ]
    if len(chosen) != 4 or len({case.domain for case in chosen}) != 4:
        raise RuntimeError("AInsteinBench selection must cover four repositories")
    return [
        _case_entry(
            case,
            stratum=f"repository:{case.domain}",
            namespace=f"ainstein:{case.domain}",
        )
        for case in chosen
    ]


def _execution_schedule(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered_cases = sorted(
        cases,
        key=lambda case: _rank("schedule-case", case["id"]),
    )
    full_first = {
        case["id"]
        for case in sorted(
            cases,
            key=lambda case: _rank("schedule-order", case["id"]),
        )[: len(cases) // 2]
    }
    schedule: list[dict[str, Any]] = []
    for block, case in enumerate(ordered_cases, start=1):
        configurations = list(CONFIGURATIONS)
        if case["id"] not in full_first:
            configurations.reverse()
        for position, configuration in enumerate(configurations, start=1):
            schedule.append(
                {
                    "block": block,
                    "position_within_pair": position,
                    "case_id": case["id"],
                    "configuration": configuration,
                }
            )
    return schedule


def build_suite() -> dict[str, Any]:
    audit = audit_external_sources()
    if not audit["ok"]:
        raise RuntimeError("Pinned external sources failed their audit")
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    calibration_ids = {item["id"] for item in calibration["cases"]}

    cases = [
        *_choose_scicode(calibration_ids),
        *_choose_minif2f(calibration_ids),
        *_choose_frontier(calibration_ids),
        *_choose_ainstein(calibration_ids),
    ]
    if len(cases) != 40 or len({item["id"] for item in cases}) != 40:
        raise RuntimeError("Frozen suite must contain 40 unique cases")
    if calibration_ids & {item["id"] for item in cases}:
        raise RuntimeError("Frozen suite overlaps the calibration cases")

    schedule = _execution_schedule(cases)
    canary_case_ids = [
        min(
            (item for item in cases if item["benchmark"] == benchmark),
            key=lambda item: _rank(f"canary:{benchmark}", item["id"]),
        )["id"]
        for benchmark in (
            "scicode",
            "minif2f",
            "frontierscience",
            "ainsteinbench",
        )
    ]
    case_ids_sha256 = _digest(
        "\n".join(sorted(item["id"] for item in cases))
    )
    schedule_sha256 = _digest(
        json.dumps(schedule, sort_keys=True, separators=(",", ":"))
    )
    suite: dict[str, Any] = {
        "schema_version": "1.0",
        "suite_id": "external_diversity_frozen_v1",
        "description": (
            "Preregistered 40-case paired test of heterogeneous versus "
            "homogeneous proposal teams under matched downstream roles."
        ),
        "frozen": True,
        "frozen_on": "2026-07-24",
        "comparison_mode": "paired_equal_phase_topology",
        "configurations": CONFIGURATIONS,
        "hypotheses": {
            "primary": (
                "Replacing the second Codex proposer with AGY/Gemini increases "
                "native benchmark pass probability under equal phase topology."
            ),
            "mechanism": (
                "The heterogeneous pair exhibits greater initial perspective "
                "diversity, and synthesis/review converts some disagreements "
                "into paired wins rather than merely adding verbosity."
            ),
            "null": (
                "The heterogeneous and homogeneous proposal pairs have equal "
                "native pass probability."
            ),
        },
        "analysis_plan": {
            "primary_endpoint": "paired native PASS",
            "primary_test": "exact McNemar, full greater than control",
            "effect_interval": (
                "deterministic 5000-resample paired bootstrap 95% interval"
            ),
            "mechanism_metrics": [
                "unigram Jaccard distance",
                "bigram Jaccard distance",
                "synthesis proposal retention",
                "review intervention",
                "repair lift",
            ],
            "operational_errors": (
                "reported separately and excluded from scientific pass rates"
            ),
            "decision_rule": (
                "supported only when paired pass-rate delta is positive and "
                "one-sided exact McNemar p < 0.05; otherwise report directional, "
                "null, or adverse evidence without changing cases"
            ),
        },
        "selection": {
            "seed": SEED,
            "source_fingerprint": audit["fingerprint"],
            "source_commits": {
                item["name"]: item["expected_commit"]
                for item in audit["source_checks"]
            },
            "excluded_calibration_case_ids": sorted(calibration_ids),
            "stratification": {
                "scicode": "12 distinct development problems; first subproblem",
                "minif2f": "one validation theorem from each of 12 name strata",
                "frontierscience": "6 physics, 5 chemistry, 1 biology olympiad",
                "ainsteinbench": (
                    "one task from each of four repositories not used in calibration"
                ),
            },
            "case_ids_sha256": case_ids_sha256,
            "schedule_sha256": schedule_sha256,
        },
        "canary_case_ids": canary_case_ids,
        "cases": cases,
        "execution_schedule": schedule,
    }
    suite["suite_sha256"] = _digest(
        json.dumps(suite, sort_keys=True, separators=(",", ":"))
    )
    return suite


def main() -> int:
    suite = build_suite()
    rendered = json.dumps(suite, indent=2, ensure_ascii=False) + "\n"
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if existing != suite:
            raise RuntimeError(
                f"Frozen suite mismatch; refusing to overwrite {OUTPUT}"
            )
        action = "verified"
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")
        action = "created"
    print(
        json.dumps(
            {
                "status": action,
                "path": str(OUTPUT),
                "suite_sha256": suite["suite_sha256"],
                "cases": len(suite["cases"]),
                "cells": len(suite["execution_schedule"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
