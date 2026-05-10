"""
scripts/run_benchmarks.py — Headless benchmark runner for ASTRUM Production.

Usage:
    python scripts/run_benchmarks.py
    python scripts/run_benchmarks.py --provider gemini
    python scripts/run_benchmarks.py --conjecture-provider gemini --translator-provider anthropic --analyst-provider openai
    python scripts/run_benchmarks.py --only gr_schwarzschild_ricci_scalar,logic_am_gm_two_variables
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.preflight import load_project_env

load_project_env()


def _apply_provider_args(args) -> None:
    if args.provider:
        os.environ.setdefault("ASTRA_CONJECTURE_PROVIDER", args.provider)
        os.environ.setdefault("ASTRA_TRANSLATOR_PROVIDER", args.provider)
        os.environ.setdefault("ASTRA_ANALYST_PROVIDER", args.provider)
    if args.conjecture_provider:
        os.environ["ASTRA_CONJECTURE_PROVIDER"] = args.conjecture_provider
    if args.translator_provider:
        os.environ["ASTRA_TRANSLATOR_PROVIDER"] = args.translator_provider
    if args.analyst_provider:
        os.environ["ASTRA_ANALYST_PROVIDER"] = args.analyst_provider


async def _run_benchmark_cycle(conjecture: str, max_retries: int) -> tuple[str, dict]:
    from main import (
        phase_3_formal_translation,
        phase_4_validation_oracle,
        phase_5_result_analysis,
    )

    python_code = None
    code_retries = 0

    while True:
        if python_code is None:
            python_code = await phase_3_formal_translation(conjecture)

        exec_result = await phase_4_validation_oracle(python_code)
        analysis = await phase_5_result_analysis(conjecture, exec_result)
        status = analysis.get("status", "UNKNOWN")

        if status == "CODE_ERROR":
            code_retries += 1
            if code_retries > max_retries:
                return "CODE_ERROR", analysis

            corrected = analysis.get("corrected_code", "")
            if corrected:
                if "```" in corrected:
                    parts = corrected.split("```")
                    if len(parts) >= 3:
                        corrected = parts[1]
                        first_line = corrected.split("\n")[0].strip()
                        if first_line in ("python", "sage", "maxima", "cadabra"):
                            corrected = corrected.split("\n", 1)[1]
                python_code = corrected.strip()
            else:
                python_code = await phase_3_formal_translation(
                    conjecture,
                    is_correction=True,
                    previous_error=exec_result.get("stderr", "Unknown execution error"),
                )
        else:
            return status, analysis


def _save_report(results: list[dict], providers: dict[str, str], run_file: Path) -> None:
    ts = datetime.datetime.now().isoformat()
    total = len(results)
    matches = sum(1 for r in results if r["match"])

    vals = list(providers.values())
    if len(set(vals)) == 1:
        layout = f"{vals[0]} for conjecture, translator, and analyst"
    else:
        layout = (
            f"{providers['conjecture']} for conjecture, "
            f"{providers['translator']} for translator, "
            f"{providers['analyst']} for analyst"
        )

    data = {
        "updated": ts,
        "provider_layout": layout,
        "providers": providers,
        "results_recorded": total,
        "matches": matches,
        "results": results,
    }

    json_path = run_file.with_suffix(".json")
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    lines = [
        "# ASTRUM Benchmark Run",
        "",
        f"- Updated: {ts}",
        f"- Provider layout: {layout}",
        f"- Results recorded: {total}",
        f"- Matches expected: {matches}/{total}",
        "",
        "| Benchmark | Domain | Expected | Observed | Match |",
        "|---|---|---:|---:|---:|",
    ]
    for r in results:
        match_str = "yes" if r["match"] else "no"
        lines.append(
            f"| `{r['id']}` | {r['domain']} | {r['expected']} | {r['observed']} | {match_str} |"
        )

    run_file.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main(args) -> None:
    _apply_provider_args(args)

    from core.benchmarks import load_benchmarks
    from core.preflight import phase_provider_map
    from main import _reload_llm_clients

    _reload_llm_clients()
    providers = phase_provider_map()

    benchmarks = load_benchmarks()
    if args.only:
        only_ids = {s.strip() for s in args.only.split(",")}
        benchmarks = [b for b in benchmarks if b.id in only_ids]

    vals = list(providers.values())
    layout = (
        f"{vals[0]} (all phases)"
        if len(set(vals)) == 1
        else f"{providers['conjecture']} / {providers['translator']} / {providers['analyst']}"
    )

    print(f"\nASTRUM Headless Benchmark Runner")
    print(f"Provider: {layout}")
    print(f"Cases:    {len(benchmarks)}")
    print("-" * 60)

    ts_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "workspace" / "benchmark_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_file = run_dir / f"benchmark_run_{ts_slug}"

    results: list[dict] = []

    for b in benchmarks:
        n = len(results) + 1
        print(f"\n[{n}/{len(benchmarks)}] {b.id} ({b.domain})  expected={b.expected}")
        try:
            status, analysis = await _run_benchmark_cycle(b.to_prompt(), args.max_retries)
            match = status == b.expected
            r = {
                "id": b.id,
                "domain": b.domain,
                "expected": b.expected,
                "observed": status,
                "match": match,
                "notes": analysis.get("reasoning", "")[:300],
            }
            tag = "PASS" if match else "FAIL"
            print(f"  -> [{tag}]  observed={status}")
            if not match:
                print(f"     {r['notes'][:120]}")
        except Exception as exc:
            r = {
                "id": b.id,
                "domain": b.domain,
                "expected": b.expected,
                "observed": "ERROR",
                "match": False,
                "notes": str(exc)[:300],
            }
            print(f"  -> [ERROR] {exc}")

        results.append(r)
        _save_report(results, providers, run_file)

    matches = sum(1 for r in results if r["match"])
    print("\n" + "=" * 60)
    print(f"DONE  {matches}/{len(results)} matches  ({round(matches/len(results)*100,1)}%)")
    print(f"Report: {run_file}.md")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRUM headless benchmark runner")
    parser.add_argument("--provider", help="Provider for all phases")
    parser.add_argument("--conjecture-provider", dest="conjecture_provider")
    parser.add_argument("--translator-provider", dest="translator_provider")
    parser.add_argument("--analyst-provider", dest="analyst_provider")
    parser.add_argument("--max-retries", dest="max_retries", type=int, default=3)
    parser.add_argument("--only", help="Comma-separated benchmark IDs to run")
    args = parser.parse_args()

    asyncio.run(main(args))
