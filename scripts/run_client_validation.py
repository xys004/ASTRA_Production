"""Run ASTRA's minimum client-facing validation package."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.client_validation import (
    load_client_validation_cases,
    route_validator,
    run_client_validation_case,
    select_oracles,
)
from core.preflight import load_project_env

load_project_env()


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# ASTRA Minimum Client Validation",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Created: {report['created_at']}",
        f"- Cases: {summary['cases']}",
        f"- Evidence bundles: {summary['bundles']}",
        f"- Passing bundles: {summary['passing_bundles']}/{summary['bundles']}",
        f"- Passing cases: {summary['passing_cases']}/{summary['cases']}",
        f"- Cross-oracle agreement: {summary['cross_oracle_agreement']}",
        "",
        "| Application case | Validator | Oracle | Claim | Status | Seconds |",
        "|---|---|---|---|---:|---:|",
    ]
    for bundle in report["bundles"]:
        validation = bundle["validation"]
        lines.append(
            f"| `{bundle['case']['id']}` | {bundle['route']['primary']} | "
            f"{validation['oracle']} | {validation['claim_verdict']} | "
            f"{validation['status']} | {validation['duration_s']} |"
        )
    lines.extend([
        "",
        "Each JSON bundle records the artifact hash, assumptions, limitations,",
        "validator decision, executable evidence, environment and reproduction command.",
    ])
    return "\n".join(lines) + "\n"


def _summarize(cases, bundles: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle["case"]["id"]].append(bundle)
    passing_cases = sum(
        bool(items) and all(item["validation"]["status"] == "PASS" for item in items)
        for items in grouped.values()
    )
    comparable = [
        items for items in grouped.values()
        if len(items) > 1
    ]
    agreement = [
        len({item["validation"]["claim_verdict"] for item in items}) == 1
        for items in comparable
    ]
    return {
        "registered_cases": len(cases),
        "cases": len(grouped),
        "bundles": len(bundles),
        "passing_bundles": sum(
            bundle["validation"]["status"] == "PASS" for bundle in bundles
        ),
        "passing_cases": passing_cases,
        "cross_oracle_cases": len(comparable),
        "cross_oracle_agreement": (
            round(sum(agreement) / len(agreement), 6) if agreement else None
        ),
    }


async def main(args: argparse.Namespace) -> int:
    if args.prepare_lean4:
        from core.formal_validators import bootstrap_remote_formal_environment

        result = await bootstrap_remote_formal_environment(timeout=args.timeout)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "READY" else 1

    cases = load_client_validation_cases(include_optional=args.include_optional)
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case.id in wanted]
        missing = wanted - {case.id for case in cases}
        if missing:
            raise ValueError(f"Unknown or unavailable client cases: {sorted(missing)}")

    if args.list:
        print(json.dumps([
            {
                **case.public_dict(),
                "route": route_validator(case).public_dict(),
                "selected_oracles": select_oracles(case, args.oracle),
            }
            for case in cases
        ], indent=2))
        return 0

    bundles = []
    for index, case in enumerate(cases, 1):
        oracles = select_oracles(case, args.oracle)
        if not oracles:
            print(f"[{index}/{len(cases)}] {case.id}: skipped (oracle unsupported)")
            continue
        for oracle in oracles:
            print(f"[{index}/{len(cases)}] {case.id} -> {oracle}", flush=True)
            bundle = await run_client_validation_case(
                case,
                oracle=oracle,
                timeout=args.timeout,
            )
            bundles.append(bundle)
            verdict = bundle["validation"]
            print(
                f"  {verdict['status']} claim={verdict['claim_verdict']} "
                f"validator={bundle['route']['primary']} "
                f"time={verdict['duration_s']}s",
                flush=True,
            )

    run_id = dt.datetime.now().strftime("client_validation_%Y%m%d_%H%M%S")
    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "settings": {
            "oracle": args.oracle,
            "timeout_s": args.timeout,
            "include_optional": args.include_optional,
        },
        "summary": _summarize(cases, bundles),
        "bundles": bundles,
    }
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (
        ROOT / "workspace" / "client_validation_runs"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    md_path = out_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "summary": report["summary"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if (
        report["summary"]["cases"] > 0
        and report["summary"]["passing_cases"] == report["summary"]["cases"]
    ) else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ASTRA minimum client validation")
    result.add_argument("--only", default="", help="Comma-separated case IDs")
    result.add_argument(
        "--oracle",
        choices=["auto", "local", "astrum", "both"],
        default="both",
    )
    result.add_argument("--timeout", type=int, default=300)
    result.add_argument("--list", action="store_true")
    result.add_argument("--include-optional", action="store_true")
    result.add_argument(
        "--prepare-lean4",
        action="store_true",
        help="Install the pinned no-sudo Lean 4/Mathlib environment on ASTRUM.",
    )
    result.add_argument("--output-dir", default="")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main(parser().parse_args())))
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
