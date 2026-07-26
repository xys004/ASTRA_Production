"""Pinned adapters for public scientific benchmarks.

The adapters preserve each benchmark's native task and evaluator type. They do
not pretend that a Lean proof, a repository patch, a numerical function, and an
expert-graded research answer share one interchangeable accuracy number.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "benchmarks" / "external" / "registry.json"


@dataclass(frozen=True)
class ExternalCase:
    benchmark: str
    id: str
    split: str
    domain: str
    task_type: str
    evaluator: str
    prompt: str
    reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "id": self.id,
            "split": self.split,
            "domain": self.domain,
            "task_type": self.task_type,
            "evaluator": self.evaluator,
            "prompt": self.prompt,
            "metadata": {
                key: value
                for key, value in self.metadata.items()
                if key not in {"test_cases", "test_patch", "docker_image"}
            },
        }


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cache_root(registry: dict[str, Any] | None = None) -> Path:
    registry = registry or load_registry()
    return ROOT / registry["cache_root"]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_scicode(root: Path | None = None) -> list[ExternalCase]:
    registry = load_registry()
    root = root or cache_root(registry) / "SciCode_dataset"
    excluded = set(registry["datasets"]["scicode"]["excluded_subproblems"])
    cases: list[ExternalCase] = []
    for split, filename in (
        ("development", "problems_dev.jsonl"),
        ("test", "problems_test.jsonl"),
    ):
        for problem in _read_jsonl(root / filename):
            previous_headers: list[str] = []
            for step in problem["sub_steps"]:
                step_number = str(step["step_number"])
                if step_number in excluded:
                    continue
                prompt = (
                    "SCICODE SCIENTIFIC CODING SUBPROBLEM\n\n"
                    f"Main problem: {problem['problem_name']} "
                    f"(id {problem['problem_id']})\n"
                    f"{problem['problem_description_main']}\n\n"
                    f"Required imports:\n{problem['required_dependencies']}\n\n"
                    f"Current subproblem {step_number}:\n"
                    f"{step['step_description_prompt']}\n\n"
                    f"Required signature:\n{step['function_header']}\n\n"
                    f"Required return line:\n{step['return_line']}\n"
                )
                if step.get("step_background"):
                    prompt += f"\nScientific background:\n{step['step_background']}\n"
                if previous_headers:
                    prompt += (
                        "\nPreviously requested interfaces (available to call):\n"
                        + "\n\n".join(previous_headers)
                    )
                cases.append(
                    ExternalCase(
                        benchmark="scicode",
                        id=f"scicode_{step_number.replace('.', '_')}",
                        split=split,
                        domain=str(problem.get("problem_name") or "scientific_coding"),
                        task_type="python_function",
                        evaluator="scicode_h5_tests",
                        prompt=prompt,
                        reference=str(step.get("ground_truth_code") or ""),
                        metadata={
                            "problem_id": str(problem["problem_id"]),
                            "step_number": step_number,
                            "function_header": step["function_header"],
                            "required_dependencies": problem["required_dependencies"],
                            "test_cases": step.get("test_cases", []),
                        },
                    )
                )
                previous_headers.append(step["function_header"])
    return cases


_THEOREM_START = re.compile(r"(?m)^theorem\s+([^\s:(]+)")


def _lean_theorems(path: Path) -> Iterable[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    matches = list(_THEOREM_START.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start():end].strip()
        statement, marker, _proof = block.partition(":=")
        if not marker:
            continue
        yield match.group(1), statement.strip()


def load_minif2f(root: Path | None = None) -> list[ExternalCase]:
    root = root or cache_root() / "miniF2F"
    cases: list[ExternalCase] = []
    for split, filename in (("validation", "valid.lean"), ("test", "test.lean")):
        path = root / "lean" / "src" / filename
        for name, statement in _lean_theorems(path):
            cases.append(
                ExternalCase(
                    benchmark="minif2f",
                    id=f"minif2f_{split}_{name}",
                    split=split,
                    domain="formal_mathematics",
                    task_type="lean3_proof",
                    evaluator="lean3_compile",
                    prompt=(
                        "Complete the following Lean 3 theorem. Return only the proof "
                        "term beginning with `by` or the tactic block beginning with "
                        "`begin`; do not change the statement.\n\n"
                        f"{statement} :="
                    ),
                    metadata={
                        "theorem_name": name,
                        "statement": statement,
                        "source": str(path),
                    },
                )
            )
    return cases


def load_frontierscience(root: Path | None = None) -> list[ExternalCase]:
    root = root or cache_root() / "frontierscience"
    cases: list[ExternalCase] = []
    for split in ("olympiad", "research"):
        for row in _read_jsonl(root / split / "test.jsonl"):
            cases.append(
                ExternalCase(
                    benchmark="frontierscience",
                    id=f"frontierscience_{split}_{row['task_group_id']}",
                    split=split,
                    domain=str(row.get("subject") or "science"),
                    task_type="open_scientific_reasoning",
                    evaluator=(
                        "frontier_answer_equivalence"
                        if split == "olympiad"
                        else "frontier_expert_rubric"
                    ),
                    prompt=str(row["problem"]),
                    reference=str(row["answer"]),
                    metadata={"task_group_id": row["task_group_id"]},
                )
            )
    return cases


def load_ainsteinbench(root: Path | None = None) -> list[ExternalCase]:
    root = root or cache_root() / "AInsteinBench"
    rows = _read_jsonl(root / "data" / "msb_type.jsonl")
    cases: list[ExternalCase] = []
    for row in rows:
        content = row["content"]
        environment = row["environment"]
        test = row["test"]
        resolved_issues = content.get("resolved_issues") or []
        issue_context = ""
        if resolved_issues:
            issue_context = "\n\nResolved issue context:\n" + "\n\n".join(
                f"#{item.get('number', '')} — {item.get('title', '')}\n"
                f"{item.get('body', '')}"
                for item in resolved_issues
                if isinstance(item, dict)
            )
        prompt = (
            "AINSTEINBENCH SCIENTIFIC REPOSITORY TASK\n\n"
            f"Repository: {content['org']}/{content['repo']}\n"
            f"Issue: {content['issue_title']}\n\n"
            f"{content['issue_body']}"
            f"{issue_context}\n\n"
            "Implement a minimal scientifically correct patch. Do not inspect or "
            "infer the hidden reference patch."
        )
        cases.append(
            ExternalCase(
                benchmark="ainsteinbench",
                id=f"ainsteinbench_{row['question_id']}",
                split="test",
                domain=str(content.get("repo") or "scientific_repository"),
                task_type="repository_patch",
                evaluator="ainstein_docker_tests",
                prompt=prompt,
                reference=str(row.get("answer", {}).get("fix_patch") or ""),
                metadata={
                    "question_id": row["question_id"],
                    "org": content["org"],
                    "repo": content["repo"],
                    "docker_image": environment["docker_image"],
                    "working_directory": environment["working_directory"],
                    "needs_build": environment.get("needs_build", False),
                    "test_patch": test.get("test_patch", ""),
                    "pass_criteria": test.get("pass_criteria", ""),
                    "scoring_config": row.get("scoring_config", {}),
                },
            )
        )
    return cases


LOADERS = {
    "scicode": load_scicode,
    "minif2f": load_minif2f,
    "frontierscience": load_frontierscience,
    "ainsteinbench": load_ainsteinbench,
}


def load_external_cases(benchmark: str = "all") -> list[ExternalCase]:
    if benchmark == "all":
        cases: list[ExternalCase] = []
        for name in LOADERS:
            cases.extend(LOADERS[name]())
        return cases
    try:
        return LOADERS[benchmark]()
    except KeyError as exc:
        raise ValueError(f"Unknown external benchmark: {benchmark}") from exc


def _git_commit(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def audit_external_sources() -> dict[str, Any]:
    registry = load_registry()
    root = cache_root(registry)
    source_checks = []
    for dataset in registry["datasets"].values():
        for source in dataset["sources"]:
            path = root / source["name"]
            actual = _git_commit(path) if path.exists() else "missing"
            source_checks.append({
                "name": source["name"],
                "expected_commit": source["commit"],
                "actual_commit": actual,
                "ok": actual == source["commit"],
            })

    counts = {}
    errors = []
    for benchmark, loader in LOADERS.items():
        try:
            cases = loader()
            counts[benchmark] = {
                "total": len(cases),
                "by_split": {
                    split: sum(case.split == split for case in cases)
                    for split in sorted({case.split for case in cases})
                },
            }
        except Exception as exc:
            errors.append({"benchmark": benchmark, "error": str(exc)})

    fingerprint = hashlib.sha256(
        json.dumps(
            {"sources": source_checks, "counts": counts},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": registry["schema_version"],
        "source_checks": source_checks,
        "counts": counts,
        "errors": errors,
        "fingerprint": fingerprint,
        "ok": all(item["ok"] for item in source_checks) and not errors,
    }
