"""Domain records for ASTRA 2.0 research campaigns.

This module implements the frozen first-slice contract in
``docs/architecture/ASTRA2_IMPLEMENTATION_CONTRACT.md``: six persisted record
types (Campaign, Branch, Episode, Claim, Evidence, Decision), the event
envelope, closed status/type enums, explicit transition tables, and stable
versioned JSON serialization.  Every validation fails closed: unknown schema
versions, ids, states, transitions, or fields raise ``CampaignModelError``.

The module is pure domain code.  It performs no model calls, no network or
remote access, and never touches the production cycle.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = "astra-campaign/0.1"
EVENT_SCHEMA_VERSION = "astra-campaign-event/0.1"
CHECKPOINT_SCHEMA_VERSION = "astra-campaign-checkpoint/0.1"


class CampaignModelError(ValueError):
    """A campaign record failed fail-closed validation."""


# ---------------------------------------------------------------------------
# Identifiers, timestamps, and canonical hashing
# ---------------------------------------------------------------------------

ID_PREFIXES = {
    "campaign": "cmp",
    "branch": "brn",
    "episode": "epi",
    "claim": "clm",
    "evidence": "evd",
    "decision": "dec",
    "event": "evt",
}

_ID_RE = re.compile(r"^(cmp|brn|epi|clm|evd|dec|evt)_[a-z0-9][a-z0-9-]{3,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_METHOD_FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_MACHINE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\|/home/|/users/|/tmp/)")


def validate_record_id(value: Any, kind: str) -> str:
    prefix = ID_PREFIXES.get(kind)
    if prefix is None:
        raise CampaignModelError(f"Unknown record kind: {kind!r}")
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise CampaignModelError(f"Invalid {kind} id: {value!r}")
    if not value.startswith(prefix + "_"):
        raise CampaignModelError(
            f"{kind} id must use the {prefix}_ prefix: {value!r}"
        )
    return value


def new_record_id(kind: str) -> str:
    prefix = ID_PREFIXES.get(kind)
    if prefix is None:
        raise CampaignModelError(f"Unknown record kind: {kind!r}")
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def normalize_utc_timestamp(value: Any) -> str:
    """Validate an RFC 3339 UTC timestamp and normalize it to a Z suffix."""
    if not isinstance(value, str) or not value.strip():
        raise CampaignModelError(f"Timestamp must be a string: {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CampaignModelError(f"Invalid RFC 3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise CampaignModelError(f"Timestamp must be timezone-aware: {value!r}")
    if parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise CampaignModelError(f"Timestamp must be UTC: {value!r}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(payload: Any) -> str:
    """Canonical UTF-8 JSON: sorted keys, compact separators."""
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignModelError(f"Value is not JSON-serializable: {exc}") from exc


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise CampaignModelError(f"Invalid SHA-256 for {field_name}: {value!r}")
    return value


def validate_source_commit(value: Any) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.match(value):
        raise CampaignModelError(f"Invalid source commit: {value!r}")
    return value


def validate_method_family(value: Any) -> str:
    """Normalized lowercase method-family name shared by Branch and portfolio."""
    if not isinstance(value, str) or not _METHOD_FAMILY_RE.match(value):
        raise CampaignModelError(
            f"method_family must be normalized lowercase ([a-z0-9_-]): {value!r}"
        )
    return value


def ensure_portable_text(field_name: str, value: Any) -> str:
    """Reject machine-specific absolute paths inside portable content."""
    if not isinstance(value, str) or not value.strip():
        raise CampaignModelError(f"{field_name} must be a non-empty string")
    if _MACHINE_PATH_RE.search(value):
        raise CampaignModelError(
            f"{field_name} contains a machine-specific absolute path: {value!r}"
        )
    return value.strip()


def validate_relative_artifact_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignModelError(f"{field_name} must be a non-empty relative path")
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"(?i)^[a-z]:", normalized):
        raise CampaignModelError(
            f"{field_name} must be relative, not absolute: {value!r}"
        )
    if ".." in normalized.split("/"):
        raise CampaignModelError(f"{field_name} must not traverse upward: {value!r}")
    return normalized


def _require_schema_version(data: Mapping[str, Any], expected: str) -> None:
    found = data.get("schema_version")
    if found != expected:
        raise CampaignModelError(
            f"Unknown schema version {found!r}; expected {expected!r}"
        )


def _require_exact_keys(
    data: Mapping[str, Any], required: set[str], record: str
) -> None:
    missing = sorted(required - set(data))
    unknown = sorted(set(data) - required)
    if missing or unknown:
        raise CampaignModelError(
            f"{record} fields invalid: missing={missing}, unknown={unknown}"
        )


def _string_tuple(value: Any, field_name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CampaignModelError(f"{field_name} must be a list of strings")
    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise CampaignModelError(f"{field_name} must not contain empty entries")
    if not allow_empty and not items:
        raise CampaignModelError(f"{field_name} must not be empty")
    if len(set(items)) != len(items):
        raise CampaignModelError(f"{field_name} must not contain duplicates")
    return items


def _json_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CampaignModelError(f"{field_name} must be a mapping")
    result = {str(key): copy.deepcopy(val) for key, val in value.items()}
    canonical_json(result)  # fail closed on non-JSON content
    return result


# ---------------------------------------------------------------------------
# Closed enums
# ---------------------------------------------------------------------------


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class BranchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADMISSIBLE = "ADMISSIBLE"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REFUTED = "REFUTED"
    MERGED = "MERGED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class ClaimType(str, Enum):
    UNIVERSAL = "UNIVERSAL"
    EXISTENTIAL_OR_COUNTEREXAMPLE = "EXISTENTIAL_OR_COUNTEREXAMPLE"
    EQUIVALENCE_OR_DERIVATION = "EQUIVALENCE_OR_DERIVATION"
    NUMERICAL_PREDICTION = "NUMERICAL_PREDICTION"
    ALGORITHMIC_GUARANTEE = "ALGORITHMIC_GUARANTEE"
    SCOPED_EMPIRICAL = "SCOPED_EMPIRICAL"


class EvidenceKind(str, Enum):
    COUNTEREXAMPLE = "COUNTEREXAMPLE"
    NUMERICAL = "NUMERICAL"
    SYMBOLIC = "SYMBOLIC"
    FORMAL = "FORMAL"
    EMPIRICAL = "EMPIRICAL"
    LITERATURE = "LITERATURE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class EvidenceStrength(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    SCOPED = "SCOPED"
    CORROBORATED = "CORROBORATED"
    CERTIFIED = "CERTIFIED"


class EvidenceOutcome(str, Enum):
    """Outcome of one evidence record.

    ``SUPPORTS`` is the only positive outcome.  The remaining values are the
    contract's closed failure classes; only ``SCIENTIFIC_REFUTATION``
    scientifically refutes a claim.  An operational error, numerical
    instability, invalid validator, or formalization failure never does.
    """

    SUPPORTS = "SUPPORTS"
    SCIENTIFIC_REFUTATION = "SCIENTIFIC_REFUTATION"
    INVALID_VALIDATOR = "INVALID_VALIDATOR"
    OPERATIONAL_ERROR = "OPERATIONAL_ERROR"
    NUMERICAL_INSTABILITY = "NUMERICAL_INSTABILITY"
    FORMALIZATION_FAILURE = "FORMALIZATION_FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"


class DecisionAction(str, Enum):
    SELECT = "SELECT"
    CONTINUE = "CONTINUE"
    SPLIT = "SPLIT"
    PROMOTE = "PROMOTE"
    SUSPEND = "SUSPEND"
    MERGE = "MERGE"
    CLOSE = "CLOSE"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"


class OperationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClaimStatus(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class GoalCoverage(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class Actor(str, Enum):
    SYSTEM = "system"
    HUMAN = "human"
    CODEX = "codex"
    AGY = "agy"
    CLAUDE = "claude"
    ORACLE = "oracle"


def _parse_enum(enum_cls: type[Enum], value: Any, field_name: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = [item.value for item in enum_cls]
        raise CampaignModelError(
            f"Invalid {field_name} {value!r}; allowed: {allowed}"
        ) from exc


# ---------------------------------------------------------------------------
# Transition tables (fail-closed; terminal states have no outgoing edges)
# ---------------------------------------------------------------------------

CAMPAIGN_TRANSITIONS: dict[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.DRAFT: frozenset({CampaignStatus.ACTIVE}),
    CampaignStatus.ACTIVE: frozenset(
        {
            CampaignStatus.PAUSED,
            CampaignStatus.COMPLETED,
            CampaignStatus.EXHAUSTED,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.PAUSED: frozenset(
        {CampaignStatus.ACTIVE, CampaignStatus.CANCELLED}
    ),
    CampaignStatus.COMPLETED: frozenset(),
    CampaignStatus.EXHAUSTED: frozenset(),
    CampaignStatus.CANCELLED: frozenset(),
}

CAMPAIGN_TERMINAL_STATUSES = frozenset(
    {CampaignStatus.COMPLETED, CampaignStatus.EXHAUSTED, CampaignStatus.CANCELLED}
)

BRANCH_TRANSITIONS: dict[BranchStatus, frozenset[BranchStatus]] = {
    BranchStatus.PROPOSED: frozenset(
        {BranchStatus.ADMISSIBLE, BranchStatus.REJECTED}
    ),
    BranchStatus.ADMISSIBLE: frozenset(
        {BranchStatus.ACTIVE, BranchStatus.SUSPENDED}
    ),
    BranchStatus.ACTIVE: frozenset(
        {
            BranchStatus.SUSPENDED,
            BranchStatus.REFUTED,
            BranchStatus.MERGED,
            BranchStatus.EXHAUSTED,
            BranchStatus.CLOSED,
        }
    ),
    BranchStatus.SUSPENDED: frozenset(
        {
            BranchStatus.ACTIVE,
            BranchStatus.REFUTED,
            BranchStatus.MERGED,
            BranchStatus.EXHAUSTED,
            BranchStatus.CLOSED,
        }
    ),
    BranchStatus.REJECTED: frozenset(),
    BranchStatus.REFUTED: frozenset(),
    BranchStatus.MERGED: frozenset(),
    BranchStatus.EXHAUSTED: frozenset(),
    BranchStatus.CLOSED: frozenset(),
}

BRANCH_TERMINAL_STATUSES = frozenset(
    {
        BranchStatus.REJECTED,
        BranchStatus.REFUTED,
        BranchStatus.MERGED,
        BranchStatus.EXHAUSTED,
        BranchStatus.CLOSED,
    }
)


def assert_campaign_transition(
    current: CampaignStatus, new: CampaignStatus
) -> None:
    if new not in CAMPAIGN_TRANSITIONS[current]:
        raise CampaignModelError(
            f"Invalid campaign transition {current.value} -> {new.value}"
        )


def assert_branch_transition(current: BranchStatus, new: BranchStatus) -> None:
    if new not in BRANCH_TRANSITIONS[current]:
        raise CampaignModelError(
            f"Invalid branch transition {current.value} -> {new.value}"
        )


# ---------------------------------------------------------------------------
# Budgets and priority vectors
# ---------------------------------------------------------------------------

BUDGET_DIMENSIONS = (
    "cycles",
    "model_calls",
    "wall_seconds",
    "execution_seconds",
    "human_interventions",
    "remote_jobs",
)


@dataclass(frozen=True)
class BudgetVector:
    """Six independent budget dimensions; never collapsed into one number."""

    cycles: int = 0
    model_calls: int = 0
    wall_seconds: int = 0
    execution_seconds: int = 0
    human_interventions: int = 0
    remote_jobs: int = 0

    def __post_init__(self) -> None:
        for dimension in BUDGET_DIMENSIONS:
            value = getattr(self, dimension)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignModelError(
                    f"Budget dimension {dimension} must be a non-negative "
                    f"integer, got {value!r}"
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BudgetVector":
        _require_exact_keys(dict(data), set(BUDGET_DIMENSIONS), "BudgetVector")
        return cls(**{dimension: data[dimension] for dimension in BUDGET_DIMENSIONS})

    def to_dict(self) -> dict[str, int]:
        return {dimension: getattr(self, dimension) for dimension in BUDGET_DIMENSIONS}

    def add(self, other: "BudgetVector") -> "BudgetVector":
        return BudgetVector(
            **{
                dimension: getattr(self, dimension) + getattr(other, dimension)
                for dimension in BUDGET_DIMENSIONS
            }
        )

    def charge(self, dimension: str, amount: int) -> "BudgetVector":
        if dimension not in BUDGET_DIMENSIONS:
            raise CampaignModelError(f"Unknown budget dimension: {dimension!r}")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise CampaignModelError(
                f"Budget charge must be a positive integer, got {amount!r}"
            )
        values = self.to_dict()
        values[dimension] += amount
        return BudgetVector(**values)

    def covers(self, cost: "BudgetVector") -> bool:
        return all(
            getattr(self, dimension) >= getattr(cost, dimension)
            for dimension in BUDGET_DIMENSIONS
        )

    def remaining_after(self, spent: "BudgetVector") -> "BudgetVector":
        if not self.covers(spent):
            raise CampaignModelError("Spent budget exceeds limits")
        return BudgetVector(
            **{
                dimension: getattr(self, dimension) - getattr(spent, dimension)
                for dimension in BUDGET_DIMENSIONS
            }
        )


@dataclass(frozen=True)
class BudgetSnapshot:
    """Complete limits-plus-spent snapshot stored with every Decision."""

    limits: BudgetVector
    spent: BudgetVector

    def __post_init__(self) -> None:
        if not isinstance(self.limits, BudgetVector) or not isinstance(
            self.spent, BudgetVector
        ):
            raise CampaignModelError("Budget snapshot requires two BudgetVectors")
        if not self.limits.covers(self.spent):
            raise CampaignModelError("Budget snapshot spent exceeds limits")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BudgetSnapshot":
        _require_exact_keys(dict(data), {"limits", "spent"}, "BudgetSnapshot")
        return cls(
            limits=BudgetVector.from_dict(data["limits"]),
            spent=BudgetVector.from_dict(data["spent"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"limits": self.limits.to_dict(), "spent": self.spent.to_dict()}


PRIORITY_DIMENSIONS = (
    "information_gain",
    "evidence_strength",
    "methodological_independence",
    "goal_advancement",
    "estimated_cost",
    "instability_risk",
)


@dataclass(frozen=True)
class PriorityVector:
    """Visible, uncollapsed priority estimates for one branch."""

    information_gain: float
    evidence_strength: float
    methodological_independence: float
    goal_advancement: float
    estimated_cost: float
    instability_risk: float

    def __post_init__(self) -> None:
        for dimension in PRIORITY_DIMENSIONS:
            value = getattr(self, dimension)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CampaignModelError(
                    f"Priority dimension {dimension} must be numeric"
                )
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise CampaignModelError(
                    f"Priority dimension {dimension} must be finite and >= 0"
                )
            object.__setattr__(self, dimension, float(value))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PriorityVector":
        _require_exact_keys(dict(data), set(PRIORITY_DIMENSIONS), "PriorityVector")
        return cls(**{dimension: data[dimension] for dimension in PRIORITY_DIMENSIONS})

    def to_dict(self) -> dict[str, float]:
        return {
            dimension: getattr(self, dimension) for dimension in PRIORITY_DIMENSIONS
        }


@dataclass(frozen=True)
class AssumptionDelta:
    """Assumptions a branch adds or removes relative to its parent."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "added", _string_tuple(self.added, "assumption_delta.added",
                                         allow_empty=True)
        )
        object.__setattr__(
            self,
            "removed",
            _string_tuple(self.removed, "assumption_delta.removed", allow_empty=True),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssumptionDelta":
        _require_exact_keys(dict(data), {"added", "removed"}, "AssumptionDelta")
        return cls(added=tuple(data["added"]), removed=tuple(data["removed"]))

    def to_dict(self) -> dict[str, list[str]]:
        return {"added": list(self.added), "removed": list(self.removed)}


@dataclass(frozen=True)
class EvidencePlan:
    """Cheapest discriminating evidence plan for one branch."""

    description: str
    kind: EvidenceKind
    estimated_cost: BudgetVector

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "description",
            ensure_portable_text("evidence_plan.description", self.description),
        )
        if not isinstance(self.kind, EvidenceKind):
            raise CampaignModelError("evidence_plan.kind must be an EvidenceKind")
        if not isinstance(self.estimated_cost, BudgetVector):
            raise CampaignModelError(
                "evidence_plan.estimated_cost must be a BudgetVector"
            )
        if self.estimated_cost.cycles < 1:
            raise CampaignModelError(
                "evidence_plan.estimated_cost must include at least one cycle"
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidencePlan":
        _require_exact_keys(
            dict(data), {"description", "kind", "estimated_cost"}, "EvidencePlan"
        )
        return cls(
            description=data["description"],
            kind=_parse_enum(EvidenceKind, data["kind"], "evidence_plan.kind"),
            estimated_cost=BudgetVector.from_dict(data["estimated_cost"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "kind": self.kind.value,
            "estimated_cost": self.estimated_cost.to_dict(),
        }


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    created_at: str
    source_commit: str
    objective: str
    success_definition: str
    deliverables: tuple[str, ...]
    frozen_resources: dict[str, str]
    allowed_evidence_classes: tuple[EvidenceKind, ...]
    budget: BudgetVector
    status: CampaignStatus = CampaignStatus.DRAFT
    goal_coverage: GoalCoverage = GoalCoverage.NONE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.campaign_id, "campaign")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        object.__setattr__(
            self, "objective", ensure_portable_text("objective", self.objective)
        )
        object.__setattr__(
            self,
            "success_definition",
            ensure_portable_text("success_definition", self.success_definition),
        )
        deliverables = _string_tuple(
            self.deliverables, "deliverables", allow_empty=False
        )
        for item in deliverables:
            ensure_portable_text("deliverables entry", item)
        object.__setattr__(self, "deliverables", deliverables)
        if not isinstance(self.frozen_resources, Mapping):
            raise CampaignModelError("frozen_resources must be a mapping")
        resources: dict[str, str] = {}
        for name, digest in self.frozen_resources.items():
            resources[ensure_portable_text("frozen resource name", name)] = (
                validate_sha256(digest, f"frozen resource {name!r}")
            )
        object.__setattr__(self, "frozen_resources", resources)
        classes = tuple(self.allowed_evidence_classes)
        if not classes:
            raise CampaignModelError("allowed_evidence_classes must not be empty")
        if len(set(classes)) != len(classes):
            raise CampaignModelError("allowed_evidence_classes must be unique")
        for item in classes:
            if not isinstance(item, EvidenceKind):
                raise CampaignModelError(
                    f"allowed_evidence_classes entry is not an EvidenceKind: {item!r}"
                )
        object.__setattr__(self, "allowed_evidence_classes", classes)
        if not isinstance(self.budget, BudgetVector):
            raise CampaignModelError("budget must be a BudgetVector")
        if not isinstance(self.status, CampaignStatus):
            raise CampaignModelError(f"Invalid campaign status: {self.status!r}")
        if not isinstance(self.goal_coverage, GoalCoverage):
            raise CampaignModelError(f"Invalid goal coverage: {self.goal_coverage!r}")

    def with_status(self, new_status: CampaignStatus) -> "Campaign":
        assert_campaign_transition(self.status, new_status)
        return replace(self, status=new_status)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Campaign":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "campaign_id",
                "created_at",
                "source_commit",
                "objective",
                "success_definition",
                "deliverables",
                "frozen_resources",
                "allowed_evidence_classes",
                "budget",
                "status",
                "goal_coverage",
            },
            "Campaign",
        )
        return cls(
            campaign_id=data["campaign_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            objective=data["objective"],
            success_definition=data["success_definition"],
            deliverables=tuple(data["deliverables"]),
            frozen_resources=dict(data["frozen_resources"]),
            allowed_evidence_classes=tuple(
                _parse_enum(EvidenceKind, item, "allowed_evidence_classes")
                for item in data["allowed_evidence_classes"]
            ),
            budget=BudgetVector.from_dict(data["budget"]),
            status=_parse_enum(CampaignStatus, data["status"], "campaign status"),
            goal_coverage=_parse_enum(
                GoalCoverage, data["goal_coverage"], "goal_coverage"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "objective": self.objective,
            "success_definition": self.success_definition,
            "deliverables": list(self.deliverables),
            "frozen_resources": dict(self.frozen_resources),
            "allowed_evidence_classes": [
                item.value for item in self.allowed_evidence_classes
            ],
            "budget": self.budget.to_dict(),
            "status": self.status.value,
            "goal_coverage": self.goal_coverage.value,
        }


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Branch:
    branch_id: str
    campaign_id: str
    created_at: str
    source_commit: str
    direction: str
    method_family: str
    material_difference: str
    assumption_delta: AssumptionDelta
    evidence_plan: EvidencePlan
    priority_vector: PriorityVector
    budget: BudgetVector
    deliverable_refs: tuple[str, ...]
    claim_refs: tuple[str, ...] = ()
    parent_branch_id: str | None = None
    parent_episode_id: str | None = None
    status: BranchStatus = BranchStatus.PROPOSED
    decision_history: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.branch_id, "branch")
        validate_record_id(self.campaign_id, "campaign")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        object.__setattr__(
            self, "direction", ensure_portable_text("direction", self.direction)
        )
        validate_method_family(self.method_family)
        object.__setattr__(
            self,
            "material_difference",
            ensure_portable_text("material_difference", self.material_difference),
        )
        if not isinstance(self.assumption_delta, AssumptionDelta):
            raise CampaignModelError("assumption_delta must be an AssumptionDelta")
        if not isinstance(self.evidence_plan, EvidencePlan):
            raise CampaignModelError("evidence_plan must be an EvidencePlan")
        if not isinstance(self.priority_vector, PriorityVector):
            raise CampaignModelError("priority_vector must be a PriorityVector")
        if not isinstance(self.budget, BudgetVector):
            raise CampaignModelError("budget must be a BudgetVector")
        deliverable_refs = _string_tuple(
            self.deliverable_refs, "deliverable_refs", allow_empty=False
        )
        object.__setattr__(self, "deliverable_refs", deliverable_refs)
        claim_refs = tuple(self.claim_refs)
        for claim_id in claim_refs:
            validate_record_id(claim_id, "claim")
        if len(set(claim_refs)) != len(claim_refs):
            raise CampaignModelError("claim_refs must not contain duplicates")
        object.__setattr__(self, "claim_refs", claim_refs)
        if self.parent_branch_id is not None:
            validate_record_id(self.parent_branch_id, "branch")
            if self.parent_branch_id == self.branch_id:
                raise CampaignModelError("A branch cannot be its own parent")
        if self.parent_episode_id is not None:
            validate_record_id(self.parent_episode_id, "episode")
        if not isinstance(self.status, BranchStatus):
            raise CampaignModelError(f"Invalid branch status: {self.status!r}")
        history = tuple(self.decision_history)
        for decision_id in history:
            validate_record_id(decision_id, "decision")
        object.__setattr__(self, "decision_history", history)

    def with_status(
        self, new_status: BranchStatus, *, decision_id: str | None = None
    ) -> "Branch":
        assert_branch_transition(self.status, new_status)
        history = self.decision_history
        if decision_id is not None:
            validate_record_id(decision_id, "decision")
            history = (*history, decision_id)
        return replace(self, status=new_status, decision_history=history)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Branch":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "branch_id",
                "campaign_id",
                "created_at",
                "source_commit",
                "direction",
                "method_family",
                "material_difference",
                "assumption_delta",
                "evidence_plan",
                "priority_vector",
                "budget",
                "deliverable_refs",
                "claim_refs",
                "parent_branch_id",
                "parent_episode_id",
                "status",
                "decision_history",
            },
            "Branch",
        )
        return cls(
            branch_id=data["branch_id"],
            campaign_id=data["campaign_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            direction=data["direction"],
            method_family=data["method_family"],
            material_difference=data["material_difference"],
            assumption_delta=AssumptionDelta.from_dict(data["assumption_delta"]),
            evidence_plan=EvidencePlan.from_dict(data["evidence_plan"]),
            priority_vector=PriorityVector.from_dict(data["priority_vector"]),
            budget=BudgetVector.from_dict(data["budget"]),
            deliverable_refs=tuple(data["deliverable_refs"]),
            claim_refs=tuple(data["claim_refs"]),
            parent_branch_id=data["parent_branch_id"],
            parent_episode_id=data["parent_episode_id"],
            status=_parse_enum(BranchStatus, data["status"], "branch status"),
            decision_history=tuple(data["decision_history"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "branch_id": self.branch_id,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "direction": self.direction,
            "method_family": self.method_family,
            "material_difference": self.material_difference,
            "assumption_delta": self.assumption_delta.to_dict(),
            "evidence_plan": self.evidence_plan.to_dict(),
            "priority_vector": self.priority_vector.to_dict(),
            "budget": self.budget.to_dict(),
            "deliverable_refs": list(self.deliverable_refs),
            "claim_refs": list(self.claim_refs),
            "parent_branch_id": self.parent_branch_id,
            "parent_episode_id": self.parent_episode_id,
            "status": self.status.value,
            "decision_history": list(self.decision_history),
        }


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Episode:
    """One bounded use of the atomic worker.

    The five status axes stay separate: ``operation_status`` (axis 1),
    ``claim_status`` (axis 2), evidence kind/strength via ``evidence_refs``
    (axis 3), ``branch_status`` (axis 4), and ``goal_coverage`` (axis 5).
    The first slice stores Episodes but never invokes ``astra_cycle``.
    """

    episode_id: str
    campaign_id: str
    branch_id: str
    created_at: str
    source_commit: str
    inputs: dict[str, Any]
    providers: dict[str, str]
    actual_models: dict[str, str]
    budget: BudgetVector
    timings: dict[str, float]
    operation_status: OperationStatus
    claim_status: ClaimStatus
    branch_status: BranchStatus
    goal_coverage: GoalCoverage
    claim_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    checkpoint_artifact: str | None = None
    artifacts: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.episode_id, "episode")
        validate_record_id(self.campaign_id, "campaign")
        validate_record_id(self.branch_id, "branch")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        object.__setattr__(self, "inputs", _json_mapping(self.inputs, "inputs"))
        providers = _json_mapping(self.providers, "providers")
        if any(not isinstance(item, str) or not item for item in providers.values()):
            raise CampaignModelError("providers values must be non-empty strings")
        object.__setattr__(self, "providers", providers)
        models = _json_mapping(self.actual_models, "actual_models")
        if any(not isinstance(item, str) or not item for item in models.values()):
            raise CampaignModelError("actual_models values must be non-empty strings")
        object.__setattr__(self, "actual_models", models)
        if not isinstance(self.budget, BudgetVector):
            raise CampaignModelError("budget must be a BudgetVector")
        timings = _json_mapping(self.timings, "timings")
        for phase, seconds in timings.items():
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
                raise CampaignModelError(f"timings[{phase!r}] must be numeric")
            if not math.isfinite(float(seconds)) or float(seconds) < 0.0:
                raise CampaignModelError(
                    f"timings[{phase!r}] must be finite and >= 0"
                )
            timings[phase] = float(seconds)
        object.__setattr__(self, "timings", timings)
        if not isinstance(self.operation_status, OperationStatus):
            raise CampaignModelError(
                f"Invalid operation status: {self.operation_status!r}"
            )
        if not isinstance(self.claim_status, ClaimStatus):
            raise CampaignModelError(f"Invalid claim status: {self.claim_status!r}")
        if not isinstance(self.branch_status, BranchStatus):
            raise CampaignModelError(f"Invalid branch status: {self.branch_status!r}")
        if not isinstance(self.goal_coverage, GoalCoverage):
            raise CampaignModelError(f"Invalid goal coverage: {self.goal_coverage!r}")
        claim_refs = tuple(self.claim_refs)
        for claim_id in claim_refs:
            validate_record_id(claim_id, "claim")
        object.__setattr__(self, "claim_refs", claim_refs)
        evidence_refs = tuple(self.evidence_refs)
        for evidence_id in evidence_refs:
            validate_record_id(evidence_id, "evidence")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        if self.checkpoint_artifact is not None:
            object.__setattr__(
                self,
                "checkpoint_artifact",
                validate_relative_artifact_path(
                    self.checkpoint_artifact, "checkpoint_artifact"
                ),
            )
        artifacts = tuple(
            validate_relative_artifact_path(item, "artifacts entry")
            for item in self.artifacts
        )
        object.__setattr__(self, "artifacts", artifacts)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Episode":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "episode_id",
                "campaign_id",
                "branch_id",
                "created_at",
                "source_commit",
                "inputs",
                "providers",
                "actual_models",
                "budget",
                "timings",
                "operation_status",
                "claim_status",
                "branch_status",
                "goal_coverage",
                "claim_refs",
                "evidence_refs",
                "checkpoint_artifact",
                "artifacts",
            },
            "Episode",
        )
        return cls(
            episode_id=data["episode_id"],
            campaign_id=data["campaign_id"],
            branch_id=data["branch_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            inputs=dict(data["inputs"]),
            providers=dict(data["providers"]),
            actual_models=dict(data["actual_models"]),
            budget=BudgetVector.from_dict(data["budget"]),
            timings=dict(data["timings"]),
            operation_status=_parse_enum(
                OperationStatus, data["operation_status"], "operation_status"
            ),
            claim_status=_parse_enum(
                ClaimStatus, data["claim_status"], "claim_status"
            ),
            branch_status=_parse_enum(
                BranchStatus, data["branch_status"], "branch_status"
            ),
            goal_coverage=_parse_enum(
                GoalCoverage, data["goal_coverage"], "goal_coverage"
            ),
            claim_refs=tuple(data["claim_refs"]),
            evidence_refs=tuple(data["evidence_refs"]),
            checkpoint_artifact=data["checkpoint_artifact"],
            artifacts=tuple(data["artifacts"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "campaign_id": self.campaign_id,
            "branch_id": self.branch_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "inputs": copy.deepcopy(self.inputs),
            "providers": dict(self.providers),
            "actual_models": dict(self.actual_models),
            "budget": self.budget.to_dict(),
            "timings": dict(self.timings),
            "operation_status": self.operation_status.value,
            "claim_status": self.claim_status.value,
            "branch_status": self.branch_status.value,
            "goal_coverage": self.goal_coverage.value,
            "claim_refs": list(self.claim_refs),
            "evidence_refs": list(self.evidence_refs),
            "checkpoint_artifact": self.checkpoint_artifact,
            "artifacts": list(self.artifacts),
        }


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

_FINGERPRINT_FIELDS = (
    "statement",
    "domain",
    "quantifiers",
    "assumptions",
    "tolerance",
    "units",
    "scope",
)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    campaign_id: str
    created_at: str
    source_commit: str
    statement: str
    claim_type: ClaimType
    domain: str
    scope: str
    quantifiers: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    tolerance: str | None = None
    units: str | None = None
    unresolved_obligations: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.claim_id, "claim")
        validate_record_id(self.campaign_id, "campaign")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        object.__setattr__(
            self, "statement", ensure_portable_text("statement", self.statement)
        )
        if not isinstance(self.claim_type, ClaimType):
            raise CampaignModelError(f"Invalid claim type: {self.claim_type!r}")
        object.__setattr__(
            self, "domain", ensure_portable_text("domain", self.domain)
        )
        object.__setattr__(self, "scope", ensure_portable_text("scope", self.scope))
        object.__setattr__(
            self,
            "quantifiers",
            _string_tuple(self.quantifiers, "quantifiers", allow_empty=True),
        )
        object.__setattr__(
            self,
            "assumptions",
            _string_tuple(self.assumptions, "assumptions", allow_empty=True),
        )
        for name in ("tolerance", "units"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise CampaignModelError(f"{name} must be None or a non-empty string")
        if self.claim_type is ClaimType.NUMERICAL_PREDICTION and (
            self.tolerance is None or self.units is None
        ):
            raise CampaignModelError(
                "A NUMERICAL_PREDICTION claim requires explicit tolerance and units"
            )
        object.__setattr__(
            self,
            "unresolved_obligations",
            _string_tuple(
                self.unresolved_obligations,
                "unresolved_obligations",
                allow_empty=True,
            ),
        )

    def fingerprint(self) -> str:
        """Canonical structured fingerprint; never a bare text hash."""
        return canonical_sha256(
            {
                "statement": self.statement,
                "domain": self.domain,
                "quantifiers": list(self.quantifiers),
                "assumptions": list(self.assumptions),
                "tolerance": self.tolerance,
                "units": self.units,
                "scope": self.scope,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Claim":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        declared_fingerprint = data.pop("fingerprint", None)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "claim_id",
                "campaign_id",
                "created_at",
                "source_commit",
                "statement",
                "claim_type",
                "domain",
                "scope",
                "quantifiers",
                "assumptions",
                "tolerance",
                "units",
                "unresolved_obligations",
            },
            "Claim",
        )
        claim = cls(
            claim_id=data["claim_id"],
            campaign_id=data["campaign_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            statement=data["statement"],
            claim_type=_parse_enum(ClaimType, data["claim_type"], "claim_type"),
            domain=data["domain"],
            scope=data["scope"],
            quantifiers=tuple(data["quantifiers"]),
            assumptions=tuple(data["assumptions"]),
            tolerance=data["tolerance"],
            units=data["units"],
            unresolved_obligations=tuple(data["unresolved_obligations"]),
        )
        if declared_fingerprint is not None and (
            declared_fingerprint != claim.fingerprint()
        ):
            raise CampaignModelError(
                f"Claim fingerprint mismatch for {claim.claim_id}"
            )
        return claim

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "statement": self.statement,
            "claim_type": self.claim_type.value,
            "domain": self.domain,
            "scope": self.scope,
            "quantifiers": list(self.quantifiers),
            "assumptions": list(self.assumptions),
            "tolerance": self.tolerance,
            "units": self.units,
            "unresolved_obligations": list(self.unresolved_obligations),
            "fingerprint": self.fingerprint(),
        }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

REQUIRED_EVIDENCE_METADATA: dict[EvidenceKind, tuple[str, ...]] = {
    EvidenceKind.COUNTEREXAMPLE: (),
    EvidenceKind.NUMERICAL: ("precision", "convergence", "stability"),
    EvidenceKind.SYMBOLIC: (),
    EvidenceKind.FORMAL: ("kernel",),
    EvidenceKind.EMPIRICAL: ("replication",),
    EvidenceKind.LITERATURE: ("source",),
    EvidenceKind.HUMAN_REVIEW: (),
}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    campaign_id: str
    created_at: str
    source_commit: str
    claim_ids: tuple[str, ...]
    kind: EvidenceKind
    strength: EvidenceStrength
    scope: str
    engine: str
    outcome: EvidenceOutcome
    artifact_hashes: dict[str, str]
    independence_links: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.evidence_id, "evidence")
        validate_record_id(self.campaign_id, "campaign")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        claim_ids = tuple(self.claim_ids)
        if not claim_ids:
            raise CampaignModelError(
                "Evidence must state exactly which claim ids it tests"
            )
        for claim_id in claim_ids:
            validate_record_id(claim_id, "claim")
        if len(set(claim_ids)) != len(claim_ids):
            raise CampaignModelError("claim_ids must not contain duplicates")
        object.__setattr__(self, "claim_ids", claim_ids)
        if not isinstance(self.kind, EvidenceKind):
            raise CampaignModelError(f"Invalid evidence kind: {self.kind!r}")
        if not isinstance(self.strength, EvidenceStrength):
            raise CampaignModelError(f"Invalid evidence strength: {self.strength!r}")
        object.__setattr__(self, "scope", ensure_portable_text("scope", self.scope))
        if not isinstance(self.engine, str) or not self.engine.strip():
            raise CampaignModelError("engine must be a non-empty string")
        object.__setattr__(self, "engine", self.engine.strip())
        if not isinstance(self.outcome, EvidenceOutcome):
            raise CampaignModelError(f"Invalid evidence outcome: {self.outcome!r}")
        if not isinstance(self.artifact_hashes, Mapping):
            raise CampaignModelError("artifact_hashes must be a mapping")
        hashes: dict[str, str] = {}
        for path, digest in self.artifact_hashes.items():
            hashes[validate_relative_artifact_path(path, "artifact path")] = (
                validate_sha256(digest, f"artifact {path!r}")
            )
        object.__setattr__(self, "artifact_hashes", hashes)
        links = tuple(self.independence_links)
        for link in links:
            validate_record_id(link, "evidence")
            if link == self.evidence_id:
                raise CampaignModelError(
                    "Evidence cannot declare itself as an independence link"
                )
        if len(set(links)) != len(links):
            raise CampaignModelError("independence_links must not contain duplicates")
        object.__setattr__(self, "independence_links", links)
        metadata = _json_mapping(self.metadata, "metadata")
        missing = [
            key
            for key in REQUIRED_EVIDENCE_METADATA[self.kind]
            if key not in metadata
        ]
        if missing:
            raise CampaignModelError(
                f"{self.kind.value} evidence requires metadata keys: {missing}"
            )
        object.__setattr__(self, "metadata", metadata)

    @property
    def is_scientific_refutation(self) -> bool:
        return self.outcome is EvidenceOutcome.SCIENTIFIC_REFUTATION

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Evidence":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "evidence_id",
                "campaign_id",
                "created_at",
                "source_commit",
                "claim_ids",
                "kind",
                "strength",
                "scope",
                "engine",
                "outcome",
                "artifact_hashes",
                "independence_links",
                "metadata",
            },
            "Evidence",
        )
        return cls(
            evidence_id=data["evidence_id"],
            campaign_id=data["campaign_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            claim_ids=tuple(data["claim_ids"]),
            kind=_parse_enum(EvidenceKind, data["kind"], "evidence kind"),
            strength=_parse_enum(
                EvidenceStrength, data["strength"], "evidence strength"
            ),
            scope=data["scope"],
            engine=data["engine"],
            outcome=_parse_enum(EvidenceOutcome, data["outcome"], "evidence outcome"),
            artifact_hashes=dict(data["artifact_hashes"]),
            independence_links=tuple(data["independence_links"]),
            metadata=dict(data["metadata"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "claim_ids": list(self.claim_ids),
            "kind": self.kind.value,
            "strength": self.strength.value,
            "scope": self.scope,
            "engine": self.engine,
            "outcome": self.outcome.value,
            "artifact_hashes": dict(self.artifact_hashes),
            "independence_links": list(self.independence_links),
            "metadata": copy.deepcopy(self.metadata),
        }


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

PROMOTING_ACTIONS = frozenset(
    {
        DecisionAction.SELECT,
        DecisionAction.CONTINUE,
        DecisionAction.SPLIT,
        DecisionAction.PROMOTE,
        DecisionAction.MERGE,
    }
)


@dataclass(frozen=True)
class Decision:
    decision_id: str
    campaign_id: str
    created_at: str
    source_commit: str
    action: DecisionAction
    policy_result: dict[str, Any]
    reasons: tuple[str, ...]
    budget_snapshot: BudgetSnapshot
    subject_branch_id: str | None = None
    model_recommendation: dict[str, Any] | None = None
    alternatives_considered: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown schema version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        validate_record_id(self.decision_id, "decision")
        validate_record_id(self.campaign_id, "campaign")
        object.__setattr__(
            self, "created_at", normalize_utc_timestamp(self.created_at)
        )
        validate_source_commit(self.source_commit)
        if not isinstance(self.action, DecisionAction):
            raise CampaignModelError(f"Invalid decision action: {self.action!r}")
        policy_result = _json_mapping(self.policy_result, "policy_result")
        if not isinstance(policy_result.get("hard_gates_passed"), bool):
            raise CampaignModelError(
                "policy_result must record the deterministic boolean "
                "'hard_gates_passed'"
            )
        object.__setattr__(self, "policy_result", policy_result)
        if (
            self.action in PROMOTING_ACTIONS
            and policy_result["hard_gates_passed"] is False
        ):
            raise CampaignModelError(
                "A model recommendation cannot override a failed hard gate: "
                f"{self.action.value} requires hard_gates_passed=true"
            )
        object.__setattr__(
            self, "reasons", _string_tuple(self.reasons, "reasons", allow_empty=False)
        )
        if not isinstance(self.budget_snapshot, BudgetSnapshot):
            raise CampaignModelError("budget_snapshot must be a BudgetSnapshot")
        if self.subject_branch_id is not None:
            validate_record_id(self.subject_branch_id, "branch")
        if self.model_recommendation is not None:
            object.__setattr__(
                self,
                "model_recommendation",
                _json_mapping(self.model_recommendation, "model_recommendation"),
            )
        alternatives = tuple(self.alternatives_considered)
        for branch_id in alternatives:
            validate_record_id(branch_id, "branch")
        if len(set(alternatives)) != len(alternatives):
            raise CampaignModelError(
                "alternatives_considered must not contain duplicates"
            )
        object.__setattr__(self, "alternatives_considered", alternatives)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Decision":
        data = dict(data)
        _require_schema_version(data, SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "decision_id",
                "campaign_id",
                "created_at",
                "source_commit",
                "action",
                "policy_result",
                "reasons",
                "budget_snapshot",
                "subject_branch_id",
                "model_recommendation",
                "alternatives_considered",
            },
            "Decision",
        )
        recommendation = data["model_recommendation"]
        return cls(
            decision_id=data["decision_id"],
            campaign_id=data["campaign_id"],
            created_at=data["created_at"],
            source_commit=data["source_commit"],
            action=_parse_enum(DecisionAction, data["action"], "decision action"),
            policy_result=dict(data["policy_result"]),
            reasons=tuple(data["reasons"]),
            budget_snapshot=BudgetSnapshot.from_dict(data["budget_snapshot"]),
            subject_branch_id=data["subject_branch_id"],
            model_recommendation=(
                dict(recommendation) if recommendation is not None else None
            ),
            alternatives_considered=tuple(data["alternatives_considered"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "action": self.action.value,
            "policy_result": copy.deepcopy(self.policy_result),
            "reasons": list(self.reasons),
            "budget_snapshot": self.budget_snapshot.to_dict(),
            "subject_branch_id": self.subject_branch_id,
            "model_recommendation": copy.deepcopy(self.model_recommendation),
            "alternatives_considered": list(self.alternatives_considered),
        }


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------

EVENT_TYPES = (
    "CAMPAIGN_CREATED",
    "CAMPAIGN_STATUS_CHANGED",
    "DELIVERABLE_RESOLVED",
    "BRANCH_CREATED",
    "BRANCH_STATUS_CHANGED",
    "CLAIM_RECORDED",
    "EVIDENCE_RECORDED",
    "EPISODE_RECORDED",
    "DECISION_RECORDED",
    "BUDGET_CHARGED",
)


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    campaign_id: str
    sequence: int
    event_type: str
    occurred_at: str
    source_commit: str
    actor: Actor
    payload: dict[str, Any]
    previous_event_sha256: str | None
    event_sha256: str
    schema_version: str = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise CampaignModelError(
                f"Unknown event schema version {self.schema_version!r}; "
                f"expected {EVENT_SCHEMA_VERSION!r}"
            )
        validate_record_id(self.event_id, "event")
        validate_record_id(self.campaign_id, "campaign")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise CampaignModelError(
                f"Event sequence must be an integer >= 1, got {self.sequence!r}"
            )
        if self.event_type not in EVENT_TYPES:
            raise CampaignModelError(f"Unknown event type: {self.event_type!r}")
        object.__setattr__(
            self, "occurred_at", normalize_utc_timestamp(self.occurred_at)
        )
        validate_source_commit(self.source_commit)
        if not isinstance(self.actor, Actor):
            raise CampaignModelError(f"Invalid actor: {self.actor!r}")
        object.__setattr__(self, "payload", _json_mapping(self.payload, "payload"))
        if self.sequence == 1:
            if self.previous_event_sha256 is not None:
                raise CampaignModelError(
                    "The first event must not link to a previous hash"
                )
        else:
            validate_sha256(self.previous_event_sha256, "previous_event_sha256")
        expected = canonical_sha256(self.core_dict())
        if self.event_sha256 != expected:
            raise CampaignModelError(
                f"Event {self.event_id} hash mismatch: stored "
                f"{self.event_sha256!r}, canonical {expected!r}"
            )

    def core_dict(self) -> dict[str, Any]:
        """The canonical envelope content covered by ``event_sha256``."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "campaign_id": self.campaign_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "source_commit": self.source_commit,
            "actor": self.actor.value,
            "payload": self.payload,
            "previous_event_sha256": self.previous_event_sha256,
        }

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        campaign_id: str,
        sequence: int,
        event_type: str,
        occurred_at: str,
        source_commit: str,
        actor: Actor,
        payload: Mapping[str, Any],
        previous_event_sha256: str | None,
    ) -> "EventEnvelope":
        core = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "campaign_id": campaign_id,
            "sequence": sequence,
            "event_type": event_type,
            "occurred_at": normalize_utc_timestamp(occurred_at),
            "source_commit": source_commit,
            "actor": actor.value if isinstance(actor, Actor) else actor,
            "payload": _json_mapping(payload, "payload"),
            "previous_event_sha256": previous_event_sha256,
        }
        return cls.from_dict({**core, "event_sha256": canonical_sha256(core)})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventEnvelope":
        data = dict(data)
        _require_schema_version(data, EVENT_SCHEMA_VERSION)
        _require_exact_keys(
            data,
            {
                "schema_version",
                "event_id",
                "campaign_id",
                "sequence",
                "event_type",
                "occurred_at",
                "source_commit",
                "actor",
                "payload",
                "previous_event_sha256",
                "event_sha256",
            },
            "EventEnvelope",
        )
        return cls(
            event_id=data["event_id"],
            campaign_id=data["campaign_id"],
            sequence=data["sequence"],
            event_type=data["event_type"],
            occurred_at=data["occurred_at"],
            source_commit=data["source_commit"],
            actor=_parse_enum(Actor, data["actor"], "actor"),
            payload=dict(data["payload"]),
            previous_event_sha256=data["previous_event_sha256"],
            event_sha256=data["event_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.core_dict(), "event_sha256": self.event_sha256}
