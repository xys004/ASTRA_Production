from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / "benchmarks"


@dataclass
class Benchmark:
    id: str
    domain: str
    difficulty: str
    claim: str
    expected: str
    preferred_engines: list[str]
    success_criteria: list[str]
    failure_modes: list[str]
    prompt: str
    path: Path

    def to_prompt(self) -> str:
        criteria = "\n".join(f"- {item}" for item in self.success_criteria)
        failures = "\n".join(f"- {item}" for item in self.failure_modes)
        engines = ", ".join(self.preferred_engines)
        return f"""ASTRUM BENCHMARK: {self.id}
Domain: {self.domain}
Expected result: {self.expected}
Preferred engines: {engines}

Claim:
{self.claim}

Task:
{self.prompt}

Success criteria:
{criteria}

Known failure modes to avoid:
{failures}

Return a rigorous validation/refutation workflow. The final oracle script must print VERDICT: PASS or VERDICT: FAIL with concise evidence.
"""


def load_benchmarks(root: Path = BENCHMARK_ROOT) -> list[Benchmark]:
    benchmarks: list[Benchmark] = []
    for path in sorted(root.glob("*/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        benchmarks.append(
            Benchmark(
                id=data["id"],
                domain=data["domain"],
                difficulty=data["difficulty"],
                claim=data["claim"],
                expected=data["expected"],
                preferred_engines=list(data["preferred_engines"]),
                success_criteria=list(data["success_criteria"]),
                failure_modes=list(data["failure_modes"]),
                prompt=data["prompt"],
                path=path,
            )
        )
    return benchmarks


def benchmark_summary() -> dict:
    benchmarks = load_benchmarks()
    by_domain: dict[str, int] = {}
    for benchmark in benchmarks:
        by_domain[benchmark.domain] = by_domain.get(benchmark.domain, 0) + 1
    return {"count": len(benchmarks), "by_domain": by_domain}


def get_benchmark(benchmark_id: str) -> Benchmark:
    for benchmark in load_benchmarks():
        if benchmark.id == benchmark_id:
            return benchmark
    raise KeyError(f"Benchmark not found: {benchmark_id}")
