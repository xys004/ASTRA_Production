"""Run a checkpointed public-benchmark comparison across ASTRA architectures."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.architecture_configs import ARCHITECTURE_ROLES, architecture_roles
from core.diversity_metrics import (
    OPERATIONAL_STATUSES,
    compute_diversity_metrics,
    paired_architecture_summary,
)
from core.external_benchmarks import audit_external_sources, load_external_cases
from core.preflight import load_project_env
from scripts.run_external_benchmarks import (
    _ainstein_pilot,
    _frontier_evaluation,
    _frontier_pilot,
    _minif2f_pilot,
    _scicode_pilot,
)


DEFAULT_SUITE = ROOT / "benchmarks" / "external" / "comparison_calibration_v1.json"
OUTPUT_ROOT = ROOT / "workspace" / "external_comparison_runs"


def _csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(
        ordered[lower] * (1 - fraction) + ordered[upper] * fraction,
        3,
    )


def _archive_and_reset(record: dict[str, Any]) -> None:
    record.setdefault("prior_attempts", []).append(
        {
            key: record.get(key)
            for key in (
                "status",
                "duration_s",
                "effective_models",
                "diversity",
                "report",
                "error",
                "started",
                "finished",
            )
        }
    )
    for key in (
        "status",
        "duration_s",
        "effective_models",
        "diversity",
        "report",
        "error",
        "started",
        "finished",
    ):
        record.pop(key, None)
    record["state"] = "pending"


def _migrate_frontier_abstention(record: dict[str, Any]) -> bool:
    if (
        record.get("benchmark") != "frontierscience"
        or record.get("state") != "complete"
        or str(record.get("status") or "").upper() != "TOOL_ERROR"
    ):
        return False
    item_report = record.get("report") or {}
    evaluation = _frontier_evaluation(
        str(item_report.get("candidate") or ""),
        str(item_report.get("reference") or ""),
        item_report.get("cycle") or {},
    )
    if evaluation.get("status") != "ABSTAIN":
        return False
    item_report["evaluation"] = evaluation
    record["status"] = "ABSTAIN"
    return True


def _effective_models(report: dict[str, Any]) -> list[str]:
    values = list((report.get("models") or {}).values())
    cycle_models = ((report.get("cycle") or {}).get("cli_models") or {}).values()
    values.extend(cycle_models)
    return sorted({str(value) for value in values if str(value).strip()})


def _primary_models() -> dict[str, str]:
    keys = {
        "codex_cli": "ASTRA_CODEX_MODELS",
        "claude_cli": "ASTRA_CLAUDE_MODELS",
        "agy_cli": "ASTRA_AGY_MODELS",
    }
    return {
        provider: _csv(os.environ.get(env_key, ""))[0]
        for provider, env_key in keys.items()
        if _csv(os.environ.get(env_key, ""))
    }


def _expected_models(
    configuration: str,
    primary_models: dict[str, str],
) -> list[str]:
    roles = architecture_roles(configuration)
    providers = set(roles["proposers"])
    providers.update(
        roles[key]
        for key in ("synthesizer", "author", "reviewer", "repairer")
    )
    return sorted(
        primary_models[provider]
        for provider in providers
        if provider in primary_models
    )


def _native_result(record: dict[str, Any]) -> str:
    evaluation = (record.get("report") or {}).get("evaluation") or {}
    status = str(evaluation.get("status") or record.get("status") or "UNKNOWN")
    if evaluation.get("resolve_points") is not None:
        return (
            f"{status}; {evaluation['resolve_points']} pts; "
            f"{evaluation.get('passed_count', 0)}/"
            f"{evaluation.get('passed_count', 0) + evaluation.get('failed_count', 0)} tests"
        )
    if evaluation.get("tests") is not None:
        return f"{status}; {evaluation['tests']} official tests"
    if evaluation.get("method"):
        return f"{status}; {evaluation['method']}"
    return status


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", r"\|")


def _summarize(
    records: list[dict[str, Any]],
    configurations: list[str],
    primary_models: dict[str, str],
) -> dict[str, Any]:
    by_configuration: dict[str, Any] = {}
    for configuration in configurations:
        cells = [item for item in records if item["configuration"] == configuration]
        completed = [item for item in cells if item["state"] == "complete"]
        scored = [
            item
            for item in completed
            if str(item.get("status") or "").upper() not in OPERATIONAL_STATUSES
        ]
        operational_errors = [
            item for item in completed if item not in scored
        ]
        durations = [float(item["duration_s"]) for item in scored]
        passed = sum(item.get("status") == "PASS" for item in scored)
        models = sorted(
            {
                model
                for item in completed
                for model in item.get("effective_models", [])
            }
        )
        expected_models = _expected_models(configuration, primary_models)
        primary_compliant = sum(
            item.get("effective_models") == expected_models
            for item in completed
        )
        diversity_scores = [
            float(value)
            for item in scored
            if (
                value := (item.get("diversity") or {}).get(
                    "perspective_diversity_score"
                )
            )
            is not None
        ]
        reviewed = [
            item
            for item in scored
            if (item.get("diversity") or {}).get("review_status")
        ]
        review_interventions = sum(
            bool((item.get("diversity") or {}).get("review_intervened"))
            for item in reviewed
        )
        by_configuration[configuration] = {
            "scheduled": len(cells),
            "completed": len(completed),
            "scored": len(scored),
            "operational_errors": len(operational_errors),
            "passed": passed,
            "pass_rate": round(passed / len(scored), 4) if scored else None,
            "latency_s": {
                "p50": _percentile(durations, 0.5),
                "p95": _percentile(durations, 0.95),
                "total": round(sum(durations), 3),
            },
            "effective_models": models,
            "expected_primary_models": expected_models,
            "primary_model_compliant_cells": primary_compliant,
            "diversity_process": {
                "measured_cells": len(diversity_scores),
                "mean_perspective_diversity_score": (
                    round(sum(diversity_scores) / len(diversity_scores), 4)
                    if diversity_scores
                    else None
                ),
                "reviewed_cells": len(reviewed),
                "review_interventions": review_interventions,
                "review_intervention_rate": (
                    round(review_interventions / len(reviewed), 4)
                    if reviewed
                    else None
                ),
                "repair_lifts": sum(
                    bool((item.get("diversity") or {}).get("repair_lift"))
                    for item in scored
                ),
            },
        }
    summary = {
        "scheduled_cells": len(records),
        "completed_cells": sum(item["state"] == "complete" for item in records),
        "scored_cells": sum(
            item["state"] == "complete"
            and str(item.get("status") or "").upper() not in OPERATIONAL_STATUSES
            for item in records
        ),
        "operational_error_cells": sum(
            item["state"] == "complete"
            and str(item.get("status") or "").upper() in OPERATIONAL_STATUSES
            for item in records
        ),
        "passing_cells": sum(item.get("status") == "PASS" for item in records),
        "by_configuration": by_configuration,
    }
    paired = paired_architecture_summary(records)
    if paired:
        summary["paired_diversity_test"] = paired
    return summary


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    suite_id = report["suite"].get("suite_id", "comparison")
    lines = [
        f"# ASTRA Public Benchmark Comparison — {suite_id}",
        "",
        f"- Run: `{report['run_id']}`",
        f"- State: `{report['state']}`",
        f"- Source commit: `{report['manifest']['astra_git_commit']}`",
        "- Protocol: equal phase topology; two independent proposals, synthesis, "
        "artifact authoring, independent review, native evaluator.",
        "",
        "## Architecture summary",
        "",
        "| Configuration | Completed | Scored | Passed | Pass rate | Operational errors | P50 (s) | P95 (s) | Effective models |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, item in summary["by_configuration"].items():
        rate = "—" if item["pass_rate"] is None else f"{100 * item['pass_rate']:.1f}%"
        expected = item["expected_primary_models"]
        effective = item["effective_models"]
        models = ", ".join(effective) or "—"
        if effective and effective != expected:
            models += " (fallback/mismatch)"
        lines.append(
            f"| `{name}` | {item['completed']}/{item['scheduled']} | "
            f"{item['scored']} | {item['passed']} | {rate} | "
            f"{item['operational_errors']} | {item['latency_s']['p50']} | "
            f"{item['latency_s']['p95']} | {models} |"
        )
    paired = summary.get("paired_diversity_test")
    if paired:
        ci = paired.get("pass_rate_delta_bootstrap_95") or ["—", "—"]
        diversity = paired.get("mean_perspective_diversity") or {}
        lines.extend(
            [
                "",
                "## Preregistered paired diversity test",
                "",
                f"- Scored pairs: {paired['paired_scored_cases']}",
                f"- Diverse wins / control wins / ties: "
                f"{paired['diverse_wins']} / {paired['control_wins']} / "
                f"{paired['ties']}",
                f"- Paired pass-rate delta: {paired['pass_rate_delta']:+.4f} "
                f"(bootstrap 95% [{ci[0]}, {ci[1]}])",
                f"- Exact McNemar p (one-sided / two-sided): "
                f"{paired['mcnemar_exact_one_sided_p']} / "
                f"{paired['mcnemar_exact_two_sided_p']}",
                f"- Mean perspective-diversity score: "
                f"`{paired['diverse_configuration']}`="
                f"{diversity.get(paired['diverse_configuration'])}; "
                f"`{paired['control_configuration']}`="
                f"{diversity.get(paired['control_configuration'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Native benchmark cells",
            "",
            "| Benchmark | Case | Configuration | Native result | Seconds |",
            "|---|---|---|---|---:|",
        ]
    )
    for record in report["records"]:
        result = _native_result(record) if record["state"] == "complete" else record["state"]
        expected = _expected_models(
            record["configuration"],
            report["manifest"].get("primary_models", {}),
        )
        if (
            record["state"] == "complete"
            and str(record.get("status") or "").upper()
            not in OPERATIONAL_STATUSES
            and record.get("effective_models", []) != expected
        ):
            result += "; non-primary model"
        lines.append(
            f"| {record['benchmark']} | `{record['case_id']}` | "
            f"`{record['configuration']}` | {_markdown_cell(result)} | "
            f"{record.get('duration_s', '—')} |"
        )
    lines.extend(
        [
            "",
            "Pass rates and latency percentiles exclude operational-error cells;",
            "`NEEDS_EXPERT` remains a scored non-pass result.",
            "",
            "Native metrics are deliberately not collapsed into one synthetic score.",
            (
                "This suite was frozen before execution; case substitutions are "
                "not allowed."
                if report["suite"].get("frozen")
                else
                "This calibration run is not a statistically powered model ranking."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _write_checkpoint(report: dict[str, Any], target: Path) -> None:
    report["summary"] = _summarize(
        report["records"],
        report["settings"]["configurations"],
        report["manifest"].get("primary_models", {}),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    target.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")


def _load_suite(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0" or not data.get("cases"):
        raise ValueError(f"Invalid comparison suite: {path}")
    return data


def _scheduled_pairs(
    suite: dict[str, Any],
    specs: list[dict[str, Any]],
    configurations: list[str],
) -> list[tuple[dict[str, Any], str]]:
    spec_by_id = {item["id"]: item for item in specs}
    expected = {
        (case_id, configuration)
        for case_id in spec_by_id
        for configuration in configurations
    }
    schedule = suite.get("execution_schedule")
    if not schedule:
        return [
            (spec, configuration)
            for spec in specs
            for configuration in configurations
        ]
    ordered = [
        (spec_by_id[str(item["case_id"])], str(item["configuration"]))
        for item in schedule
        if str(item.get("case_id")) in spec_by_id
        and str(item.get("configuration")) in configurations
    ]
    actual = {(spec["id"], configuration) for spec, configuration in ordered}
    if actual != expected or len(ordered) != len(expected):
        raise ValueError(
            "Frozen execution schedule does not cover every selected "
            "case/configuration exactly once"
        )
    return ordered


def _case_catalog() -> dict[str, Any]:
    return {case.id: case for case in load_external_cases("all")}


async def _run_cell(
    spec: dict[str, Any],
    case: Any,
    configuration: str,
    *,
    oracle: str,
    timeout: int,
) -> dict[str, Any]:
    pilot = spec["pilot"]
    if pilot == "scicode":
        return await _scicode_pilot(case, timeout, configuration)
    if pilot == "minif2f":
        return await _minif2f_pilot(case, timeout, configuration)
    if pilot == "frontier":
        return await _frontier_pilot(
            case,
            oracle=oracle,
            timeout=timeout,
            configuration=configuration,
        )
    if pilot == "ainstein":
        return await _ainstein_pilot(case, timeout, configuration)
    raise ValueError(f"Unknown pilot: {pilot}")


async def run(args: argparse.Namespace) -> int:
    load_project_env()
    if args.strict_primary_models:
        for env_key in (
            "ASTRA_CODEX_MODELS",
            "ASTRA_CLAUDE_MODELS",
            "ASTRA_AGY_MODELS",
        ):
            candidates = _csv(os.environ.get(env_key, ""))
            if candidates:
                os.environ[env_key] = candidates[0]
    audit = audit_external_sources()
    if not audit["ok"]:
        raise ValueError("External sources are not at their pinned revisions")

    suite_path = Path(args.suite).resolve()
    suite = _load_suite(suite_path)
    requested_configurations = _csv(args.config)
    configurations = requested_configurations or list(suite["configurations"])
    unknown = set(configurations) - set(ARCHITECTURE_ROLES)
    if unknown:
        raise ValueError(f"Unknown configurations: {sorted(unknown)}")
    selected_ids = set(_csv(args.only))
    specs = [
        item for item in suite["cases"]
        if not selected_ids or item["id"] in selected_ids
    ]
    if selected_ids - {item["id"] for item in specs}:
        raise ValueError(
            f"Unknown suite cases: {sorted(selected_ids - {item['id'] for item in specs})}"
        )
    catalog = _case_catalog()
    missing = [item["id"] for item in specs if item["id"] not in catalog]
    if missing:
        raise ValueError(f"Cases missing from pinned external catalog: {missing}")

    if args.resume:
        target = Path(args.resume).resolve()
        report = json.loads(target.read_text(encoding="utf-8"))
        scheduled_configurations = report["settings"]["configurations"]
        if requested_configurations:
            unscheduled = set(requested_configurations) - set(
                scheduled_configurations
            )
            if unscheduled:
                raise ValueError(
                    "Resume configurations were not scheduled in the checkpoint: "
                    f"{sorted(unscheduled)}"
                )
            active_configurations = requested_configurations
        else:
            active_configurations = list(scheduled_configurations)
        scheduled_case_ids = set(report["settings"]["case_ids"])
        requested_case_ids = {item["id"] for item in specs}
        if selected_ids:
            unscheduled_cases = requested_case_ids - scheduled_case_ids
            if unscheduled_cases:
                raise ValueError(
                    "Resume cases were not scheduled in the checkpoint: "
                    f"{sorted(unscheduled_cases)}"
                )
            active_case_ids = requested_case_ids
        else:
            active_case_ids = scheduled_case_ids
        report["manifest"].setdefault("primary_models", _primary_models())
        for record in report["records"]:
            _migrate_frontier_abstention(record)
            if (
                record.get("state") == "complete"
                and record.get("report")
                and "diversity" not in record
            ):
                record["diversity"] = compute_diversity_metrics(
                    record["report"]
                )
        if args.rerun_nonprimary:
            primary = report["manifest"]["primary_models"]
            for record in report["records"]:
                if (
                    record["configuration"] not in active_configurations
                    or record["case_id"] not in active_case_ids
                ):
                    continue
                expected = _expected_models(record["configuration"], primary)
                if (
                    record.get("state") == "complete"
                    and record.get("effective_models", []) != expected
                ):
                    _archive_and_reset(record)
        if args.rerun_operational:
            for record in report["records"]:
                if (
                    record["configuration"] not in active_configurations
                    or record["case_id"] not in active_case_ids
                ):
                    continue
                if (
                    record.get("state") == "complete"
                    and str(record.get("status") or "").upper()
                    in OPERATIONAL_STATUSES
                ):
                    _archive_and_reset(record)
        if args.rerun_completed:
            for record in report["records"]:
                if (
                    record["configuration"] in active_configurations
                    and record["case_id"] in active_case_ids
                    and record.get("state") == "complete"
                ):
                    _archive_and_reset(record)
        report["settings"]["strict_primary_models"] = bool(
            args.strict_primary_models
        )
        report["settings"]["active_resume_configurations"] = (
            active_configurations
        )
        report["settings"]["active_resume_case_ids"] = sorted(active_case_ids)
        if not args.dry_run:
            report["state"] = "running"
        _write_checkpoint(report, target)
    else:
        active_configurations = configurations
        active_case_ids = {item["id"] for item in specs}
        run_id = dt.datetime.now().strftime("external_comparison_%Y%m%d_%H%M%S")
        target = OUTPUT_ROOT / f"{run_id}.json"
        scheduled_pairs = _scheduled_pairs(suite, specs, configurations)
        records = [
            {
                "benchmark": spec["benchmark"],
                "case_id": spec["id"],
                "pilot": spec["pilot"],
                "native_metric": spec["native_metric"],
                "configuration": configuration,
                "architecture": architecture_roles(configuration),
                "state": "pending",
            }
            for spec, configuration in scheduled_pairs
        ]
        report = {
            "schema_version": "1.0",
            "run_id": run_id,
            "state": "paused" if args.dry_run else "running",
            "created": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
            "suite": suite,
            "settings": {
                "configurations": configurations,
                "oracle": args.oracle,
                "timeout_s": args.timeout,
                "cell_timeout_s": args.cell_timeout,
                "equal_phase_topology": True,
                "strict_primary_models": bool(args.strict_primary_models),
                "case_ids": [item["id"] for item in specs],
            },
            "manifest": {
                "astra_git_commit": _git_commit(),
                "external_source_fingerprint": audit.get("fingerprint"),
                "python": sys.version.split()[0],
                "primary_models": _primary_models(),
            },
            "records": records,
            "summary": {},
        }
        _write_checkpoint(report, target)

    pending = [
        item
        for item in report["records"]
        if item["state"] != "complete"
        and item["configuration"] in active_configurations
        and item["case_id"] in active_case_ids
    ]
    remaining = [
        item for item in report["records"] if item["state"] != "complete"
    ]
    print(
        f"run={report['run_id']} cells={len(report['records'])} "
        f"active_pending={len(pending)} total_pending={len(remaining)} "
        f"checkpoint={target}",
        flush=True,
    )
    if args.dry_run:
        for item in pending:
            print(
                f"{item['benchmark']:16} {item['case_id']:58} "
                f"{item['configuration']}",
                flush=True,
            )
        return 0

    spec_by_id = {item["id"]: item for item in specs}
    for record in report["records"]:
        if (
            record["state"] == "complete"
            or record["configuration"] not in active_configurations
            or record["case_id"] not in active_case_ids
        ):
            continue
        spec = spec_by_id[record["case_id"]]
        case = catalog[record["case_id"]]
        record["state"] = "running"
        record["started"] = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
        _write_checkpoint(report, target)
        print(
            f"[RUN] {record['benchmark']} {record['case_id']} "
            f"config={record['configuration']}",
            flush=True,
        )
        started = time.monotonic()
        try:
            cell_report = await asyncio.wait_for(
                _run_cell(
                    spec,
                    case,
                    record["configuration"],
                    oracle=args.oracle,
                    timeout=args.timeout,
                ),
                timeout=args.cell_timeout,
            )
            evaluation = cell_report.get("evaluation") or {}
            record["status"] = str(evaluation.get("status") or "TOOL_ERROR").upper()
            record["report"] = cell_report
            record["effective_models"] = _effective_models(cell_report)
            record["diversity"] = compute_diversity_metrics(cell_report)
            record["error"] = None
        except asyncio.TimeoutError:
            record["status"] = "TIMEOUT"
            record["report"] = {}
            record["effective_models"] = []
            record["error"] = f"Cell timeout after {args.cell_timeout}s"
        except Exception as exc:
            record["status"] = "TOOL_ERROR"
            record["report"] = {}
            record["effective_models"] = []
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["finished"] = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
        record["state"] = "complete"
        _write_checkpoint(report, target)
        print(
            f"[{record['status']}] {record['case_id']} "
            f"config={record['configuration']} {record['duration_s']}s",
            flush=True,
        )

    remaining = [
        item for item in report["records"] if item["state"] != "complete"
    ]
    if remaining:
        report["state"] = "paused"
        report.pop("finished", None)
    else:
        report["state"] = "complete"
        report["finished"] = (
            dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
        )
    _write_checkpoint(report, target)
    print(json.dumps({"report": str(target), "summary": report["summary"]}, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Checkpointed ASTRA comparison on pinned public benchmarks"
    )
    result.add_argument("--suite", default=str(DEFAULT_SUITE))
    result.add_argument("--config", default="")
    result.add_argument("--only", default="")
    result.add_argument("--oracle", choices=["astrum", "auto"], default="astrum")
    result.add_argument("--timeout", type=int, default=2400)
    result.add_argument("--cell-timeout", type=int, default=3600)
    result.add_argument("--resume", default="")
    result.add_argument("--strict-primary-models", action="store_true")
    result.add_argument("--rerun-nonprimary", action="store_true")
    result.add_argument("--rerun-operational", action="store_true")
    result.add_argument("--rerun-completed", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parser().parse_args())))
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
