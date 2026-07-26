"""Run ASTRA Quality Benchmark v1.

Examples:
    python scripts/run_quality_benchmarks.py --list
    python scripts/run_quality_benchmarks.py --tier smoke --tracks audit,execution
    python scripts/run_quality_benchmarks.py --tier standard --oracle both --jobs 4
    python scripts/run_quality_benchmarks.py --tier release --repeats 3 \
        --config full,no-review,no-ensemble

The runner calls ``astra_tool.py`` through its JSON subprocess boundary. Each
cycle therefore receives an isolated environment, which makes concurrent
ablations safe and prevents one configuration from contaminating another.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.preflight import load_project_env
from core.architecture_configs import (
    ARCHITECTURE_ROLES,
    architecture_environment,
)
from core.quality_benchmarks import (
    QualityCase,
    load_quality_cases,
    quality_summary,
    select_quality_cases,
)
from core.quality_metrics import summarize_records

load_project_env()


CONFIGURATIONS = {name: {} for name in ARCHITECTURE_ROLES}


def _parse_set(raw: str) -> set[str]:
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _parse_tracks(raw: str) -> set[str]:
    aliases = {"audit": "validator_audit", "truth": "cycle", "repro": "execution"}
    tracks = {aliases.get(item, item) for item in _parse_set(raw)}
    unknown = tracks - {"cycle", "validator_audit", "execution"}
    if unknown:
        raise ValueError(f"Unknown tracks: {sorted(unknown)}")
    return tracks


def _parse_configs(raw: str) -> list[str]:
    configs = [part.strip().lower() for part in raw.split(",") if part.strip()]
    unknown = set(configs) - set(CONFIGURATIONS)
    if unknown:
        raise ValueError(f"Unknown configurations: {sorted(unknown)}")
    return configs


def _oracles(raw: str) -> list[str]:
    value = raw.strip().lower()
    if value == "both":
        return ["local", "astrum"]
    if value not in {"local", "astrum", "auto"}:
        raise ValueError(f"Unknown oracle: {raw}")
    return [value]


def _safe_detail(value: Any) -> Any:
    """Remove machine addressing from reports that may later be published."""
    if isinstance(value, dict):
        return {
            key: _safe_detail(item)
            for key, item in value.items()
            if key not in {"remote_host"}
        }
    if isinstance(value, list):
        return [_safe_detail(item) for item in value]
    return value


async def _invoke_tool(
    payload: dict[str, Any],
    *,
    env: dict[str, str],
    timeout: int,
) -> tuple[dict[str, Any], str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "astra_tool.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
        env=env,
    )
    body = json.dumps(payload).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(body), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {"error": f"TIMEOUT after {timeout}s"}, ""
    text = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text), err[-4000:]
    except json.JSONDecodeError:
        # Defensive fallback if a third-party CLI leaked a line to stdout.
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line), err[-4000:]
            except json.JSONDecodeError:
                continue
        return {
            "error": "TOOL_ERROR: astra_tool returned non-JSON output",
            "stdout_tail": text[-2000:],
        }, err[-4000:]


def _configuration_env(name: str) -> dict[str, str]:
    return architecture_environment(name)


def _manifest() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except Exception:
        commit = "unknown"
    model_keys = [
        "ASTRA_CONJECTURE_PROVIDER", "ASTRA_TRANSLATOR_PROVIDER",
        "ASTRA_REVIEWER_PROVIDER", "ASTRA_ANALYST_PROVIDER",
        "ASTRA_NAVIGATOR_PROVIDER", "ASTRA_SYNTH_PROVIDER",
        "ASTRA_CODEX_MODELS", "ASTRA_CODEX_REASONING",
        "ASTRA_CLAUDE_MODELS", "ASTRA_AGY_MODELS",
    ]
    return {
        "git_commit": commit,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "model_configuration": {
            key: os.environ.get(key, "") for key in model_keys if os.environ.get(key)
        },
    }


def _error_status(result: dict[str, Any]) -> str:
    message = str(result.get("error") or "")
    upper = message.upper()
    if "TIMEOUT" in upper:
        return "TIMEOUT"
    if "API_ERROR" in upper or result.get("phase") in {
        "conjecture", "translator", "translator_retry", "reviewer",
        "reviewer_retry", "analyst", "navigator",
    }:
        return "API_ERROR"
    return "TOOL_ERROR"


def _cycle_evidence_grade(result: dict[str, Any], correct: bool) -> str:
    if not correct:
        return "F"
    execution = result.get("execution") or {}
    guard = execution.get("guard") or {}
    review = result.get("code_review") or {}
    checks = int(guard.get("checks_total") or 0)
    if (
        review.get("status") == "APPROVED"
        and not guard.get("verdict_suspect")
        and execution.get("exit_code") == 0
        and checks >= 3
    ):
        return "A"
    if (
        review.get("status") == "APPROVED"
        and not guard.get("verdict_suspect")
        and execution.get("exit_code") == 0
    ):
        return "B"
    return "C"


def _guard_audit(case: QualityCase) -> dict[str, Any]:
    """Cheap offline diagnostic; the release benchmark always uses live review."""
    from core.verdict_guard import assess_verdict

    guard = assess_verdict(
        case.code,
        {"stdout": "VERDICT: PASS", "stderr": "", "exit_code": 0},
    )
    labels: list[str] = []
    reasons = " ".join(guard.get("reasons") or []).lower()
    if "pass incondicional" in reasons:
        labels.extend(["hardcoded_pass", "unreachable_failure"])
    observed = "REVISE" if guard.get("verdict_suspect") else "APPROVED"
    return {
        "review": {
            "status": observed,
            "reasoning": reasons or "No basic deterministic defect detected.",
            "defect_labels": sorted(set(labels)),
            "coverage": [],
        },
        "provider": "deterministic_guard",
    }


async def _run_one(
    case: QualityCase,
    *,
    configuration: str,
    oracle: str,
    repeat: int,
    audit_mode: str,
    cycle_timeout: int,
    env: dict[str, str],
) -> dict[str, Any]:
    started = time.monotonic()
    stderr_tail = ""
    if case.track == "cycle":
        result, stderr_tail = await _invoke_tool(
            case.cycle_request(oracle),
            env=env,
            timeout=cycle_timeout,
        )
        observed = (
            _error_status(result)
            if result.get("error")
            else str(result.get("status") or "TOOL_ERROR").upper()
        )
        expected = case.expected
        correct = observed == expected
        evidence_grade = _cycle_evidence_grade(result, correct)
        observed_defects: list[str] = []
    elif case.track == "validator_audit":
        if audit_mode == "guard":
            result = _guard_audit(case)
        else:
            result, stderr_tail = await _invoke_tool(
                {
                    "action": "review",
                    "objective": case.objective,
                    "conjecture": case.intuition,
                    "code": case.code,
                    "provider": env.get("ASTRA_REVIEWER_PROVIDER", "codex_cli"),
                },
                env=env,
                timeout=min(cycle_timeout, 900),
            )
        review = result.get("review") or {}
        observed = (
            _error_status(result)
            if result.get("error")
            else str(review.get("status") or "TOOL_ERROR").upper()
        )
        expected = "|".join(case.expected_review or (case.expected,))
        correct = observed in set(case.expected_review or (case.expected,))
        evidence_grade = None
        observed_defects = [
            str(item).lower() for item in review.get("defect_labels", [])
        ]
    else:
        result, stderr_tail = await _invoke_tool(
            {
                "action": "execute",
                "code": case.code,
                "oracle": oracle,
                "timeout": case.timeout,
            },
            env=env,
            timeout=case.timeout + 60,
        )
        if result.get("error"):
            observed = _error_status(result)
        elif result.get("exit_code") != 0:
            observed = "CODE_ERROR"
        else:
            observed = str(result.get("verdict") or "NO_VERDICT").upper()
        expected = case.expected
        correct = observed == expected
        evidence_grade = "A" if correct else "F"
        observed_defects = []

    duration = round(time.monotonic() - started, 3)
    return {
        "id": case.id,
        "track": case.track,
        "domain": case.domain,
        "difficulty": case.difficulty,
        "configuration": configuration,
        "oracle": "n/a" if case.track == "validator_audit" else oracle,
        "repeat": repeat,
        "expected": expected,
        "observed": observed,
        "correct": correct,
        "duration_s": duration,
        "evidence_grade": evidence_grade,
        "expected_defects": list(case.expected_defects),
        "observed_defects": observed_defects,
        "severity": str(case.metadata.get("severity") or ""),
        "stderr_tail": stderr_tail,
        "detail": _safe_detail(result),
    }


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    scientific = summary["scientific"]
    audit = summary["audit"]
    execution = summary["execution"]
    lines = [
        "# ASTRA Quality Benchmark v1",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Created: {report['created']}",
        f"- Tier: `{report['settings']['tier']}`",
        f"- Configurations: {', '.join(report['settings']['configurations'])}",
        f"- Oracles: {', '.join(report['settings']['oracles'])}",
        f"- Recorded runs: {summary['runs']}",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Scientific strict accuracy | {scientific['strict_accuracy']} |",
        f"| Scientific balanced accuracy | {scientific['balanced_accuracy']} |",
        f"| False acceptance rate | {scientific['false_acceptance_rate']} |",
        f"| Operational failure rate | {scientific['operational_failure_rate']} |",
        f"| Validator defect recall | {audit['defect_detection_recall']} |",
        f"| Critical defect recall | {audit['critical_defect_recall']} |",
        f"| Execution verdict accuracy | {execution['verdict_accuracy']} |",
        f"| Cross-run/oracle agreement | {execution['cross_run_agreement']} |",
        f"| Latency p50 / p95 (s) | {summary['latency_s']['p50']} / {summary['latency_s']['p95']} |",
        "",
        "## Runs",
        "",
        "| Case | Track | Config | Oracle | Expected | Observed | Correct | Seconds |",
        "|---|---|---|---|---|---|---:|---:|",
    ]
    for record in report["records"]:
        lines.append(
            f"| `{record['id']}` | {record['track']} | {record['configuration']} | "
            f"{record['oracle']} | {record['expected']} | {record['observed']} | "
            f"{'yes' if record['correct'] else 'no'} | {record['duration_s']} |"
        )
    lines.extend([
        "",
        "The JSON report beside this file contains per-phase timings, reviewer labels,",
        "oracle evidence, model resolution, and sanitized error details.",
        "",
    ])
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    case_root = Path(args.case_root).resolve() if args.case_root else None
    all_cases = load_quality_cases(
        root=case_root or (ROOT / "benchmarks" / "quality"),
        include_legacy=not args.no_legacy,
    )
    tracks = _parse_tracks(args.tracks)
    only = _parse_set(args.only) if args.only else None
    selected = select_quality_cases(
        all_cases,
        tier=args.tier,
        tracks=tracks,
        only=only,
    )
    configurations = _parse_configs(args.config)
    oracles = _oracles(args.oracle)
    repeats = args.repeats if args.repeats is not None else (3 if args.tier == "release" else 1)

    if args.list:
        print(json.dumps({
            "summary": quality_summary(selected),
            "cases": [
                {
                    "id": case.id,
                    "track": case.track,
                    "domain": case.domain,
                    "expected": case.expected,
                    "tags": list(case.tags),
                }
                for case in selected
            ],
        }, indent=2))
        return 0

    matrix = []
    for configuration in configurations:
        for case in selected:
            case_oracles = ["local"] if case.track == "validator_audit" else oracles
            for oracle in case_oracles:
                for repeat in range(1, repeats + 1):
                    matrix.append((case, configuration, oracle, repeat))

    print("ASTRA Quality Benchmark v1")
    print(
        f"tier={args.tier} cases={len(selected)} scheduled_runs={len(matrix)} "
        f"repeats={repeats} jobs={args.jobs} cycle_jobs={args.cycle_jobs}"
    )
    if args.dry_run:
        for case, config, oracle, repeat in matrix:
            print(f"{case.track:17} {case.id:52} {config:12} {oracle:7} r{repeat}")
        return 0

    overall_sem = asyncio.Semaphore(max(1, args.jobs))
    cycle_sem = asyncio.Semaphore(max(1, args.cycle_jobs))

    async def scheduled(item):
        case, configuration, oracle, repeat = item
        async with overall_sem:
            if case.track == "cycle":
                async with cycle_sem:
                    record = await _run_one(
                        case,
                        configuration=configuration,
                        oracle=oracle,
                        repeat=repeat,
                        audit_mode=args.audit_mode,
                        cycle_timeout=args.cycle_timeout,
                        env=_configuration_env(configuration),
                    )
            else:
                record = await _run_one(
                    case,
                    configuration=configuration,
                    oracle=oracle,
                    repeat=repeat,
                    audit_mode=args.audit_mode,
                    cycle_timeout=args.cycle_timeout,
                    env=_configuration_env(configuration),
                )
            tag = "PASS" if record["correct"] else "FAIL"
            print(
                f"[{tag}] {record['id']} config={configuration} "
                f"oracle={record['oracle']} observed={record['observed']} "
                f"{record['duration_s']}s"
            )
            return record

    records = await asyncio.gather(*(scheduled(item) for item in matrix))
    created = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    run_id = dt.datetime.now().strftime("quality_%Y%m%d_%H%M%S")
    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created": created,
        "settings": {
            "tier": args.tier,
            "tracks": sorted(tracks),
            "configurations": configurations,
            "oracles": oracles,
            "repeats": repeats,
            "jobs": args.jobs,
            "cycle_jobs": args.cycle_jobs,
            "audit_mode": args.audit_mode,
        },
        "manifest": _manifest(),
        "summary": summarize_records(records),
        "records": records,
    }
    out_dir = ROOT / "workspace" / "quality_benchmark_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    md_path = out_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")

    # Infrastructure failures are visible in metrics but do not erase the report.
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ASTRA Quality Benchmark v1")
    result.add_argument("--tier", choices=["smoke", "standard", "release"], default="smoke")
    result.add_argument(
        "--tracks",
        default="cycle,validator_audit,execution",
        help="Comma-separated: cycle, validator_audit, execution",
    )
    result.add_argument("--only", default="", help="Comma-separated case ids")
    result.add_argument(
        "--case-root",
        default="",
        help="Alternative quality-case root (use with --no-legacy for a hidden holdout)",
    )
    result.add_argument("--no-legacy", action="store_true")
    result.add_argument(
        "--config",
        default="full",
        help="full,no-review,no-ensemble,codex-only,claude-only,agy-only",
    )
    result.add_argument("--oracle", choices=["local", "astrum", "auto", "both"], default="local")
    result.add_argument("--repeats", type=int)
    result.add_argument("--jobs", type=int, default=4)
    result.add_argument("--cycle-jobs", type=int, default=1)
    result.add_argument("--cycle-timeout", type=int, default=2400)
    result.add_argument("--audit-mode", choices=["live", "guard"], default="live")
    result.add_argument("--list", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parser().parse_args())))
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
