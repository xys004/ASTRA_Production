#!/usr/bin/env python3
"""Run ASTRA Research Trajectory Benchmark v1.

Each cell receives one human-authored research brief.  Reflective configurations
choose later directions from ASTRA's own navigator output; ``full-linear`` runs
the same production role map and phase-call topology but follows frozen
directions that cannot react to prior evidence.

The runner is intentionally sequential.  Model CLIs remain local and
subscription-bound, while compute-heavy validators can use the ASTRUM oracle.
Every completed cycle is checkpointed and can be resumed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.architecture_configs import architecture_environment, architecture_roles
from core.preflight import load_project_env
from core.research_programs import (
    DEFAULT_SUITE,
    ResearchProgram,
    load_research_suite,
    select_research_programs,
    suite_fingerprint,
)
from core.research_trajectory_metrics import (
    OPERATIONAL_STATUSES,
    blank_expert_scorecard,
    build_research_graph,
    compute_trajectory_metrics,
    stable_blind_id,
    summarize_trajectory_records,
)


OUTPUT_ROOT = ROOT / "workspace" / "research_trajectory_runs"
ASTRA_TOOL = ROOT / "astra_tool.py"
CONFIGURATIONS = {
    "full": {"architecture": "full", "policy": "reflective"},
    # Explicit profile for the 2026-07-31 quota optimization.  It is opt-in so
    # the frozen public pilot remains unchanged while paired canaries can compare
    # the exact production optimization against ``full``.
    "quota-optimized": {
        "architecture": "no-ensemble",
        "policy": "reflective",
        "environment": {
            "ASTRA_TRANSLATOR_MODELS": "sonnet,claude-opus-4-8",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "2",
        },
    },
    "full-vnext": {
        "architecture": "full",
        "policy": "reflective",
        "environment": {
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
        },
    },
    # Explicit alias used in before/after reports so the algorithmic version is
    # unambiguous. ``full-vnext`` always points to the current production repair.
    "full-vnext1": {
        "architecture": "full",
        "policy": "reflective",
        "environment": {
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "local-patch",
            "ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS": "1",
        },
    },
    "full-vnext0": {
        "architecture": "full",
        "policy": "reflective",
        "environment": {
            "ASTRA_VALIDATOR_REPAIR_VNEXT": "1",
            "ASTRA_VALIDATOR_REPAIR_STRATEGY": "legacy",
            "ASTRA_VNEXT_REVIEW_MAX_REVISIONS": "2",
        },
    },
    "homogeneous-proposers": {
        "architecture": "homogeneous-proposers",
        "policy": "reflective",
    },
    "codex-only": {"architecture": "codex-only", "policy": "reflective"},
    "full-linear": {"architecture": "full", "policy": "linear"},
}


def _csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _frozen_resource_context(program: ResearchProgram) -> str:
    """Embed declared benchmark resources for tool-disabled model phases.

    The CLIs are intentionally denied filesystem tools, so a path alone is not
    evidence available to the conjecturer or translator.  Every architecture
    receives the same bounded, hashed resource bytes through its prompt.
    """
    if not program.resources:
        return ""
    blocks = [
        "FROZEN RESOURCE CONTENTS (authoritative benchmark inputs):",
        "Use these exact values. Do not attempt to inspect files with tools.",
    ]
    root = ROOT.resolve()
    for resource in program.resources:
        path = (ROOT / resource).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"Frozen resource escapes ASTRA root: {resource}"
            ) from exc
        payload = path.read_bytes()
        if len(payload) > 16000:
            raise ValueError(
                f"Frozen resource exceeds 16,000-byte prompt limit: {resource}"
            )
        digest = hashlib.sha256(payload).hexdigest()
        text = payload.decode("utf-8")
        blocks.extend(
            [
                "",
                f"RESOURCE: {resource}",
                f"SHA256: {digest}",
                "```text",
                text.rstrip(),
                "```",
            ]
        )
    return "\n".join(blocks)


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


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _last_json(stdout: str) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for line in stdout.splitlines():
        try:
            value = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            last = value
    if last is not None:
        return last

    decoder = json.JSONDecoder()
    largest_span = -1
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and end > largest_span:
            last = value
            largest_span = end
    if last is None:
        raise ValueError("ASTRA subprocess emitted no JSON object")
    return last


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


def _strict_primary_environment(env: dict[str, str]) -> dict[str, str]:
    result = dict(env)
    for key in ("ASTRA_CODEX_MODELS", "ASTRA_CLAUDE_MODELS", "ASTRA_AGY_MODELS"):
        candidates = _csv(result.get(key, ""))
        if candidates:
            result[key] = candidates[0]
    return result


def schedule_cells(
    programs: list[ResearchProgram],
    configurations: list[str],
    seeds: list[int],
) -> list[tuple[ResearchProgram, str, int]]:
    """Rotate within each case/seed block to balance temporal first position."""
    scheduled: list[tuple[ResearchProgram, str, int]] = []
    block_index = 0
    for program in programs:
        for seed in seeds:
            offset = block_index % len(configurations)
            order = configurations[offset:] + configurations[:offset]
            scheduled.extend((program, configuration, seed) for configuration in order)
            block_index += 1
    return scheduled


def _new_record(
    *,
    run_id: str,
    program: ResearchProgram,
    configuration: str,
    seed: int,
) -> dict[str, Any]:
    spec = CONFIGURATIONS[configuration]
    return {
        "case_id": program.id,
        "case_title": program.title,
        "domain": program.domain,
        "configuration": configuration,
        "architecture": architecture_roles(spec["architecture"]),
        "trajectory_policy": spec["policy"],
        "seed": seed,
        "blind_id": stable_blind_id(run_id, program.id, configuration, seed),
        "seed_blind_id": stable_blind_id(run_id, program.id, seed),
        "state": "pending",
        "objective": program.research_brief(),
        "human_interventions": program.budget.human_interventions,
        "budget": program.budget.to_dict(),
        "cycles": [],
        "metrics": {},
    }


def _thread_summary(record: dict[str, Any]) -> str:
    lines = [
        f"Research program: {record['case_id']}",
        f"Completed autonomous cycles: {len(record.get('cycles') or [])}",
    ]
    for cycle in (record.get("cycles") or [])[-6:]:
        result = cycle.get("result") or {}
        lines.append(
            "Cycle {cycle} [{status}] direction={direction}; hypothesis={hypothesis}; "
            "assessment={assessment}".format(
                cycle=cycle.get("cycle"),
                status=_status(result),
                direction=str(cycle.get("direction") or "")[:180],
                hypothesis=str(result.get("conjecture") or "")[:220],
                assessment=str((result.get("analysis") or {}).get("reasoning") or "")[:180],
            )
        )
    return "\n".join(lines)


def _axiomatic_memory(record: dict[str, Any], max_chars: int = 14000) -> str:
    entries = []
    for cycle in record.get("cycles") or []:
        result = cycle.get("result") or {}
        status = _status(result)
        if status not in {"VALIDATED", "REFUTED"}:
            continue
        entries.append(
            "[{status} cycle {cycle}]\nHypothesis: {hypothesis}\nEvidence assessment: "
            "{assessment}".format(
                status=status,
                cycle=cycle.get("cycle"),
                hypothesis=str(result.get("conjecture") or "")[:1200],
                assessment=str((result.get("analysis") or {}).get("reasoning") or "")[:1000],
            )
        )
    memory = "\n\n".join(entries)
    return memory[-max_chars:]


def _next_direction(
    program: ResearchProgram,
    record: dict[str, Any],
    cycle_index: int,
) -> str:
    if record["trajectory_policy"] == "linear":
        if cycle_index == 1:
            return program.research_brief()
        return program.linear_control_directions[cycle_index - 2]
    cycles = record.get("cycles") or []
    if not cycles:
        return program.research_brief()
    last = cycles[-1].get("result") or {}
    navigation = last.get("navigation") or {}
    direction = str(navigation.get("next_direction") or "").strip()
    if direction:
        return direction
    status = _status(last)
    return (
        f"Continue the research program after an operationally incomplete {status} "
        "cycle. Diagnose the missing evidence, choose a narrower falsifiable next "
        "step, and do not repeat the prior conjecture."
    )


def _run_cycle(
    *,
    program: ResearchProgram,
    record: dict[str, Any],
    direction: str,
    oracle: str,
    strict_primary_models: bool,
) -> tuple[dict[str, Any], float, str]:
    spec = CONFIGURATIONS[record["configuration"]]
    env = architecture_environment(spec["architecture"], base=dict(os.environ))
    env["ASTRA_CYCLE_CACHE"] = "0"
    env["ASTRA_NAVIGATE_AFTER_CYCLE"] = "1"
    env["ASTRA_BENCHMARK_SEED"] = str(record["seed"])
    env.update(
        {
            str(key): str(value)
            for key, value in dict(spec.get("environment") or {}).items()
        }
    )
    if strict_primary_models:
        env = _strict_primary_environment(env)
    shared_objective = program.research_brief()
    resource_context = _frozen_resource_context(program)
    if resource_context:
        shared_objective += "\n\n" + resource_context
    request = {
        "action": "cycle",
        "objective": shared_objective,
        "intuition": direction,
        "axiomatic_base": _axiomatic_memory(record),
        "thread_summary": _thread_summary(record),
        "cycles_since_milestone": len(record.get("cycles") or []) + 1,
        "oracle": oracle,
        "exec_timeout": program.budget.execution_timeout_seconds,
        "benchmark_seed": record["seed"],
    }
    started = time.monotonic()
    raw_output = ""
    try:
        process = subprocess.run(
            [sys.executable, str(ASTRA_TOOL)],
            cwd=ROOT,
            env=env,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=program.budget.cycle_timeout_seconds,
            check=False,
        )
        raw_output = process.stdout
        result = _last_json(process.stdout)
        if process.stderr.strip():
            result.setdefault("runner_warnings", []).append(process.stderr[-3000:])
        result["subprocess_returncode"] = process.returncode
    except subprocess.TimeoutExpired as exc:
        raw_output = str(exc.stdout or "")
        result = {
            "status": "TIMEOUT",
            "error": (
                "Research cycle exceeded the frozen timeout of "
                f"{program.budget.cycle_timeout_seconds} seconds"
            ),
            "phase": "runner_timeout",
        }
    except Exception as exc:
        result = {
            "status": "TOOL_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "phase": "runner",
        }
    return result, round(time.monotonic() - started, 3), raw_output


def _artifact_suffix(result: dict[str, Any]) -> str:
    engine = str((result.get("execution") or {}).get("engine") or "").lower()
    if not engine:
        code = str(result.get("code") or "")
        marker = "# ASTRA_ENGINE:"
        for line in code.splitlines()[:20]:
            if line.strip().upper().startswith(marker):
                engine = line.split(":", 1)[1].strip().lower()
                break
    return {
        "lean": ".lean",
        "lean4": ".lean",
        "maxima": ".mac",
        "sage": ".sage",
        "cadabra": ".cdb",
        "wolfram": ".wl",
        "mathematica": ".wl",
    }.get(engine, ".py")


def _write_cycle_artifacts(
    cell_dir: Path,
    cycle: dict[str, Any],
    raw_output: str,
) -> None:
    cycle_dir = cell_dir / f"cycle_{int(cycle['cycle']):03d}"
    result = cycle.get("result") or {}
    execution = result.get("execution") or {}
    _write_json(cycle_dir / "cycle.json", cycle)
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / f"validator{_artifact_suffix(result)}").write_text(
        str(result.get("code") or ""),
        encoding="utf-8",
    )
    (cycle_dir / "stdout.txt").write_text(
        str(execution.get("stdout") or ""),
        encoding="utf-8",
    )
    (cycle_dir / "stderr.txt").write_text(
        str(execution.get("stderr") or ""),
        encoding="utf-8",
    )
    (cycle_dir / "subprocess_stdout.txt").write_text(
        raw_output,
        encoding="utf-8",
    )


def _render_cell_markdown(
    record: dict[str, Any],
    graph: dict[str, Any],
) -> str:
    metrics = record.get("metrics") or {}
    lines = [
        "# ASTRA Research Trajectory",
        "",
        f"- Blind ID: `{record['blind_id']}`",
        f"- Case: `{record['case_id']}`",
        f"- State: `{record['state']}`",
        f"- Autonomous cycles: {len(record.get('cycles') or [])}",
        f"- Human interventions: {record['human_interventions']}",
        "",
        "## Research objective",
        "",
        record["objective"],
        "",
        "## Automatic process profile",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for name in (
        "human_prompt_efficiency",
        "autonomous_loop_yield",
        "independent_evidence_rate",
        "recovery_rate_after_negative_evidence",
        "operational_failure_rate",
        "estimated_model_calls",
        "wall_time_seconds",
    ):
        lines.append(f"| {name} | {metrics.get(name)} |")
    lines.extend(["", "## Trajectory", ""])
    for cycle in record.get("cycles") or []:
        result = cycle.get("result") or {}
        lines.extend(
            [
                f"### Cycle {cycle['cycle']} — {_status(result)}",
                "",
                f"**Direction:** {cycle.get('direction', '')}",
                "",
                f"**Hypothesis:** {result.get('conjecture', '')}",
                "",
                "**Evidence assessment:** "
                + str((result.get("analysis") or {}).get("reasoning") or ""),
                "",
                "**Next direction:** "
                + str((result.get("navigation") or {}).get("next_direction") or ""),
                "",
            ]
        )
    lines.extend(
        [
            "## Graph manifest",
            "",
            f"- Nodes: {len(graph['nodes'])}",
            f"- Edges: {len(graph['edges'])}",
            "",
            "> The automatic profile measures observable process and efficiency. "
            "Scientific depth, novelty, utility, and causal uptake are assessed "
            "separately with the blinded expert scorecard.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_cell_outputs(
    run_dir: Path,
    record: dict[str, Any],
    program: ResearchProgram,
    expert_weights: dict[str, float],
) -> None:
    cell_dir = (
        run_dir
        / "cells"
        / record["case_id"]
        / record["blind_id"]
    )
    graph = build_research_graph(record)
    _write_json(cell_dir / "trajectory.json", record)
    _write_json(cell_dir / "research_graph.json", graph)
    blind_dir = cell_dir / "expert_bundle"
    blind_graph = {
        **graph,
        "nodes": [
            {key: value for key, value in node.items() if key != "providers"}
            for node in graph["nodes"]
        ],
    }
    _write_json(blind_dir / "research_graph.json", blind_graph)
    blind_dir.mkdir(parents=True, exist_ok=True)
    (blind_dir / "trajectory.md").write_text(
        _render_cell_markdown(record, blind_graph),
        encoding="utf-8",
    )
    (blind_dir / "BLINDING_README.md").write_text(
        "# Expert evaluation bundle\n\n"
        "This directory intentionally omits architecture, provider, model, and "
        "seed identities. Evaluate only the material inside this directory. "
        "Complete a separate copy of `expert_scorecard.json` for each rater, "
        "for example `expert_scorecard.rater-a.json`.\n",
        encoding="utf-8",
    )
    for cycle in record.get("cycles") or []:
        result = cycle.get("result") or {}
        execution = result.get("execution") or {}
        evidence_dir = blind_dir / "evidence" / f"cycle_{int(cycle['cycle']):03d}"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / f"validator{_artifact_suffix(result)}").write_text(
            str(result.get("code") or ""),
            encoding="utf-8",
        )
        (evidence_dir / "stdout.txt").write_text(
            str(execution.get("stdout") or ""),
            encoding="utf-8",
        )
        (evidence_dir / "stderr.txt").write_text(
            str(execution.get("stderr") or ""),
            encoding="utf-8",
        )
    scorecard_path = blind_dir / "expert_scorecard.json"
    if not scorecard_path.exists():
        _write_json(
            scorecard_path,
            blank_expert_scorecard(
                record=record,
                expert_anchors=program.expert_anchors,
                weights=expert_weights,
            ),
        )
    (cell_dir / "trajectory.md").write_text(
        _render_cell_markdown(record, graph),
        encoding="utf-8",
    )


def _write_run_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary") or {}
    lines = [
        "# ASTRA Research Trajectory Benchmark",
        "",
        f"- Run: `{report['run_id']}`",
        f"- State: `{report['state']}`",
        f"- Protocol fingerprint: `{report['manifest']['suite_fingerprint']}`",
        f"- Completed cells: {summary.get('complete_cells', 0)}",
        "",
        "## Automatic process profile by configuration",
        "",
        "| Configuration | Cells | Prompt efficiency | Loop yield | Independent evidence | Recovery | Operational failures | Model calls | Wall seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for configuration, item in (summary.get("by_configuration") or {}).items():
        lines.append(
            "| {configuration} | {cells} | {human_prompt_efficiency} | "
            "{autonomous_loop_yield} | {independent_evidence_rate} | "
            "{recovery_rate_after_negative_evidence} | {operational_failure_rate} | "
            "{estimated_model_calls} | {wall_time_seconds} |".format(
                configuration=configuration,
                **item,
            )
        )
    lines.extend(
        [
            "",
            "Automatic metrics are not a scientific-quality leaderboard. Complete "
            "the architecture-blinded expert scorecards before interpreting depth, "
            "novelty, utility, or cross-perspective causal uptake.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _checkpoint(report: dict[str, Any], path: Path) -> None:
    report["updated"] = _now()
    report["summary"] = summarize_trajectory_records(report.get("records") or [])
    _write_json(path, report)
    _write_run_markdown(report, path.with_suffix(".md"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one-objective, long-horizon ASTRA research benchmarks."
    )
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument(
        "--tier",
        choices=("canary", "pilot"),
        default="canary",
        help="Canary uses two cases, the first seed, and at most three cycles.",
    )
    parser.add_argument("--only", default="", help="Comma-separated case ids.")
    parser.add_argument("--config", default="", help="Comma-separated configurations.")
    parser.add_argument("--seeds", default="", help="Comma-separated integer seeds.")
    parser.add_argument(
        "--oracle",
        choices=("local", "astrum", "auto"),
        default="local",
    )
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--resume", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--strict-primary-models",
        action="store_true",
        help="Forbid configured fallback models by retaining only each first CLI model.",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    load_project_env()
    suite, all_programs = load_research_suite(args.suite)
    resume_report = None
    if args.resume:
        resume_path = Path(args.resume).resolve()
        resume_report = json.loads(resume_path.read_text(encoding="utf-8"))
        selected_ids = list(
            dict.fromkeys(
                str(record["case_id"])
                for record in resume_report.get("records") or []
            )
        )
        configurations = list(
            resume_report.get("settings", {}).get("configurations") or []
        )
        seeds = [
            int(value)
            for value in resume_report.get("settings", {}).get("seeds") or []
        ]
        max_cycles_override = int(
            resume_report.get("settings", {}).get("max_cycles_override") or 0
        )
    else:
        selected_ids = _csv(args.only)
        if args.tier == "canary" and not selected_ids:
            selected_ids = list(suite.get("canary_cases") or [])
        configurations = _csv(args.config) or list(suite["configurations"])
        seeds = [int(item) for item in _csv(args.seeds)] or list(suite["seeds"])
        if args.tier == "canary" and not args.seeds:
            seeds = seeds[:1]
        max_cycles_override = args.max_cycles
        if args.tier == "canary" and not max_cycles_override:
            max_cycles_override = 3
    programs = select_research_programs(all_programs, only=selected_ids)

    unknown = sorted(set(configurations) - set(CONFIGURATIONS))
    if unknown:
        raise ValueError(f"Unknown research configurations: {unknown}")

    fingerprint = suite_fingerprint(suite, all_programs)
    selection_fingerprint = suite_fingerprint(suite, programs)
    schedule = schedule_cells(programs, configurations, seeds)
    if args.dry_run:
        print(
            f"suite={suite['id']} fingerprint={fingerprint} "
            f"selection_fingerprint={selection_fingerprint} "
            f"cells={len(schedule)} oracle={args.oracle}"
        )
        for program, configuration, seed in schedule:
            cycles = min(
                program.budget.max_cycles,
                max_cycles_override or program.budget.max_cycles,
            )
            print(
                f"{program.id:34} {configuration:24} seed={seed:3d} "
                f"cycles<={cycles} policy={CONFIGURATIONS[configuration]['policy']}"
            )
        return 0

    if args.resume:
        checkpoint_path = Path(args.resume).resolve()
        report = resume_report
        assert report is not None
        if report["manifest"]["suite_fingerprint"] != fingerprint:
            raise ValueError("Resume refused: suite fingerprint changed")
        recorded_selection = report["manifest"].get("selection_fingerprint")
        if recorded_selection and recorded_selection != selection_fingerprint:
            raise ValueError("Resume refused: selected case fingerprint changed")
        run_dir = checkpoint_path.parent
    else:
        run_id = dt.datetime.now().strftime("research_trajectory_%Y%m%d_%H%M%S")
        run_dir = OUTPUT_ROOT / run_id
        checkpoint_path = run_dir / "checkpoint.json"
        report = {
            "schema_version": "1.0",
            "run_id": run_id,
            "state": "running",
            "created": _now(),
            "updated": _now(),
            "suite": suite,
            "settings": {
                "tier": args.tier,
                "oracle": args.oracle,
                "configurations": configurations,
                "seeds": seeds,
                "max_cycles_override": max_cycles_override or None,
                "strict_primary_models": bool(args.strict_primary_models),
                "sequential_model_cells": True,
            },
            "manifest": {
                "suite_fingerprint": fingerprint,
                "selection_fingerprint": selection_fingerprint,
                "astra_git_commit": _git_commit(),
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "records": [
                _new_record(
                    run_id=run_id,
                    program=program,
                    configuration=configuration,
                    seed=seed,
                )
                for program, configuration, seed in schedule
            ],
            "summary": {},
        }
        _checkpoint(report, checkpoint_path)

    program_by_id = {program.id: program for program in programs}
    min_cycles = int(suite.get("minimum_cycles_before_resolution") or 1)
    max_failures = int(suite.get("maximum_consecutive_operational_failures") or 2)
    weights = dict(suite["expert_weights"])

    # Recompute every persisted trajectory when resuming. This makes metric
    # bug fixes retroactive without rerunning expensive model cycles.
    for persisted_record in report.get("records") or []:
        if persisted_record.get("cycles"):
            persisted_record["metrics"] = compute_trajectory_metrics(
                persisted_record
            )
    _checkpoint(report, checkpoint_path)

    for record in report["records"]:
        if record.get("state") == "complete":
            continue
        program = program_by_id.get(record["case_id"])
        if program is None:
            continue
        record["state"] = "running"
        record.setdefault("started", _now())
        record.setdefault("cycles", [])
        _checkpoint(report, checkpoint_path)

        configured_max = int(record["budget"]["max_cycles"])
        max_cycles = min(configured_max, max_cycles_override or configured_max)
        wall_limit = float(record["budget"]["max_wall_minutes"]) * 60.0
        consecutive_operational_failures = 0
        while len(record["cycles"]) < max_cycles:
            elapsed = sum(
                float(item.get("duration_s") or 0.0)
                for item in record["cycles"]
            )
            if elapsed >= wall_limit:
                record["stop_reason"] = "wall_time_budget_exhausted"
                break
            cycle_index = len(record["cycles"]) + 1
            direction = _next_direction(program, record, cycle_index)
            print(
                f"[RUN] {record['case_id']} blind={record['blind_id']} "
                f"cycle={cycle_index}/{max_cycles}",
                flush=True,
            )
            result, duration, raw_output = _run_cycle(
                program=program,
                record=record,
                direction=direction,
                oracle=report["settings"]["oracle"],
                strict_primary_models=bool(
                    report["settings"].get("strict_primary_models")
                ),
            )
            cycle = {
                "cycle": cycle_index,
                "direction": direction,
                "started": _now(),
                "duration_s": duration,
                "result": result,
            }
            record["cycles"].append(cycle)
            record["metrics"] = compute_trajectory_metrics(record)
            cell_dir = (
                run_dir
                / "cells"
                / record["case_id"]
                / record["blind_id"]
            )
            _write_cycle_artifacts(cell_dir, cycle, raw_output)
            _write_cell_outputs(run_dir, record, program, weights)
            _checkpoint(report, checkpoint_path)

            status = _status(result)
            if status in OPERATIONAL_STATUSES:
                consecutive_operational_failures += 1
            else:
                consecutive_operational_failures = 0
            if consecutive_operational_failures >= max_failures:
                record["stop_reason"] = "consecutive_operational_failures"
                break
            macro_resolved = bool(
                (result.get("navigation") or {}).get("macro_resolved")
            )
            if macro_resolved and cycle_index >= min_cycles:
                record["stop_reason"] = "navigator_declared_macro_resolved"
                break

        record["metrics"] = compute_trajectory_metrics(record)
        record["state"] = "complete"
        record["finished"] = _now()
        _write_cell_outputs(run_dir, record, program, weights)
        _checkpoint(report, checkpoint_path)

    report["state"] = "complete"
    _checkpoint(report, checkpoint_path)
    print(f"Completed research trajectory run: {checkpoint_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(_parse_args()))
