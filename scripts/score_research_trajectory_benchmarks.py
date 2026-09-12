#!/usr/bin/env python3
"""Validate blinded expert scorecards and unblind aggregate comparisons."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.research_trajectory_metrics import (
    score_expert_scorecards,
    summarize_trajectory_records,
)


def _write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _is_complete(card: dict[str, Any]) -> bool:
    dimensions = card.get("dimensions") or {}
    return bool(
        card.get("rater_id")
        and dimensions
        and all(item.get("score_0_to_4") is not None for item in dimensions.values())
    )


def _scorecards(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(
        run_dir.glob("cells/*/*/expert_bundle/expert_scorecard*.json")
    ):
        card = json.loads(path.read_text(encoding="utf-8"))
        if not _is_complete(card):
            continue
        blind_id = str(card.get("configuration_blind_id") or "")
        if not blind_id:
            raise ValueError(f"Scorecard has no blind id: {path}")
        card["_source"] = str(path)
        grouped.setdefault(blind_id, []).append(card)
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score blinded ASTRA research-trajectory evaluations."
    )
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--minimum-raters", type=int, default=2)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Score cells with enough ratings and leave other cells pending.",
    )
    args = parser.parse_args()

    checkpoint = Path(args.checkpoint).resolve()
    report = json.loads(checkpoint.read_text(encoding="utf-8"))
    grouped = _scorecards(checkpoint.parent)
    missing = []
    scored = 0
    for record in report.get("records") or []:
        if record.get("state") != "complete":
            continue
        blind_id = str(record.get("blind_id") or "")
        cards = grouped.get(blind_id, [])
        rater_ids = [str(card.get("rater_id")) for card in cards]
        if len(rater_ids) != len(set(rater_ids)):
            raise ValueError(f"Duplicate rater ids for blind cell {blind_id}")
        if len(cards) < args.minimum_raters:
            missing.append(
                {
                    "blind_id": blind_id,
                    "case_id": record.get("case_id"),
                    "ratings": len(cards),
                }
            )
            continue
        record["expert_evaluation"] = score_expert_scorecards(cards)
        scored += 1

    if missing and not args.allow_partial:
        preview = ", ".join(
            f"{item['blind_id']} ({item['ratings']})" for item in missing[:8]
        )
        raise ValueError(
            f"{len(missing)} cells have fewer than {args.minimum_raters} complete "
            f"ratings: {preview}"
        )
    report["summary"] = summarize_trajectory_records(report.get("records") or [])
    report["expert_scoring"] = {
        "scored_cells": scored,
        "minimum_raters": args.minimum_raters,
        "missing_cells": missing,
        "architecture_unblinded_after_scoring": True,
    }
    _write_json(checkpoint, report)
    _write_json(
        checkpoint.parent / "expert_comparison.json",
        {
            "run_id": report.get("run_id"),
            "expert_scoring": report["expert_scoring"],
            "summary": report["summary"],
        },
    )
    print(
        f"scored_cells={scored} missing_cells={len(missing)} "
        f"output={checkpoint.parent / 'expert_comparison.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
