"""Catalog, export, preflight, and pilot ASTRA external benchmarks."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.external_benchmarks import (
    ExternalCase,
    audit_external_sources,
    load_external_cases,
)
from core.external_evaluators import (
    clean_lean_proof,
    evaluate_ainstein_patch_remote,
    evaluate_frontier_answer,
    evaluate_minif2f_proof_remote,
    evaluate_scicode_code,
    evaluator_readiness,
    inspect_ainstein_repository_remote,
    prepare_ainstein_image_remote,
)
from core.architecture_configs import (
    ARCHITECTURE_ROLES,
    architecture_environment,
    architecture_roles,
)
from core.preflight import load_project_env

load_project_env()


def _select(args: argparse.Namespace) -> list[ExternalCase]:
    cases = load_external_cases(args.benchmark)
    if args.split:
        cases = [case for case in cases if case.split == args.split]
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case.id in wanted]
    if args.limit:
        cases = cases[: args.limit]
    return cases


def _catalog(
    cases: list[ExternalCase],
    readiness_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness_overrides = readiness_overrides or {}
    readiness = Counter()
    evaluators = Counter()
    for case in cases:
        evaluators[case.evaluator] += 1
        state = readiness_overrides.get(case.evaluator) or evaluator_readiness(case)
        readiness["ready" if state["ready"] else "blocked"] += 1
    return {
        "cases": len(cases),
        "by_benchmark": dict(Counter(case.benchmark for case in cases)),
        "by_split": dict(Counter(f"{case.benchmark}:{case.split}" for case in cases)),
        "by_evaluator": dict(evaluators),
        "evaluator_readiness": dict(readiness),
    }


async def _astrum_external_readiness() -> dict[str, dict[str, Any]]:
    from core.remote_executor import execute_remote_code

    code = r'''
import json
import os
import subprocess

lean = os.path.expanduser("~/.elan/bin/lean")
mathlib = os.path.expanduser(
    "~/astra-benchmarks/miniF2F/_target/deps/mathlib"
)
udocker = os.path.expanduser(
    "~/miniforge3/envs/astra-bench/bin/udocker"
)
udocker_dir = os.path.expanduser("~/astra-benchmarks/udocker")

def version(command):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30
        )
        return result.returncode, (result.stdout or result.stderr).strip()
    except Exception as exc:
        return 127, str(exc)

lean_rc, lean_version = version([lean, "--version"]) if os.path.isfile(lean) else (127, "")
udocker_rc, udocker_version = (
    version([udocker, "version"]) if os.path.isfile(udocker) else (127, "")
)
print(json.dumps({
    "lean3_compile": {
        "ready": lean_rc == 0 and os.path.isdir(mathlib),
        "mode": "ASTRUM Lean 3 + pinned mathlib",
        "detail": lean_version,
    },
    "ainstein_docker_tests": {
        "ready": udocker_rc == 0 and os.path.isdir(udocker_dir),
        "mode": "ASTRUM uDocker PRoot with official OCI images on demand",
        "detail": udocker_version.splitlines()[0] if udocker_version else "",
    },
}))
'''
    response = await execute_remote_code(code, timeout=75)
    if int(response.get("exit_code", -1)) != 0:
        return {}
    try:
        return json.loads(str(response.get("stdout") or "").strip())
    except json.JSONDecodeError:
        return {}


async def _invoke_cycle(
    case: ExternalCase,
    oracle: str,
    timeout: int,
    configuration: str = "full",
) -> dict[str, Any]:
    payload = {
        "action": "cycle",
        "objective": (
            "Solve this FrontierScience problem rigorously. The final response must "
            "contain one line beginning exactly with FINAL ANSWER: followed by the "
            "single requested answer."
        ),
        "intuition": (
            case.prompt
            + "\n\nDerive the result, actively search for counterchecks, and finish "
              "the consensus conjecture with `FINAL ANSWER: ...`."
        ),
        "oracle": oracle,
        "exec_timeout": 300,
    }
    env = architecture_environment(configuration)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "astra_tool.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload).encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {"error": f"TIMEOUT after {timeout}s"}
    raw = stdout.decode("utf-8", errors="replace").strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"error": "astra_tool returned non-JSON", "stdout_tail": raw[-2000:]}
    if stderr:
        result["stderr_tail"] = stderr.decode("utf-8", errors="replace")[-2000:]
    return result


async def _frontier_pilot(
    case: ExternalCase,
    *,
    oracle: str,
    timeout: int,
    configuration: str = "full",
) -> dict[str, Any]:
    if case.benchmark != "frontierscience" or case.split != "olympiad":
        raise ValueError("--pilot-frontier requires one FrontierScience olympiad case")
    cycle = await _invoke_cycle(case, oracle, timeout, configuration)
    candidate = str(cycle.get("conjecture") or cycle.get("analysis", {}).get("reasoning") or "")
    evaluation = _frontier_evaluation(candidate, case.reference, cycle)
    return {
        "protocol": "ASTRA external pilot v1; not an official leaderboard score",
        "configuration": configuration,
        "architecture": architecture_roles(configuration),
        "case": case.public_dict(),
        "candidate": candidate,
        "evaluation": evaluation,
        "reference": case.reference,
        "cycle": {
            key: cycle.get(key)
            for key in (
                "status", "providers", "cli_models", "timings", "code_review",
                "execution", "analysis", "navigation", "warnings", "error",
                "deliberation", "conjecture", "retries",
            )
            if cycle.get(key) is not None
        },
    }


def _frontier_evaluation(
    candidate: str,
    reference: str,
    cycle: dict[str, Any],
) -> dict[str, Any]:
    """Separate scientific abstention from an unavailable or broken tool."""
    error = str(cycle.get("error") or "").strip()
    if not error:
        return evaluate_frontier_answer(candidate, reference)

    operational_markers = (
        "api_error",
        "timeout",
        "astra_tool returned non-json",
        "all ensemble members failed",
    )
    if not candidate.strip() or any(
        marker in error.lower() for marker in operational_markers
    ):
        return {"status": "TOOL_ERROR", "method": error}

    return {
        "status": "ABSTAIN",
        "method": "independent_review_rejected",
        "reason": error,
        "candidate_answer_evaluation": evaluate_frontier_answer(
            candidate, reference
        ),
    }


def _code_from_response(response: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL | re.IGNORECASE)
    return (max(blocks, key=len) if blocks else response).strip()


def _patch_from_response(response: str) -> str:
    blocks = re.findall(
        r"```(?:diff|patch)?\s*\n(.*?)```",
        response or "",
        re.DOTALL | re.IGNORECASE,
    )
    candidates = list(blocks)
    marker = (response or "").find("diff --git ")
    if not candidates and marker >= 0:
        candidates.append((response or "")[marker:])
    valid = [
        candidate
        for candidate in candidates
        if _valid_unified_git_diff(candidate)
    ]
    if not valid:
        return ""
    patch = max(valid, key=len).strip()
    return patch.rstrip() + "\n" if patch else ""


def _valid_unified_git_diff(candidate: str) -> bool:
    if (
        not re.match(r"^\s*diff --git a/\S+ b/\S+", candidate)
        or not re.search(r"(?m)^--- (?:a/\S+|/dev/null)$", candidate)
        or not re.search(r"(?m)^\+\+\+ (?:b/\S+|/dev/null)$", candidate)
        or "```" in candidate
    ):
        return False
    hunks = re.findall(r"(?m)^@@.*$", candidate)
    if not hunks or any(
        not re.match(
            r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$",
            hunk,
        )
        for hunk in hunks
    ):
        return False
    try:
        parsed = subprocess.run(
            ["git", "apply", "--numstat", "-"],
            input=candidate.rstrip() + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parsed.returncode == 0 and bool(parsed.stdout.strip())


async def _scicode_pilot(
    case: ExternalCase,
    timeout: int,
    configuration: str = "full",
) -> dict[str, Any]:
    """Architecture-controlled SciCode pilot with the official evaluator."""
    from core.llm_client import ASTRAIntelligence, _extract_json_object

    if case.benchmark != "scicode" or case.split != "development":
        raise ValueError("--pilot-scicode requires one SciCode development case")
    roles = architecture_roles(configuration)
    design_system = (
        "You are an ASTRA scientific-code architect. Analyze the requested function, "
        "derive the governing equations, identify units, edge cases and numerical "
        "failure modes. Do not fabricate tests or target values. Return a compact "
        "implementation plan for another model."
    )
    proposers = [
        ASTRAIntelligence(provider=provider) for provider in roles["proposers"]
    ]
    designs = await asyncio.gather(
        *(
            agent._call_api(design_system, case.prompt)
            for agent in proposers
        )
    )
    synth = ASTRAIntelligence(provider=roles["synthesizer"])
    synthesis = await synth._call_api(
        "Synthesize two independent scientific-code plans. Resolve disagreements, "
        "preserve exact function signatures, and return one technically decisive plan.",
        f"PLAN A:\n{designs[0]}\n\nPLAN B:\n{designs[1]}\n\nTASK:\n{case.prompt}",
    )
    author = ASTRAIntelligence(provider=roles["author"])
    code_response = await author._call_api(
        "You are ASTRA's scientific code author. Return ONLY executable Python code, "
        "with required imports and the requested function. Do not print a verdict, "
        "include tests, use target values, or add Markdown outside one optional code fence.",
        f"TASK:\n{case.prompt}\n\nAUDITED DESIGN:\n{synthesis}",
    )
    code = _code_from_response(code_response)
    reviewer = ASTRAIntelligence(provider=roles["reviewer"])
    review_raw = await reviewer._call_api(
        "Audit scientific function code before official tests. Return only JSON with "
        "status APPROVED or REVISE, reasoning, and revision_instructions. Check the "
        "specified signature, equations, domains, units, edge cases, and independence "
        "from hidden target values.",
        f"TASK:\n{case.prompt}\n\nCODE:\n```python\n{code}\n```",
    )
    review = _extract_json_object(review_raw) or {
        "status": "REVISE",
        "reasoning": "Reviewer output was not valid JSON.",
        "revision_instructions": review_raw,
    }
    if str(review.get("status") or "").upper() != "APPROVED":
        repairer = (
            author
            if roles["repairer"] == roles["author"]
            else ASTRAIntelligence(provider=roles["repairer"])
        )
        revised = await repairer._call_api(
            "Revise the Python implementation. Return ONLY executable Python code and "
            "preserve the exact required signature.",
            f"TASK:\n{case.prompt}\n\nCURRENT CODE:\n{code}\n\n"
            f"REVIEW:\n{review.get('revision_instructions') or review.get('reasoning')}",
        )
        code = _code_from_response(revised)
    evaluation = await asyncio.to_thread(evaluate_scicode_code, case, code, timeout=timeout)
    models = {
        **{
            f"proposal_{index + 1}": agent.cli_last_model
            for index, agent in enumerate(proposers)
        },
        "synthesis": synth.cli_last_model,
        "code": author.cli_last_model,
        "review": reviewer.cli_last_model,
    }
    return {
        "protocol": "ASTRA SciCode development pilot v1",
        "configuration": configuration,
        "architecture": roles,
        "case": case.public_dict(),
        "designs": [
            {"provider": provider, "text": text}
            for provider, text in zip(roles["proposers"], designs)
        ],
        "synthesis": synthesis,
        "code": code,
        "review": review,
        "evaluation": evaluation,
        "models": {key: value for key, value in models.items() if value},
    }


async def _ainstein_pilot(
    case: ExternalCase,
    timeout: int,
    configuration: str = "full",
) -> dict[str, Any]:
    """Blind repository pilot using issue-derived inspection and official tests."""
    from core.llm_client import ASTRAIntelligence, _extract_json_object

    if case.benchmark != "ainsteinbench":
        raise ValueError("--pilot-ainstein requires one AInsteinBench case")
    roles = architecture_roles(configuration)
    navigator_system = (
        "You are planning a blind repository inspection for a scientific coding "
        "issue. Return only JSON with `search_terms` (3-8 literal terms from the "
        "issue) and `path_hints` (0-6 likely source paths or directories). Do not "
        "invent code, patches, tests, or reference answers."
    )
    navigators = [
        ASTRAIntelligence(provider=provider) for provider in roles["proposers"]
    ]
    navigation_raw = await asyncio.gather(
        *(agent._call_api(navigator_system, case.prompt) for agent in navigators)
    )
    navigation = [
        _extract_json_object(item) or {"search_terms": [], "path_hints": []}
        for item in navigation_raw
    ]
    terms = []
    paths = []
    for item in navigation:
        for value in item.get("search_terms") or []:
            if isinstance(value, str) and value.strip() and value not in terms:
                terms.append(value.strip())
        for value in item.get("path_hints") or []:
            if isinstance(value, str) and value.strip() and value not in paths:
                paths.append(value.strip())
    if not terms:
        terms = [
            word
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", case.prompt)
            if word.lower() not in {"scientific", "repository", "implement"}
        ][:6]
    inspection = await inspect_ainstein_repository_remote(
        case,
        search_terms=terms,
        path_hints=paths,
        timeout=min(timeout, 300),
    )
    if inspection["status"] != "PASS":
        return {
            "protocol": "ASTRA AInsteinBench blind pilot v1",
            "case": case.public_dict(),
            "navigation": navigation,
            "inspection": inspection,
            "evaluation": {"status": "INSPECTION_ERROR"},
        }
    context = "\n\n".join(inspection.get("snippets") or [])
    synth = ASTRAIntelligence(provider=roles["synthesizer"])
    synthesis = await synth._call_api(
        "Design a minimal scientifically correct repository patch from the issue "
        "and inspected source. Explain the defect mechanism and exact edit. Do not "
        "modify tests or use any hidden target information.",
        f"ISSUE:\n{case.prompt}\n\nREPOSITORY CONTEXT:\n{context}",
    )
    author = ASTRAIntelligence(provider=roles["author"])
    patch_response = await author._call_api(
        "Write a minimal unified git diff implementing the requested scientific "
        "fix. Return only the diff beginning `diff --git`. Do not modify tests, "
        "benchmarks, or generated files.",
        f"ISSUE:\n{case.prompt}\n\nREPOSITORY CONTEXT:\n{context}\n\n"
        f"IMPLEMENTATION PLAN:\n{synthesis}",
    )
    patch = _patch_from_response(patch_response)
    reviewer = ASTRAIntelligence(provider=roles["reviewer"])
    review_raw = await reviewer._call_api(
        "Audit a candidate scientific repository patch. Return only JSON with "
        "status APPROVED or REVISE, reasoning, and revision_instructions. Reject "
        "test modifications, reference leakage, broad rewrites, and scientific or "
        "dimensional mistakes.",
        f"ISSUE:\n{case.prompt}\n\nCONTEXT:\n{context}\n\nPATCH:\n{patch}",
    )
    review = _extract_json_object(review_raw) or {
        "status": "REVISE",
        "reasoning": "Reviewer output was not valid JSON.",
        "revision_instructions": review_raw,
    }
    if str(review.get("status") or "").upper() != "APPROVED":
        revised = await author._call_api(
            "Revise the patch from the audit. Return only a minimal unified git "
            "diff and do not modify tests.",
            f"ISSUE:\n{case.prompt}\n\nCONTEXT:\n{context}\n\nPATCH:\n{patch}\n\n"
            f"AUDIT:\n{review.get('revision_instructions') or review.get('reasoning')}",
        )
        patch = _patch_from_response(revised)

    attempts = []
    for attempt in range(3):
        evaluation = await evaluate_ainstein_patch_remote(
            case,
            patch,
            timeout=min(timeout, 1800),
        )
        attempts.append({"patch": patch, "evaluation": evaluation})
        if evaluation["status"] == "PASS" or attempt == 2:
            break
        diagnostics = (
            str(evaluation.get("stderr") or "")
            + "\n"
            + str(evaluation.get("stdout") or "")
        )[-16000:]
        revised = await author._call_api(
            "Repair the unified diff using the official build/test diagnostics. "
            "Return only the complete minimal diff. Do not modify tests.",
            f"ISSUE:\n{case.prompt}\n\nCONTEXT:\n{context}\n\n"
            f"CURRENT PATCH:\n{patch}\n\nDIAGNOSTICS:\n{diagnostics}",
        )
        patch = _patch_from_response(revised)

    models = {
        **{
            f"navigation_{index + 1}": agent.cli_last_model
            for index, agent in enumerate(navigators)
        },
        "synthesis": synth.cli_last_model,
        "patch": author.cli_last_model,
        "review": reviewer.cli_last_model,
    }
    return {
        "protocol": "ASTRA AInsteinBench blind pilot v1",
        "configuration": configuration,
        "architecture": roles,
        "case": case.public_dict(),
        "navigation": navigation,
        "inspection": inspection,
        "synthesis": synthesis,
        "review": review,
        "attempts": attempts,
        "patch": patch,
        "evaluation": attempts[-1]["evaluation"],
        "models": {key: value for key, value in models.items() if value},
    }


async def _minif2f_pilot(
    case: ExternalCase,
    timeout: int,
    configuration: str = "full",
) -> dict[str, Any]:
    """ASTRA role-map pilot followed by pinned Lean 3 compilation on ASTRUM."""
    from core.llm_client import ASTRAIntelligence, _extract_json_object

    if case.benchmark != "minif2f" or case.split != "validation":
        raise ValueError("--pilot-minif2f requires one miniF2F validation case")
    roles = architecture_roles(configuration)
    strategy_system = (
        "You are an ASTRA Lean 3 proof strategist. Analyze the theorem and propose "
        "a short proof using tactics available in the 2022 Lean 3 mathlib. Do not "
        "use Lean 4 syntax, sorry, admit, axioms, or change the theorem statement."
    )
    strategists = [
        ASTRAIntelligence(provider=provider) for provider in roles["proposers"]
    ]
    strategies = await asyncio.gather(
        *(agent._call_api(strategy_system, case.prompt) for agent in strategists)
    )
    synth = ASTRAIntelligence(provider=roles["synthesizer"])
    synthesis = await synth._call_api(
        "Reconcile two Lean 3 proof strategies into one precise tactic plan. "
        "Reject any Lean 4-only syntax or unproved placeholder.",
        f"THEOREM:\n{case.prompt}\n\nSTRATEGY A:\n{strategies[0]}\n\n"
        f"STRATEGY B:\n{strategies[1]}",
    )
    author = ASTRAIntelligence(provider=roles["author"])
    proof_response = await author._call_api(
        "Write the proof for Lean 3.42.1 with mathlib. Return only a proof beginning "
        "with `begin` and ending with `end`, or a Lean 3 `by` proof. Never use "
        "`sorry`, `admit`, an axiom, or restate the theorem.",
        f"THEOREM:\n{case.prompt}\n\nAUDITED STRATEGY:\n{synthesis}",
    )
    proof = clean_lean_proof(proof_response)
    reviewer = ASTRAIntelligence(provider=roles["reviewer"])
    review_raw = await reviewer._call_api(
        "Audit a proposed Lean 3 proof before compilation. Return only JSON with "
        "status APPROVED or REVISE, reasoning, and revision_instructions. Reject "
        "Lean 4 syntax, placeholders, theorem restatement, and tactics unavailable "
        "in Lean 3 mathlib.",
        f"THEOREM:\n{case.prompt}\n\nPROOF:\n```lean\n{proof}\n```",
    )
    review = _extract_json_object(review_raw) or {
        "status": "REVISE",
        "reasoning": "Reviewer output was not valid JSON.",
        "revision_instructions": review_raw,
    }
    if str(review.get("status") or "").upper() != "APPROVED":
        revised = await author._call_api(
            "Revise the proof for Lean 3.42.1. Return only the complete proof block, "
            "without placeholders or theorem restatement.",
            f"THEOREM:\n{case.prompt}\n\nCURRENT PROOF:\n{proof}\n\n"
            f"REVIEW:\n{review.get('revision_instructions') or review.get('reasoning')}",
        )
        proof = clean_lean_proof(revised)

    attempts = []
    for attempt in range(3):
        evaluation = await evaluate_minif2f_proof_remote(
            case,
            proof,
            timeout=min(timeout, 300),
        )
        attempts.append({"proof": proof, "evaluation": evaluation})
        if evaluation["status"] == "PASS" or attempt == 2:
            break
        diagnostics = evaluation.get("stderr") or evaluation.get("stdout") or ""
        revised = await author._call_api(
            "Repair this Lean 3 proof using the compiler diagnostics. Return only "
            "the complete proof block. Do not use sorry, admit, or axioms.",
            f"THEOREM:\n{case.prompt}\n\nCURRENT PROOF:\n{proof}\n\n"
            f"LEAN 3 DIAGNOSTICS:\n{diagnostics}",
        )
        proof = clean_lean_proof(revised)

    models = {
        **{
            f"strategy_{index + 1}": agent.cli_last_model
            for index, agent in enumerate(strategists)
        },
        "synthesis": synth.cli_last_model,
        "proof": author.cli_last_model,
        "review": reviewer.cli_last_model,
    }
    return {
        "protocol": "ASTRA miniF2F validation pilot v1",
        "configuration": configuration,
        "architecture": roles,
        "case": case.public_dict(),
        "strategies": [
            {"provider": provider, "text": text}
            for provider, text in zip(roles["proposers"], strategies)
        ],
        "synthesis": synthesis,
        "review": review,
        "attempts": attempts,
        "proof": proof,
        "evaluation": attempts[-1]["evaluation"],
        "models": {key: value for key, value in models.items() if value},
    }


async def main(args: argparse.Namespace) -> int:
    audit = audit_external_sources()
    if not audit["ok"]:
        print(json.dumps(audit, indent=2))
        print(
            "Run `python scripts/prepare_external_benchmarks.py --download` first.",
            file=sys.stderr,
        )
        return 2
    cases = _select(args)

    if args.list:
        print(json.dumps([case.public_dict() for case in cases], indent=2))
        return 0
    if args.export:
        target = Path(args.export).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(json.dumps(case.public_dict()) for case in cases) + "\n",
            encoding="utf-8",
        )
        print(target)
        return 0
    if args.prepare_ainstein_image:
        matches = [case for case in cases if case.id == args.prepare_ainstein_image]
        if len(matches) != 1:
            raise ValueError(
                "AInsteinBench image case not selected exactly once: "
                f"{args.prepare_ainstein_image}"
            )
        result = await prepare_ainstein_image_remote(
            matches[0],
            timeout=args.timeout,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "READY" else 1
    if args.pilot_frontier:
        matches = [case for case in cases if case.id == args.pilot_frontier]
        if len(matches) != 1:
            raise ValueError(f"Pilot case not selected exactly once: {args.pilot_frontier}")
        report = await _frontier_pilot(
            matches[0],
            oracle=args.oracle,
            timeout=args.timeout,
            configuration=args.configuration,
        )
        out_dir = ROOT / "workspace" / "external_benchmark_runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = dt.datetime.now().strftime("frontier_pilot_%Y%m%d_%H%M%S.json")
        target = out_dir / slug
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "case": matches[0].id,
            "evaluation": report["evaluation"],
            "report": str(target),
        }, indent=2))
        return 0
    if args.pilot_scicode:
        matches = [case for case in cases if case.id == args.pilot_scicode]
        if len(matches) != 1:
            raise ValueError(f"Pilot case not selected exactly once: {args.pilot_scicode}")
        report = await _scicode_pilot(
            matches[0],
            timeout=args.timeout,
            configuration=args.configuration,
        )
        out_dir = ROOT / "workspace" / "external_benchmark_runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = dt.datetime.now().strftime("scicode_pilot_%Y%m%d_%H%M%S.json")
        target = out_dir / slug
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "case": matches[0].id,
            "review": report["review"].get("status"),
            "evaluation": report["evaluation"],
            "models": report["models"],
            "report": str(target),
        }, indent=2))
        return 0
    if args.pilot_minif2f:
        matches = [case for case in cases if case.id == args.pilot_minif2f]
        if len(matches) != 1:
            raise ValueError(f"Pilot case not selected exactly once: {args.pilot_minif2f}")
        report = await _minif2f_pilot(
            matches[0],
            timeout=args.timeout,
            configuration=args.configuration,
        )
        out_dir = ROOT / "workspace" / "external_benchmark_runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = dt.datetime.now().strftime("minif2f_pilot_%Y%m%d_%H%M%S.json")
        target = out_dir / slug
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "case": matches[0].id,
            "review": report["review"].get("status"),
            "attempts": len(report["attempts"]),
            "evaluation": report["evaluation"],
            "models": report["models"],
            "report": str(target),
        }, indent=2))
        return 0
    if args.pilot_ainstein:
        matches = [case for case in cases if case.id == args.pilot_ainstein]
        if len(matches) != 1:
            raise ValueError(f"Pilot case not selected exactly once: {args.pilot_ainstein}")
        report = await _ainstein_pilot(
            matches[0],
            timeout=args.timeout,
            configuration=args.configuration,
        )
        out_dir = ROOT / "workspace" / "external_benchmark_runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = dt.datetime.now().strftime("ainstein_pilot_%Y%m%d_%H%M%S.json")
        target = out_dir / slug
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "case": matches[0].id,
            "review": report.get("review", {}).get("status"),
            "attempts": len(report.get("attempts") or []),
            "evaluation": report["evaluation"],
            "models": report.get("models", {}),
            "report": str(target),
        }, indent=2))
        return 0

    readiness_overrides = (
        await _astrum_external_readiness()
        if args.oracle == "astrum"
        else {}
    )
    print(json.dumps({
        "source_audit": audit,
        "selection": _catalog(cases, readiness_overrides),
        "runtime_readiness": readiness_overrides,
        "note": (
            "Readiness follows the selected oracle. FrontierScience research still "
            "needs expert grading. AInsteinBench images are downloaded per task."
        ),
    }, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ASTRA external benchmark adapters")
    result.add_argument(
        "--benchmark",
        choices=["all", "scicode", "minif2f", "frontierscience", "ainsteinbench"],
        default="all",
    )
    result.add_argument("--split", default="")
    result.add_argument("--only", default="")
    result.add_argument("--limit", type=int, default=0)
    result.add_argument("--list", action="store_true")
    result.add_argument("--export", default="")
    result.add_argument("--pilot-frontier", default="")
    result.add_argument("--pilot-scicode", default="")
    result.add_argument("--pilot-minif2f", default="")
    result.add_argument("--pilot-ainstein", default="")
    result.add_argument("--prepare-ainstein-image", default="")
    result.add_argument("--oracle", choices=["local", "astrum", "auto"], default="astrum")
    result.add_argument(
        "--configuration",
        choices=sorted(ARCHITECTURE_ROLES),
        default="full",
    )
    result.add_argument("--timeout", type=int, default=2400)
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main(parser().parse_args())))
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
