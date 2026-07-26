"""Auditable process metrics for long-horizon ASTRA research programs.

Automatic metrics in this module describe observable events only.  They do not
pretend to infer scientific novelty, usefulness, or semantic depth from lexical
similarity.  Those construct-level dimensions are scored by blinded experts
using the frozen case anchors.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Iterable

from core.diversity_metrics import compute_diversity_metrics


OPERATIONAL_STATUSES = {
    "API_ERROR",
    "CODE_ERROR",
    "ERROR",
    "INCOMPLETE",
    "NO_VERDICT",
    "STOPPED",
    "TIMEOUT",
    "TOOL_ERROR",
    "WEAK_PASS",
}
SCIENTIFIC_STATUSES = {"VALIDATED", "REFUTED"}
_ENGINE_RE = re.compile(r"(?im)^\s*#\s*ASTRA_ENGINE:\s*([A-Za-z0-9_.-]+)")
_SPACE_RE = re.compile(r"\s+")


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 4) if denominator else None


def _mean(values: Iterable[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return round(mean(present), 4) if present else None


def _status(result: dict[str, Any]) -> str:
    value = str(result.get("status") or (result.get("analysis") or {}).get("status") or "")
    value = value.upper()
    if value.startswith("VALIDATED"):
        return "VALIDATED"
    if value.startswith("REFUTED"):
        return "REFUTED"
    if not value and result.get("error"):
        return "TOOL_ERROR"
    return value or "UNKNOWN"


def _normal_form(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").strip().lower())


def _text_hash(text: str) -> str:
    return hashlib.sha256(_normal_form(text).encode("utf-8")).hexdigest()[:16]


def _engine(result: dict[str, Any]) -> str:
    execution = result.get("execution") or {}
    if execution.get("engine"):
        return str(execution["engine"]).lower()
    match = _ENGINE_RE.search(str(result.get("code") or ""))
    return match.group(1).lower() if match else "python"


def cycle_has_credible_evidence(cycle: dict[str, Any]) -> bool:
    result = cycle.get("result") or cycle
    execution = result.get("execution") or {}
    guard = execution.get("guard") or {}
    return bool(
        _status(result) in SCIENTIFIC_STATUSES
        and execution
        and execution.get("exit_code") == 0
        and str(execution.get("verdict") or "").upper() in {"PASS", "FAIL"}
        and not guard.get("verdict_suspect", False)
        and not result.get("error")
    )


def cycle_has_independent_evidence(cycle: dict[str, Any]) -> bool:
    """Conservative machine-observable proxy for independent validation legs."""
    if not cycle_has_credible_evidence(cycle):
        return False
    result = cycle.get("result") or cycle
    execution = result.get("execution") or {}
    guard = execution.get("guard") or {}
    checks = int(guard.get("checks_total") or 0)
    engine = _engine(result)
    return bool(
        checks >= 2
        or engine
        in {
            "lean",
            "lean4",
            "sage",
            "maxima",
            "cadabra",
            "wolfram",
            "mathematica",
        }
    )


def build_research_graph(record: dict[str, Any]) -> dict[str, Any]:
    """Build an append-only hypothesis–evidence graph from a trajectory."""
    objective = str(record.get("objective") or "")
    nodes: list[dict[str, Any]] = [
        {
            "id": "objective",
            "type": "objective",
            "label": objective,
            "content_sha256": _text_hash(objective),
        }
    ]
    edges: list[dict[str, str]] = []
    branch_by_hash: dict[str, str] = {}
    previous_assessment = "objective"

    for offset, cycle in enumerate(record.get("cycles") or [], start=1):
        index = int(cycle.get("cycle") or offset)
        prefix = f"cycle_{index:03d}"
        result = cycle.get("result") or {}
        direction = str(cycle.get("direction") or "")
        conjecture = str(result.get("conjecture") or "")
        execution = result.get("execution") or {}
        analysis = result.get("analysis") or {}
        navigation = result.get("navigation") or {}

        direction_id = f"{prefix}_direction"
        hypothesis_id = f"{prefix}_hypothesis"
        evidence_id = f"{prefix}_evidence"
        assessment_id = f"{prefix}_assessment"
        nodes.extend(
            [
                {
                    "id": direction_id,
                    "type": "direction",
                    "cycle": index,
                    "label": direction,
                    "content_sha256": _text_hash(direction),
                },
                {
                    "id": hypothesis_id,
                    "type": "hypothesis",
                    "cycle": index,
                    "label": conjecture,
                    "content_sha256": _text_hash(conjecture),
                    "providers": list(
                        dict.fromkeys(
                            str(item.get("provider") or "")
                            for item in (
                                (result.get("deliberation") or {}).get("proposals")
                                or []
                            )
                            if item.get("provider")
                        )
                    ),
                },
                {
                    "id": evidence_id,
                    "type": "evidence",
                    "cycle": index,
                    "status": _status(result),
                    "credible": cycle_has_credible_evidence(cycle),
                    "independent_proxy": cycle_has_independent_evidence(cycle),
                    "engine": _engine(result),
                    "oracle": result.get("oracle_used"),
                    "verdict": execution.get("verdict"),
                    "code_sha256": hashlib.sha256(
                        str(result.get("code") or "").encode("utf-8")
                    ).hexdigest(),
                    "stdout_sha256": hashlib.sha256(
                        str(execution.get("stdout") or "").encode("utf-8")
                    ).hexdigest(),
                },
                {
                    "id": assessment_id,
                    "type": "assessment",
                    "cycle": index,
                    "status": _status(result),
                    "label": str(analysis.get("reasoning") or ""),
                    "next_direction": str(navigation.get("next_direction") or ""),
                    "macro_resolved": bool(navigation.get("macro_resolved", False)),
                },
            ]
        )
        edges.extend(
            [
                {"source": previous_assessment, "target": direction_id, "type": "selects"},
                {"source": direction_id, "target": hypothesis_id, "type": "generates"},
                {"source": hypothesis_id, "target": evidence_id, "type": "tests"},
                {"source": evidence_id, "target": assessment_id, "type": "updates"},
            ]
        )

        for branch in navigation.get("parallel_branches") or []:
            branch_text = str(branch.get("direction") or "").strip()
            if not branch_text:
                continue
            branch_hash = _text_hash(branch_text)
            branch_id = branch_by_hash.get(branch_hash)
            if branch_id is None:
                branch_id = f"branch_{len(branch_by_hash) + 1:03d}"
                branch_by_hash[branch_hash] = branch_id
                nodes.append(
                    {
                        "id": branch_id,
                        "type": "branch",
                        "origin_cycle": index,
                        "label": branch_text,
                        "motivation": str(branch.get("motivation") or ""),
                        "content_sha256": branch_hash,
                    }
                )
            edges.append(
                {"source": assessment_id, "target": branch_id, "type": "preserves"}
            )
        previous_assessment = assessment_id

    return {
        "schema_version": "1.0",
        "objective_sha256": _text_hash(objective),
        "nodes": nodes,
        "edges": edges,
    }


def estimate_model_calls(result: dict[str, Any]) -> int:
    """Count observable phase calls; it is a proxy when CLIs omit token telemetry."""
    deliberation = result.get("deliberation") or {}
    proposals = deliberation.get("proposals") or []
    critiques = deliberation.get("critiques") or []
    synthesis = 1 if len(proposals) > 1 else 0
    model_patches = len(result.get("validator_model_patch_history") or [])
    translations = 1 + int(result.get("retries") or 0) + model_patches
    reviews = sum(
        (
            not item.get("source")
            or str(item.get("source")).lower() == "model_reviewer"
        )
        for item in result.get("code_review_history") or []
        if isinstance(item, dict)
    )
    analyses = 1 + int(result.get("retries") or 0)
    navigation = 1 if result.get("navigation") else 0
    return len(proposals) + len(critiques) + synthesis + translations + reviews + analyses + navigation


def compute_trajectory_metrics(record: dict[str, Any]) -> dict[str, Any]:
    cycles = list(record.get("cycles") or [])
    human_interventions = int(record.get("human_interventions") or 1)
    credible = [cycle_has_credible_evidence(cycle) for cycle in cycles]
    independent = [cycle_has_independent_evidence(cycle) for cycle in cycles]
    statuses = [_status(cycle.get("result") or cycle) for cycle in cycles]
    hypothesis_by_cycle = [
        (
            _text_hash(str((cycle.get("result") or {}).get("conjecture") or ""))
            if str((cycle.get("result") or {}).get("conjecture") or "").strip()
            else ""
        )
        for cycle in cycles
    ]
    hypotheses = [item for item in hypothesis_by_cycle if item]
    directions = [
        _text_hash(str(cycle.get("direction") or ""))
        for cycle in cycles
        if str(cycle.get("direction") or "").strip()
    ]

    graph = build_research_graph(record)
    branches = [node for node in graph["nodes"] if node["type"] == "branch"]
    recovery_opportunities = 0
    recoveries = 0
    for index, status in enumerate(statuses[:-1]):
        if status not in {"REFUTED", "CODE_ERROR", "WEAK_PASS", "TOOL_ERROR"}:
            continue
        recovery_opportunities += 1
        next_hypothesis = hypothesis_by_cycle[index + 1]
        current_hypothesis = hypothesis_by_cycle[index]
        if (
            credible[index + 1]
            and next_hypothesis
            and next_hypothesis != current_hypothesis
        ):
            recoveries += 1

    process_diversity = []
    minority_retention = []
    heterogeneous_cycles = 0
    review_interventions = 0
    successful_review_recoveries = 0
    reviewer_blocked_cycles = 0
    reviewed_cycles = 0
    deterministic_repair_cycles = 0
    deterministic_repair_edits = 0
    model_patch_attempts = 0
    model_patches_applied = 0
    defect_counts: Counter[str] = Counter()
    for cycle, has_evidence in zip(cycles, credible):
        result = cycle.get("result") or {}
        metrics = compute_diversity_metrics({"cycle": result})
        process_diversity.append(metrics.get("perspective_diversity_score"))
        if metrics.get("heterogeneous_providers"):
            heterogeneous_cycles += 1
            minority_retention.append(metrics.get("synthesis_minority_retention"))
        history = list(result.get("code_review_history") or [])
        if not history and isinstance(result.get("code_review"), dict):
            history = [result["code_review"]]
        if history:
            reviewed_cycles += 1
        local_repairs = list(result.get("validator_local_repair_history") or [])
        model_patches = list(result.get("validator_model_patch_history") or [])
        if local_repairs:
            deterministic_repair_cycles += 1
        deterministic_repair_edits += sum(
            len(item.get("repairs") or [])
            for item in local_repairs
            if isinstance(item, dict)
        )
        model_patch_attempts += len(model_patches)
        model_patches_applied += sum(
            str(item.get("status") or "").upper() == "APPLIED"
            for item in model_patches
            if isinstance(item, dict)
        )
        if str(result.get("phase") or "").lower() in {
            "reviewer",
            "reviewer_retry",
        }:
            reviewer_blocked_cycles += 1
        for review_item in history:
            for label in review_item.get("defect_labels") or []:
                defect_counts[str(label)] += 1
        intervened = any(
            str(item.get("status") or "").upper() != "APPROVED"
            for item in history
        )
        if intervened:
            review_interventions += 1
            successful_review_recoveries += int(has_evidence)

    durations = [
        float(cycle.get("duration_s") or 0.0)
        for cycle in cycles
        if cycle.get("duration_s") is not None
    ]
    model_calls = sum(
        estimate_model_calls(cycle.get("result") or {}) for cycle in cycles
    )
    resolved = any(
        bool(((cycle.get("result") or {}).get("navigation") or {}).get("macro_resolved"))
        for cycle in cycles
    )
    return {
        "cycles_completed": len(cycles),
        "credible_evidence_cycles": sum(credible),
        "independent_evidence_cycles": sum(independent),
        "human_interventions": human_interventions,
        "human_prompt_efficiency": _rate(sum(credible), human_interventions),
        "autonomous_loop_yield": _rate(sum(credible), len(cycles)),
        "independent_evidence_rate": _rate(sum(independent), len(cycles)),
        "distinct_hypotheses": len(set(hypotheses)),
        "hypothesis_nonrepetition_rate": _rate(len(set(hypotheses)), len(hypotheses)),
        "direction_nonrepetition_rate": _rate(len(set(directions)), len(directions)),
        "preserved_independent_branches": len(branches),
        "recovery_opportunities": recovery_opportunities,
        "recoveries": recoveries,
        "recovery_rate_after_negative_evidence": _rate(
            recoveries, recovery_opportunities
        ),
        "operational_failure_rate": _rate(
            sum(status in OPERATIONAL_STATUSES for status in statuses),
            len(cycles),
        ),
        "heterogeneous_cycles": heterogeneous_cycles,
        "perspective_diversity_process_proxy": _mean(process_diversity),
        "cross_perspective_traceability_proxy": _mean(minority_retention),
        "review_interventions": review_interventions,
        "review_recovery_rate": _rate(
            successful_review_recoveries, review_interventions
        ),
        "validator_conversion_rate": _rate(sum(credible), len(cycles)),
        "reviewer_block_rate": _rate(reviewer_blocked_cycles, reviewed_cycles),
        "validator_defect_counts": dict(sorted(defect_counts.items())),
        "deterministic_repair_cycles": deterministic_repair_cycles,
        "deterministic_repair_edits": deterministic_repair_edits,
        "model_patch_attempts": model_patch_attempts,
        "model_patches_applied": model_patches_applied,
        "model_patch_acceptance_rate": _rate(
            model_patches_applied,
            model_patch_attempts,
        ),
        "macro_resolved": resolved,
        "estimated_model_calls": model_calls,
        "wall_time_seconds": round(sum(durations), 3),
        "credible_evidence_per_model_call": _rate(sum(credible), model_calls),
        "graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
    }


def blank_expert_scorecard(
    *,
    record: dict[str, Any],
    expert_anchors: dict[str, str],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Create a scorecard to be completed by a blinded human evaluator."""
    dimensions = {}
    for name, anchor in expert_anchors.items():
        dimensions[name] = {
            "weight": float(weights[name]),
            "case_anchor": anchor,
            "score_0_to_4": None,
            "evidence_nodes": [],
            "comment": "",
        }
    return {
        "schema_version": "1.0",
        "blinded": True,
        "case_id": record.get("case_id"),
        "configuration_blind_id": record.get("blind_id"),
        "seed_blind_id": record.get("seed_blind_id"),
        "rater_id": "",
        "dimensions": dimensions,
        "fatal_validity_issue": False,
        "fatal_validity_comment": "",
    }


