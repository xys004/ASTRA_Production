#!/usr/bin/env python3
"""Paired analysis of the review-independence ablation.

Reads quality-benchmark run reports, aggregates the validator_audit track by
arm, and computes the statistics fixed in REVIEW_INDEPENDENCE_ABLATION.md:
per-arm sensitivity, specificity, Youden's J and defect-label recall with
Wilson intervals, McNemar's exact test on the pre-specified paired
comparisons under Holm correction, and Cochran's Q as an omnibus check.

It also runs the contamination audit. A case whose record shows a reviewer
model other than the one its arm pinned, or a quota warning, is reported and
excluded from the rates rather than silently averaged in.

Usage:
    python scripts/analyze_review_ablation.py workspace/quality_benchmark_runs/*.json
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Arm label -> (human name, expected reviewer model). "" means no model call.
ARMS: dict[str, tuple[str, str]] = {
    "full": ("D deterministic guard", ""),
    "abl-self": ("S same model, fresh context", "claude-opus-4-8"),
    "abl-weights": ("W same provider, other model", "sonnet"),
    "abl-cross": ("P cross-provider, neutral prompt", "gpt-5.6-sol"),
    "abl-p-shipped": ("P+ cross-provider, shipped prompt", "gpt-5.6-sol"),
}

# Pre-specified comparisons, in the order registered. (a, b) tests a against b.
COMPARISONS = [
    ("abl-self", "full", "H1a  any audit beats none"),
    ("abl-weights", "abl-self", "H1b  different weights beat re-reading"),
    ("abl-cross", "abl-weights", "H1c  different vendor beats same vendor"),
    ("abl-p-shipped", "abl-cross", "prompt identity is worth something"),
]


# ----------------------------------------------------------------- statistics
def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion."""
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pair counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def cochran_q(table: list[list[int]]) -> tuple[float, int, float] | None:
    """Cochran's Q over a cases x arms binary table. Returns (Q, df, p)."""
    if not table or len(table[0]) < 2:
        return None
    k = len(table[0])
    col = [sum(row[j] for row in table) for j in range(k)]
    row = [sum(r) for r in table]
    num = (k - 1) * (k * sum(c * c for c in col) - sum(col) ** 2)
    den = k * sum(row) - sum(r * r for r in row)
    if den == 0:
        return None
    q = num / den
    df = k - 1
    try:
        from scipy.stats import chi2

        p = float(chi2.sf(q, df))
    except Exception:
        p = float("nan")
    return q, df, p


def holm(pvalues: list[float]) -> list[float]:
    """Holm-adjusted p-values, order preserved."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, idx in enumerate(order):
        value = (len(pvalues) - rank) * pvalues[idx]
        running = max(running, min(1.0, value))
        adjusted[idx] = running
    return adjusted


def bootstrap_j(
    cases: list[tuple[bool, bool]],
    draws: int = 5000,
    seed: int = 20260911,
) -> tuple[float, float] | None:
    """Percentile interval for Youden's J over cases of (is_defective, correct)."""
    if not cases:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(draws):
        sample = [cases[rng.randrange(len(cases))] for _ in cases]
        j = youden(sample)
        if j is not None:
            values.append(j)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def youden(cases: list[tuple[bool, bool]]) -> float | None:
    flawed = [ok for defective, ok in cases if defective]
    sound = [ok for defective, ok in cases if not defective]
    if not flawed or not sound:
        return None
    return sum(flawed) / len(flawed) + sum(sound) / len(sound) - 1


# ----------------------------------------------------------------- aggregation
def load_records(paths: list[str]) -> list[dict[str, Any]]:
    records = []
    for pattern in paths:
        for path in sorted(glob.glob(pattern)):
            report = json.loads(Path(path).read_text(encoding="utf-8"))
            for record in report.get("records", []):
                if record.get("track") == "validator_audit":
                    record["_source"] = Path(path).name
                    records.append(record)
    return records


def contamination(record: dict[str, Any]) -> str:
    """Reason this record must be discarded, or an empty string."""
    arm = record.get("configuration", "")
    expected_model = ARMS.get(arm, ("", ""))[1]
    if not expected_model:
        return ""
    detail = record.get("detail") or {}
    used = (detail.get("cli_models") or {}).get("reviewer", "")
    if used and used != expected_model:
        return f"reviewer answered as {used}, arm pinned {expected_model}"
    warnings = detail.get("warnings") or []
    for warning in warnings:
        if "CUOTA" in str(warning).upper() or "QUOTA" in str(warning).upper():
            return "quota warning on the call"
    if str(record.get("observed", "")).upper() in {"API_ERROR", "TOOL_ERROR"}:
        return f"call failed: {record.get('observed')}"
    return ""


