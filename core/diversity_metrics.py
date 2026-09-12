"""Deterministic diversity and paired-ablation metrics for ASTRA benchmarks."""
from __future__ import annotations

import json
import math
import random
import re
from statistics import mean
from typing import Any


OPERATIONAL_STATUSES = {
    "API_ERROR",
    "BUSY",
    "ERROR",
    "INSPECTION_ERROR",
    "NO_VERDICT",
    "PARTIAL",
    "TIMEOUT",
    "TOOL_ERROR",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def _tokens(text: str) -> list[str]:
    return [item.lower() for item in _TOKEN_RE.findall(text or "")]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def _jaccard_distance(left: set[Any], right: set[Any]) -> float | None:
    union = left | right
    if not union:
        return None
    return round(1.0 - len(left & right) / len(union), 4)


def _mean(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return round(mean(present), 4) if present else None


def extract_proposals(report: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize initial perspectives from every supported external pilot."""
    for key in ("designs", "strategies"):
        values = report.get(key)
        if isinstance(values, list):
            return [
                {
                    "provider": str(item.get("provider") or "unknown"),
                    "text": str(item.get("text") or ""),
                }
                for item in values
                if isinstance(item, dict)
            ]

    deliberation = ((report.get("cycle") or {}).get("deliberation") or {})
    values = deliberation.get("proposals")
    if isinstance(values, list):
        return [
            {
                "provider": str(item.get("provider") or "unknown"),
                "text": str(item.get("text") or ""),
            }
            for item in values
            if isinstance(item, dict)
        ]

    navigation = report.get("navigation")
    if isinstance(navigation, list):
        providers = list((report.get("architecture") or {}).get("proposers") or [])
        return [
            {
                "provider": (
                    str(providers[index])
                    if index < len(providers)
                    else "unknown"
                ),
                "text": json.dumps(item, sort_keys=True),
            }
            for index, item in enumerate(navigation)
            if isinstance(item, dict)
        ]
    return []


def _synthesis_text(report: dict[str, Any]) -> str:
    if report.get("synthesis"):
        return str(report["synthesis"])
    if report.get("candidate"):
        return str(report["candidate"])
    return str(((report.get("cycle") or {}).get("conjecture") or ""))


def compute_diversity_metrics(report: dict[str, Any]) -> dict[str, Any]:
    """Compute evaluator-independent process metrics from one cell report.

    These metrics quantify observable disagreement and intervention. They do not
    claim that lexical distance is itself scientific quality; quality remains the
    benchmark's native PASS/FAIL result.
    """
    proposals = extract_proposals(report)
    valid = [
        item
        for item in proposals
        if item["text"].strip()
        and not item["text"].lstrip().startswith("API_ERROR:")
    ]
    result: dict[str, Any] = {
        "proposal_count": len(proposals),
        "valid_proposal_count": len(valid),
        "provider_count": len({item["provider"] for item in valid}),
        "heterogeneous_providers": len(
            {item["provider"] for item in valid}
        ) > 1,
    }

    proposal_tokens = [_tokens(item["text"]) for item in valid[:2]]
    if len(proposal_tokens) == 2:
        left, right = proposal_tokens
        unigram = _jaccard_distance(set(left), set(right))
        bigram = _jaccard_distance(_bigrams(left), _bigrams(right))
        left_numbers = set(_NUMBER_RE.findall(valid[0]["text"]))
        right_numbers = set(_NUMBER_RE.findall(valid[1]["text"]))
        numeric = _jaccard_distance(left_numbers, right_numbers)
        length_ratio = (
            round(min(len(left), len(right)) / max(len(left), len(right)), 4)
            if left and right
            else None
        )
        components = [
            (unigram, 0.6),
            (bigram, 0.4),
        ]
        score = (
            round(
                sum(float(value) * weight for value, weight in components)
                / sum(weight for value, weight in components if value is not None),
                4,
            )
            if all(value is not None for value, _weight in components)
            else None
        )
        result.update(
            {
                "unigram_jaccard_distance": unigram,
                "bigram_jaccard_distance": bigram,
                "numeric_jaccard_distance": numeric,
                "proposal_length_ratio": length_ratio,
                "perspective_diversity_score": score,
            }
        )
    else:
        result.update(
            {
                "unigram_jaccard_distance": None,
                "bigram_jaccard_distance": None,
                "numeric_jaccard_distance": None,
                "proposal_length_ratio": None,
                "perspective_diversity_score": None,
            }
        )

    synthesis_tokens = set(_tokens(_synthesis_text(report)))
    source_sets = [set(tokens) for tokens in proposal_tokens]
    source_union = set().union(*source_sets) if source_sets else set()
    result["synthesis_source_coverage"] = (
        round(len(synthesis_tokens & source_union) / len(synthesis_tokens), 4)
        if synthesis_tokens
        else None
    )
    result["synthesis_proposal_retention"] = (
        round(len(synthesis_tokens & source_union) / len(source_union), 4)
        if source_union
        else None
    )
    per_source_retention = [
        len(synthesis_tokens & source) / len(source)
        for source in source_sets
        if source
    ]
    result["synthesis_minority_retention"] = (
        round(min(per_source_retention), 4)
        if per_source_retention
        else None
    )

    deliberation = ((report.get("cycle") or {}).get("deliberation") or {})
    critiques = deliberation.get("critiques") or []
    result["cross_critique_count"] = len(critiques)

    review = report.get("review") or (report.get("cycle") or {}).get(
        "code_review"
    ) or {}
    review_status = str(review.get("status") or "").upper()
    result["review_status"] = review_status or None
    result["review_intervened"] = bool(
        review_status and review_status != "APPROVED"
    )

    attempts = report.get("attempts") or []
    first_status = ""
    if attempts and isinstance(attempts[0], dict):
        first_status = str(
            (attempts[0].get("evaluation") or {}).get("status") or ""
        ).upper()
    final_status = str(
        (report.get("evaluation") or {}).get("status") or ""
    ).upper()
    cycle = report.get("cycle") or {}
    cycle_retries = int(cycle.get("retries") or 0)
    local_repairs = list(cycle.get("validator_local_repair_history") or [])
    model_patches = list(cycle.get("validator_model_patch_history") or [])
    deterministic_edit_count = sum(
        len(item.get("repairs") or [])
        for item in local_repairs
        if isinstance(item, dict)
    )
    applied_model_patches = sum(
        str(item.get("status") or "").upper() == "APPLIED"
        for item in model_patches
        if isinstance(item, dict)
    )
    result["deterministic_repair_edits"] = deterministic_edit_count
    result["model_patch_attempts"] = len(model_patches)
    result["model_patches_applied"] = applied_model_patches
    result["repair_attempts"] = max(
        len(attempts) - 1,
        cycle_retries,
        len(local_repairs) + len(model_patches),
        0,
    )
    result["repair_lift"] = bool(
        first_status
        and first_status != "PASS"
        and final_status == "PASS"
    )
    return result


def _bootstrap_ci(
    deltas: list[int],
    *,
    seed: int,
    samples: int = 5000,
) -> list[float] | None:
    if not deltas:
        return None
    rng = random.Random(seed)
    size = len(deltas)
    estimates = sorted(
        sum(rng.choice(deltas) for _ in range(size)) / size
        for _ in range(samples)
    )
    return [
        round(estimates[int(0.025 * (samples - 1))], 4),
        round(estimates[int(0.975 * (samples - 1))], 4),
    ]


def paired_architecture_summary(
    records: list[dict[str, Any]],
    *,
    diverse: str = "full",
    control: str = "homogeneous-proposers",
    seed: int = 20260724,
) -> dict[str, Any] | None:
    """Summarize the preregistered paired heterogeneous-vs-homogeneous test."""
    by_key = {
        (item.get("case_id"), item.get("configuration")): item
        for item in records
    }
    case_ids = sorted(
        {
            str(item.get("case_id"))
            for item in records
            if item.get("configuration") in {diverse, control}
        }
    )
    pairs = []
    for case_id in case_ids:
        left = by_key.get((case_id, diverse))
        right = by_key.get((case_id, control))
        if not left or not right:
            continue
        if left.get("state") != "complete" or right.get("state") != "complete":
            continue
        statuses = {
            str(left.get("status") or "").upper(),
            str(right.get("status") or "").upper(),
        }
        if statuses & OPERATIONAL_STATUSES:
            continue
        left_pass = str(left.get("status") or "").upper() == "PASS"
        right_pass = str(right.get("status") or "").upper() == "PASS"
        pairs.append(
            {
                "case_id": case_id,
                "diverse_pass": left_pass,
                "control_pass": right_pass,
                "delta": int(left_pass) - int(right_pass),
                "diverse_diversity": (
                    (left.get("diversity") or {}).get(
                        "perspective_diversity_score"
                    )
                ),
                "control_diversity": (
                    (right.get("diversity") or {}).get(
                        "perspective_diversity_score"
                    )
                ),
            }
        )
    if not pairs:
        return None

    wins = sum(item["delta"] == 1 for item in pairs)
    losses = sum(item["delta"] == -1 for item in pairs)
    ties = len(pairs) - wins - losses
    discordant = wins + losses
    one_sided_p = (
        sum(math.comb(discordant, k) for k in range(wins, discordant + 1))
        / (2 ** discordant)
        if discordant
        else 1.0
    )
    two_sided_p = (
        min(
            1.0,
            2
            * sum(
                math.comb(discordant, k)
                for k in range(0, min(wins, losses) + 1)
            )
            / (2 ** discordant),
        )
        if discordant
        else 1.0
    )
    deltas = [int(item["delta"]) for item in pairs]
    diverse_scores = [
        item["diverse_diversity"]
        for item in pairs
        if item["diverse_diversity"] is not None
    ]
    control_scores = [
        item["control_diversity"]
        for item in pairs
        if item["control_diversity"] is not None
    ]
    return {
        "diverse_configuration": diverse,
        "control_configuration": control,
        "paired_scored_cases": len(pairs),
        "diverse_wins": wins,
        "control_wins": losses,
        "ties": ties,
        "pass_rate_delta": round(sum(deltas) / len(deltas), 4),
        "pass_rate_delta_bootstrap_95": _bootstrap_ci(
            deltas,
            seed=seed,
        ),
        "mcnemar_exact_one_sided_p": round(one_sided_p, 6),
        "mcnemar_exact_two_sided_p": round(two_sided_p, 6),
        "mean_perspective_diversity": {
            diverse: _mean(diverse_scores),
            control: _mean(control_scores),
        },
    }
