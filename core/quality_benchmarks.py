"""Typed loader for ASTRA Quality Benchmark v1.

The quality suite deliberately separates three questions:

* ``cycle``: did the complete multi-model research loop validate/refute truth?
* ``validator_audit``: did the independent reviewer detect a defective oracle?
* ``execution``: does deterministic evidence reproduce across oracle backends?

Legacy golden cases remain valid and are imported as ``cycle`` cases so the new
runner extends, rather than silently replaces, the original benchmark suite.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
QUALITY_ROOT = ROOT / "benchmarks" / "quality"


@dataclass(frozen=True)
class QualityCase:
    id: str
    track: str
    domain: str
    difficulty: str
    expected: str
    objective: str = ""
    intuition: str = ""
    axiomatic_base: str = ""
    code: str = ""
    expected_review: tuple[str, ...] = ()
    expected_defects: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    timeout: int = 180
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def cycle_request(self, oracle: str) -> dict[str, Any]:
        criteria = "\n".join(f"- {item}" for item in self.success_criteria)
        failures = "\n".join(f"- {item}" for item in self.failure_modes)
        direction = self.intuition
        if criteria or failures:
            direction += (
                "\n\nBENCHMARK SUCCESS CRITERIA:\n"
                f"{criteria or '- Establish the decisive claim.'}\n\n"
                "KNOWN FAILURE MODES TO AVOID:\n"
                f"{failures or '- Do not accept a non-falsifiable validator.'}"
            )
        return {
            "action": "cycle",
            "objective": self.objective or self.intuition,
            "intuition": direction,
            "axiomatic_base": self.axiomatic_base,
            "oracle": oracle,
            "exec_timeout": self.timeout,
        }


def _objects(path: Path) -> Iterable[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        yield from raw
    elif isinstance(raw, dict):
        yield raw
    else:
        raise ValueError(f"{path}: root JSON must be an object or list")


def _case_from_dict(data: dict[str, Any], path: Path) -> QualityCase:
    required = {"id", "track", "domain", "difficulty", "expected"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"{path}: missing required fields {sorted(missing)}")
    track = str(data["track"]).lower()
    if track not in {"cycle", "validator_audit", "execution"}:
        raise ValueError(f"{path}: unsupported track {track!r}")
    if track == "cycle" and not (data.get("intuition") or data.get("claim")):
        raise ValueError(f"{path}: cycle case requires intuition or claim")
    if track in {"validator_audit", "execution"} and not data.get("code"):
        raise ValueError(f"{path}: {track} case requires code")

    known = {
        "id", "track", "domain", "difficulty", "expected", "objective",
        "intuition", "claim", "axiomatic_base", "code", "expected_review",
        "expected_defects", "success_criteria", "failure_modes", "tags",
        "timeout",
    }
    return QualityCase(
        id=str(data["id"]),
        track=track,
        domain=str(data["domain"]),
        difficulty=str(data["difficulty"]),
        expected=str(data["expected"]).upper(),
        objective=str(data.get("objective") or data.get("claim") or ""),
        intuition=str(data.get("intuition") or data.get("claim") or ""),
        axiomatic_base=str(data.get("axiomatic_base") or ""),
        code=str(data.get("code") or ""),
        expected_review=tuple(str(x).upper() for x in data.get("expected_review", [])),
        expected_defects=tuple(str(x).lower() for x in data.get("expected_defects", [])),
        success_criteria=tuple(str(x) for x in data.get("success_criteria", [])),
        failure_modes=tuple(str(x) for x in data.get("failure_modes", [])),
        tags=tuple(str(x).lower() for x in data.get("tags", [])),
        timeout=int(data.get("timeout", 180)),
        metadata={key: value for key, value in data.items() if key not in known},
        path=path,
    )


_LEGACY_SMOKE_IDS = {
    "gr_minkowski_flat_curvature",
    "logic_false_square_claim",
    "ode_harmonic_oscillator_solution",
    "quantum_pauli_commutator",
}


def _legacy_cases() -> list[QualityCase]:
    from core.benchmarks import load_benchmarks

    cases: list[QualityCase] = []
    for item in load_benchmarks():
        tags = ("legacy", "smoke") if item.id in _LEGACY_SMOKE_IDS else ("legacy",)
        cases.append(
            QualityCase(
                id=item.id,
                track="cycle",
                domain=item.domain,
                difficulty=item.difficulty,
                expected=item.expected.upper(),
                objective=f"Determine rigorously whether this claim is true: {item.claim}",
                intuition=item.prompt + "\n\nCLAIM:\n" + item.claim,
                success_criteria=tuple(item.success_criteria),
                failure_modes=tuple(item.failure_modes),
                tags=tags,
                path=item.path,
            )
        )
    return cases


def load_quality_cases(
    root: Path = QUALITY_ROOT,
    *,
    include_legacy: bool = True,
) -> list[QualityCase]:
    cases = _legacy_cases() if include_legacy else []
    if root.exists():
        for path in sorted(root.glob("*/*.json")):
            cases.extend(_case_from_dict(data, path) for data in _objects(path))
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case in cases:
        if case.id in seen:
            duplicates.add(case.id)
        seen.add(case.id)
    if duplicates:
        raise ValueError(f"Duplicate quality case ids: {sorted(duplicates)}")
    return sorted(cases, key=lambda case: (case.track, case.domain, case.id))


def select_quality_cases(
    cases: Iterable[QualityCase],
    *,
    tier: str,
    tracks: set[str] | None = None,
    only: set[str] | None = None,
) -> list[QualityCase]:
    tier = tier.lower()
    if tier not in {"smoke", "standard", "release"}:
        raise ValueError(f"Unknown tier: {tier}")
    selected = []
    for case in cases:
        if tracks and case.track not in tracks:
            continue
        if only and case.id not in only:
            continue
        if tier == "smoke" and "smoke" not in case.tags:
            continue
        if tier == "standard" and "release_only" in case.tags:
            continue
        selected.append(case)
    return selected


def quality_summary(cases: Iterable[QualityCase]) -> dict[str, Any]:
    cases = list(cases)
    by_track: dict[str, int] = {}
    by_expected: dict[str, int] = {}
    for case in cases:
        by_track[case.track] = by_track.get(case.track, 0) + 1
        by_expected[case.expected] = by_expected.get(case.expected, 0) + 1
    return {"count": len(cases), "by_track": by_track, "by_expected": by_expected}
