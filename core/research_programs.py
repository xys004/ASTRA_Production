"""Schemas and loaders for ASTRA Research Trajectory Benchmark programs.

Unlike the task-oriented benchmark suites, a research program begins with one
human objective and gives the architecture a bounded sequence of autonomous
cycles.  The loader deliberately keeps scientific goals, resource declarations,
and expert-grading anchors in data files so that a live evaluation can be frozen
before any model output is observed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_ROOT = ROOT / "benchmarks" / "research_trajectory" / "cases"
DEFAULT_SUITE = ROOT / "benchmarks" / "research_trajectory" / "pilot_v1.json"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ALLOWED_DIMENSIONS = {
    "goal_advancement",
    "hypothesis_quality",
    "research_depth",
    "evidence_quality",
    "self_correction",
    "cross_perspective_uptake",
    "novelty_utility",
    "artifact_reproducibility",
}


@dataclass(frozen=True)
class ResearchBudget:
    max_cycles: int
    max_wall_minutes: int
    cycle_timeout_seconds: int
    execution_timeout_seconds: int
    human_interventions: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchBudget":
        budget = cls(
            max_cycles=int(data["max_cycles"]),
            max_wall_minutes=int(data["max_wall_minutes"]),
            cycle_timeout_seconds=int(data["cycle_timeout_seconds"]),
            execution_timeout_seconds=int(data["execution_timeout_seconds"]),
            human_interventions=int(data.get("human_interventions", 1)),
        )
        if budget.max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if budget.max_wall_minutes < 1:
            raise ValueError("max_wall_minutes must be positive")
        if budget.cycle_timeout_seconds < 1:
            raise ValueError("cycle_timeout_seconds must be positive")
        if budget.execution_timeout_seconds < 1:
            raise ValueError("execution_timeout_seconds must be positive")
        if budget.human_interventions != 1:
            raise ValueError(
                "Research Trajectory v1 requires exactly one human objective"
            )
        return budget

    def to_dict(self) -> dict[str, int]:
        return {
            "max_cycles": self.max_cycles,
            "max_wall_minutes": self.max_wall_minutes,
            "cycle_timeout_seconds": self.cycle_timeout_seconds,
            "execution_timeout_seconds": self.execution_timeout_seconds,
            "human_interventions": self.human_interventions,
        }


@dataclass(frozen=True)
class ResearchProgram:
    id: str
    title: str
    domain: str
    objective: str
    success_definition: str
    deliverables: tuple[str, ...]
    preferred_validators: tuple[str, ...]
    resources: tuple[str, ...]
    linear_control_directions: tuple[str, ...]
    expert_anchors: dict[str, str]
    budget: ResearchBudget
    tags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchProgram":
        required = {
            "id",
            "title",
            "domain",
            "objective",
            "success_definition",
            "deliverables",
            "preferred_validators",
            "linear_control_directions",
            "expert_anchors",
            "budget",
        }
        missing = sorted(required - set(data))
        if missing:
            raise ValueError(f"Research program is missing fields: {missing}")
        case_id = str(data["id"])
        if not _ID_RE.match(case_id):
            raise ValueError(f"Invalid research program id: {case_id}")
        objective = str(data["objective"]).strip()
        if len(objective) < 80:
            raise ValueError(
                f"Research objective {case_id!r} is too short to define a program"
            )
        anchors = {
            str(key): str(value).strip()
            for key, value in dict(data["expert_anchors"]).items()
        }
        missing_dimensions = sorted(_ALLOWED_DIMENSIONS - set(anchors))
        unknown_dimensions = sorted(set(anchors) - _ALLOWED_DIMENSIONS)
        if missing_dimensions or unknown_dimensions:
            raise ValueError(
                f"Invalid expert dimensions for {case_id}: "
                f"missing={missing_dimensions}, unknown={unknown_dimensions}"
            )
        budget = ResearchBudget.from_dict(dict(data["budget"]))
        directions = tuple(
            str(item).strip()
            for item in data["linear_control_directions"]
            if str(item).strip()
        )
        if len(directions) < budget.max_cycles:
            raise ValueError(
                f"{case_id} needs at least {budget.max_cycles} frozen linear "
                "control directions"
            )
        deliverables = tuple(
            str(item).strip() for item in data["deliverables"] if str(item).strip()
        )
        if not deliverables:
            raise ValueError(f"{case_id} has no deliverables")
        return cls(
            id=case_id,
            title=str(data["title"]).strip(),
            domain=str(data["domain"]).strip(),
            objective=objective,
            success_definition=str(data["success_definition"]).strip(),
            deliverables=deliverables,
            preferred_validators=tuple(
                str(item).strip()
                for item in data["preferred_validators"]
                if str(item).strip()
            ),
            resources=tuple(
                str(item).strip()
                for item in data.get("resources", [])
                if str(item).strip()
            ),
            linear_control_directions=directions,
            expert_anchors=anchors,
            budget=budget,
            tags=tuple(
                str(item).strip().lower()
                for item in data.get("tags", [])
                if str(item).strip()
            ),
        )

    def research_brief(self) -> str:
        """Return the single human prompt supplied to every architecture."""
        lines = [
            self.objective,
            "",
            "Success definition:",
            self.success_definition,
            "",
            "Required final deliverables:",
        ]
        lines.extend(f"- {item}" for item in self.deliverables)
        if self.resources:
            lines.extend(["", "Frozen resources:"])
            lines.extend(f"- {item}" for item in self.resources)
        if self.preferred_validators:
            lines.extend(["", "Available or preferred validators:"])
            lines.extend(f"- {item}" for item in self.preferred_validators)
        lines.extend(
            [
                "",
                "Work autonomously from this single objective. Generate competing "
                "falsifiable hypotheses, use external evidence to discriminate "
                "between them, preserve materially independent branches, and "
                "revise the research direction when evidence warrants it.",
            ]
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "domain": self.domain,
            "objective": self.objective,
            "success_definition": self.success_definition,
            "deliverables": list(self.deliverables),
            "preferred_validators": list(self.preferred_validators),
            "resources": list(self.resources),
            "linear_control_directions": list(self.linear_control_directions),
            "expert_anchors": dict(self.expert_anchors),
            "budget": self.budget.to_dict(),
            "tags": list(self.tags),
        }


def load_research_programs(
    case_root: Path | str = DEFAULT_CASE_ROOT,
) -> list[ResearchProgram]:
    root = Path(case_root)
    if not root.exists():
        raise FileNotFoundError(f"Research program directory not found: {root}")
    programs: list[ResearchProgram] = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        program = ResearchProgram.from_dict(data)
        programs.append(program)
    ids = [item.id for item in programs]
    if len(ids) != len(set(ids)):
        raise ValueError("Research program ids must be unique")
    return programs


def load_research_suite(
    suite_path: Path | str = DEFAULT_SUITE,
    *,
    case_root: Path | str = DEFAULT_CASE_ROOT,
) -> tuple[dict[str, Any], list[ResearchProgram]]:
    path = Path(suite_path)
    suite = json.loads(path.read_text(encoding="utf-8"))
    required = {"id", "schema_version", "configurations", "seeds", "cases"}
    missing = sorted(required - set(suite))
    if missing:
        raise ValueError(f"Research suite is missing fields: {missing}")
    catalog = {case.id: case for case in load_research_programs(case_root)}
    unknown = [case_id for case_id in suite["cases"] if case_id not in catalog]
    if unknown:
        raise ValueError(f"Research suite references unknown cases: {unknown}")
    selected = [catalog[case_id] for case_id in suite["cases"]]
    if not selected:
        raise ValueError("Research suite contains no cases")
    return suite, selected


def select_research_programs(
    programs: Iterable[ResearchProgram],
    *,
    only: Iterable[str] = (),
    tags: Iterable[str] = (),
) -> list[ResearchProgram]:
    selected_ids = {item for item in only if item}
    selected_tags = {item.lower() for item in tags if item}
    result = [
        case
        for case in programs
        if (not selected_ids or case.id in selected_ids)
        and (not selected_tags or selected_tags & set(case.tags))
    ]
    missing = selected_ids - {case.id for case in result}
    if missing:
        raise ValueError(f"Unknown or filtered research programs: {sorted(missing)}")
    return result


def suite_fingerprint(
    suite: dict[str, Any],
    programs: Iterable[ResearchProgram],
) -> str:
    """Fingerprint the protocol plus every selected public research brief."""
    payload = {
        "suite": suite,
        "programs": [case.to_dict() for case in programs],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


EXPERT_DIMENSIONS = tuple(sorted(_ALLOWED_DIMENSIONS))