def majority(values: list[bool]) -> bool:
    return sum(values) * 2 > len(values)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reports", nargs="+", help="quality benchmark JSON reports")
    ap.add_argument("--json-out", default="", help="write the aggregate here")
    args = ap.parse_args()

    records = load_records(args.reports)
    if not records:
        print("no validator_audit records found", file=sys.stderr)
        return 1

    discarded: list[tuple[str, str, str]] = []
    kept: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        reason = contamination(record)
        if reason:
            discarded.append((record.get("configuration", ""), record.get("id", ""), reason))
            continue
        kept[(record.get("configuration", ""), record.get("id", ""))].append(record)

    arms = [a for a in ARMS if any(key[0] == a for key in kept)]
    case_ids = sorted({key[1] for key in kept})

    # Per (arm, case): majority vote over repeats, plus repeat dispersion.
    outcome: dict[tuple[str, str], bool] = {}
    defective: dict[str, bool] = {}
    labels_found: dict[str, int] = defaultdict(int)
    labels_expected: dict[str, int] = defaultdict(int)
    unstable = 0
    for (arm, case), group in kept.items():
        votes = [bool(r.get("correct")) for r in group]
        outcome[(arm, case)] = majority(votes)
        if len(set(votes)) > 1:
            unstable += 1
        defective[case] = bool(group[0].get("expected_defects"))
        for r in group:
            expected = set(x.lower() for x in (r.get("expected_defects") or []))
            observed = set(x.lower() for x in (r.get("observed_defects") or []))
            labels_expected[arm] += len(expected)
            labels_found[arm] += len(expected & observed)

    print("=" * 78)
    print("REVIEW-INDEPENDENCE ABLATION, paired analysis")
    print("=" * 78)
    print(f"records {len(records)}   kept {sum(len(v) for v in kept.values())}   "
          f"discarded {len(discarded)}   cases {len(case_ids)}   arms {len(arms)}")
    print(f"case/arm cells where repeats disagreed: {unstable}")
    if discarded:
        print("\nDISCARDED")
        for arm, case, reason in discarded[:20]:
            print(f"  {arm:16} {case:48} {reason}")

    print("\nPER-ARM RATES (majority vote over repeats)")
    print(f"{'arm':34} {'sens':>13} {'spec':>13} {'J':>18} {'labels':>8}")
    print("-" * 92)
    summary: dict[str, Any] = {}
    for arm in arms:
        cases = [(defective[c], outcome[(arm, c)]) for c in case_ids if (arm, c) in outcome]
        flawed = [ok for d, ok in cases if d]
        sound = [ok for d, ok in cases if not d]
        sens = sum(flawed) / len(flawed) if flawed else float("nan")
        spec = sum(sound) / len(sound) if sound else float("nan")
        j = youden(cases)
        ws = wilson(sum(flawed), len(flawed))
        wp = wilson(sum(sound), len(sound))
        bj = bootstrap_j(cases)
        lab = (labels_found[arm] / labels_expected[arm]) if labels_expected[arm] else float("nan")
        name = ARMS[arm][0]
        sens_s = f"{sens:.2f} [{ws[0]:.2f},{ws[1]:.2f}]" if ws else f"{sens:.2f}"
        spec_s = f"{spec:.2f} [{wp[0]:.2f},{wp[1]:.2f}]" if wp else f"{spec:.2f}"
        j_s = f"{j:+.2f} [{bj[0]:+.2f},{bj[1]:+.2f}]" if (j is not None and bj) else "n/a"
        print(f"{name:34} {sens_s:>13} {spec_s:>13} {j_s:>18} {lab:>8.2f}")
        summary[arm] = {
            "name": name, "sensitivity": sens, "specificity": spec, "youden_j": j,
            "sensitivity_ci": ws, "specificity_ci": wp, "youden_j_ci": bj,
            "defect_label_recall": lab, "n_flawed": len(flawed), "n_sound": len(sound),
        }

    table = [[int(outcome[(a, c)]) for a in arms if (a, c) in outcome]
             for c in case_ids if all((a, c) in outcome for a in arms)]
    q = cochran_q(table)
    print(f"\nOMNIBUS  Cochran's Q over {len(table)} complete cases: ", end="")
    print(f"Q={q[0]:.3f} df={q[1]} p={q[2]:.4f}" if q else "not computable")

    print("\nPRE-SPECIFIED PAIRED COMPARISONS (McNemar exact, Holm-corrected)")
    raw, rows = [], []
    for a, b, label in COMPARISONS:
        if a not in arms or b not in arms:
            continue
        both = [c for c in case_ids if (a, c) in outcome and (b, c) in outcome]
        bb = sum(1 for c in both if outcome[(a, c)] and not outcome[(b, c)])
        cc = sum(1 for c in both if outcome[(b, c)] and not outcome[(a, c)])
        p = mcnemar_exact(bb, cc)
        raw.append(p)
        rows.append((label, a, b, bb, cc, p))
    adj = holm(raw) if raw else []
    print(f"{'hypothesis':44} {'a>b':>5} {'b>a':>5} {'p':>8} {'p_holm':>8}")
    print("-" * 76)
    comparisons_out = []
    for (label, a, b, bb, cc, p), pa in zip(rows, adj):
        print(f"{label:44} {bb:5d} {cc:5d} {p:8.4f} {pa:8.4f}")
        comparisons_out.append({"hypothesis": label, "arm_a": a, "arm_b": b,
                                "a_only": bb, "b_only": cc, "p": p, "p_holm": pa})

    print("\nREADING: 'a>b' counts cases the first arm got right and the second did not.")
    print("With few discordant pairs no test can reach significance; that is a")
    print("statement about the corpus size, not about the architecture.")

    if args.json_out:
        out = {"arms": summary, "comparisons": comparisons_out,
               "cochran_q": q, "discarded": discarded, "cases": len(case_ids),
               "unstable_cells": unstable}
        Path(args.json_out).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"\naggregate written to {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