def score_expert_scorecards(
    scorecards: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    cards = list(scorecards)
    if not cards:
        return None
    by_dimension: dict[str, list[float]] = defaultdict(list)
    weights: dict[str, float] = {}
    fatal = 0
    for card in cards:
        if not card.get("blinded", False):
            raise ValueError("Expert scorecards must remain architecture-blinded")
        fatal += int(bool(card.get("fatal_validity_issue")))
        for name, item in (card.get("dimensions") or {}).items():
            score = item.get("score_0_to_4")
            if score is None:
                continue
            value = float(score)
            if not 0 <= value <= 4:
                raise ValueError(f"Expert score outside 0..4 for {name}")
            by_dimension[name].append(value)
            weights[name] = float(item.get("weight") or 0.0)
    means = {name: round(mean(values), 3) for name, values in by_dimension.items()}
    present_weight = sum(weights[name] for name in means)
    weighted = (
        sum(means[name] * weights[name] for name in means) / present_weight
        if present_weight
        else None
    )
    return {
        "raters": len(cards),
        "completed_dimensions": len(means),
        "dimension_means_0_to_4": means,
        "blind_research_quality_0_to_100": (
            round(weighted * 25.0, 2) if weighted is not None else None
        ),
        "fatal_validity_flags": fatal,
        "score_vetoed": fatal > 0,
    }


def summarize_trajectory_records(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    complete = [item for item in records if item.get("state") == "complete"]
    by_configuration: dict[str, dict[str, Any]] = {}
    metric_names = (
        "human_prompt_efficiency",
        "autonomous_loop_yield",
        "independent_evidence_rate",
        "recovery_rate_after_negative_evidence",
        "operational_failure_rate",
        "cross_perspective_traceability_proxy",
        "credible_evidence_per_model_call",
        "wall_time_seconds",
        "estimated_model_calls",
    )
    for configuration in sorted(
        {str(item.get("configuration")) for item in complete}
    ):
        subset = [
            item for item in complete if item.get("configuration") == configuration
        ]
        by_configuration[configuration] = {
            "cells": len(subset),
            **{
                name: _mean((item.get("metrics") or {}).get(name) for item in subset)
                for name in metric_names
            },
            "macro_resolution_rate": _rate(
                sum(bool((item.get("metrics") or {}).get("macro_resolved")) for item in subset),
                len(subset),
            ),
            "blind_research_quality_0_to_100": _mean(
                (item.get("expert_evaluation") or {}).get(
                    "blind_research_quality_0_to_100"
                )
                for item in subset
            ),
        }
    return {
        "complete_cells": len(complete),
        "by_configuration": by_configuration,
        "interpretation": (
            "Automatic values are process and efficiency measurements. Scientific "
            "depth, novelty, usefulness, and causal cross-perspective uptake require "
            "the blinded expert scorecards."
        ),
    }


def stable_blind_id(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
