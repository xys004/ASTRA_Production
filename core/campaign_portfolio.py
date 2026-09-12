"""Structured portfolio output from the ensemble synthesis (ASTRA 2.0 stage 1).

The ensemble synthesis historically merged every proposal into one consensus
conjecture, erasing minority proposals from structured state.  This module
implements the authorized stage-1 transformation: the synthesis additionally
emits one fenced ``astra-portfolio`` JSON block containing the selected atomic
claim plus up to three materially different alternatives, each with method
family, assumption delta, and the cheapest discriminating evidence plan.

Design rules carried over from the design contrast document
(``docs/architecture/ASTRA2_PREPRINT_2602.03837_CONTRAST.md``):

- R3: the selected candidate must state its ``crux`` — the exact blocking
  point or next discriminating obligation — which maps to the Claim's
  ``unresolved_obligations`` in the campaign domain layer.
- R4: exhausted method families can be forbidden explicitly; the prompt
  builders emit a "DO NOT use" constraint and violations are detected
  deterministically.

Parsing is fail-soft for the running cycle (a missing or invalid block is
recorded, never fatal), while portfolio *content* validation and record
conversion fail closed.  This module performs no model calls and never touches
the production checkout.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from core.campaign_models import (
    AssumptionDelta,
    Branch,
    BudgetVector,
    Campaign,
    CampaignModelError,
    Claim,
    ClaimType,
    EvidenceKind,
    EvidencePlan,
    PriorityVector,
    ensure_portable_text,
    new_record_id,
    validate_method_family,
)

PORTFOLIO_SCHEMA_VERSION = "astra-portfolio/0.1"
PORTFOLIO_FENCE_TAG = "astra-portfolio"
MAX_CANDIDATES = 4

_FENCE_RE = re.compile(
    r"```" + PORTFOLIO_FENCE_TAG + r"[ \t]*\r?\n(.*?)\r?\n?```",
    re.DOTALL,
)


class PortfolioError(ValueError):
    """A portfolio block failed fail-closed content validation."""


# Placeholder until the Navigator supplies real estimates in a later stage;
# never used for branch selection in stage 1.
NEUTRAL_PRIORITY_VECTOR = PriorityVector(
    information_gain=0.5,
    evidence_strength=0.0,
    methodological_independence=0.5,
    goal_advancement=0.5,
    estimated_cost=0.5,
    instability_risk=0.5,
)

DEFAULT_PLAN_COST = BudgetVector(
    cycles=1,
    model_calls=8,
    wall_seconds=1800,
    execution_seconds=300,
    human_interventions=0,
    remote_jobs=0,
)

DEFAULT_BRANCH_BUDGET = BudgetVector(
    cycles=4,
    model_calls=32,
    wall_seconds=7200,
    execution_seconds=1200,
    human_interventions=1,
    remote_jobs=2,
)


def _string_list(value: Any, field_name: str) -> tuple[str, ...]:
    """Tolerant boundary for model-authored lists: empty entries are dropped.

    The first live canary lost an entire valid portfolio because the model
    emitted one empty string inside ``quantifiers``.  Whitespace-only entries
    carry no semantics, so they are filtered here instead of rejecting the
    block; the strict record layer (``campaign_models``) stays fail-closed.
    """
    if not isinstance(value, (list, tuple)):
        raise PortfolioError(f"{field_name} must be a list of strings")
    return tuple(
        item for item in (str(entry).strip() for entry in value) if item
    )


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PortfolioError(f"{field_name} must be null or a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class PortfolioCandidate:
    """One claim candidate produced by the ensemble synthesis."""

    statement: str
    claim_type: ClaimType
    domain: str
    scope: str
    method_family: str
    material_difference: str
    assumption_delta: AssumptionDelta
    evidence_plan_description: str
    evidence_kind: EvidenceKind
    quantifiers: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    tolerance: str | None = None
    units: str | None = None
    deliverable: str | None = None
    direction: str | None = None
    crux: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self, "statement", ensure_portable_text("statement", self.statement)
            )
            object.__setattr__(
                self, "domain", ensure_portable_text("domain", self.domain)
            )
            object.__setattr__(
                self, "scope", ensure_portable_text("scope", self.scope)
            )
            validate_method_family(self.method_family)
            object.__setattr__(
                self,
                "material_difference",
                ensure_portable_text(
                    "material_difference", self.material_difference
                ),
            )
            object.__setattr__(
                self,
                "evidence_plan_description",
                ensure_portable_text(
                    "evidence_plan.description", self.evidence_plan_description
                ),
            )
        except CampaignModelError as exc:
            raise PortfolioError(str(exc)) from exc
        if not isinstance(self.claim_type, ClaimType):
            raise PortfolioError(f"Invalid claim_type: {self.claim_type!r}")
        if not isinstance(self.evidence_kind, EvidenceKind):
            raise PortfolioError(f"Invalid evidence kind: {self.evidence_kind!r}")
        if not isinstance(self.assumption_delta, AssumptionDelta):
            raise PortfolioError("assumption_delta must be an AssumptionDelta")
        object.__setattr__(
            self, "quantifiers", _string_list(self.quantifiers, "quantifiers")
        )
        object.__setattr__(
            self, "assumptions", _string_list(self.assumptions, "assumptions")
        )
        for name in ("tolerance", "units", "deliverable", "direction", "crux"):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioCandidate":
        if not isinstance(data, Mapping):
            raise PortfolioError("Portfolio candidate must be a JSON object")
        data = dict(data)
        required = {
            "statement",
            "claim_type",
            "domain",
            "scope",
            "method_family",
            "material_difference",
            "assumption_delta",
            "evidence_plan",
        }
        optional = {
            "quantifiers",
            "assumptions",
            "tolerance",
            "units",
            "deliverable",
            "direction",
            "crux",
        }
        missing = sorted(required - set(data))
        unknown = sorted(set(data) - required - optional)
        if missing or unknown:
            raise PortfolioError(
                f"Portfolio candidate fields invalid: missing={missing}, "
                f"unknown={unknown}"
            )
        try:
            claim_type = ClaimType(data["claim_type"])
        except ValueError as exc:
            raise PortfolioError(
                f"Unknown claim_type: {data['claim_type']!r}"
            ) from exc
        plan = data["evidence_plan"]
        if not isinstance(plan, Mapping) or set(plan) - {"description", "kind"}:
            raise PortfolioError(
                "evidence_plan must be an object with only "
                "'description' and 'kind'"
            )
        try:
            kind = EvidenceKind(plan.get("kind"))
        except ValueError as exc:
            raise PortfolioError(
                f"Unknown evidence kind: {plan.get('kind')!r}"
            ) from exc
        delta = data["assumption_delta"]
        if not isinstance(delta, Mapping) or set(delta) - {"added", "removed"}:
            raise PortfolioError(
                "assumption_delta must be an object with 'added' and 'removed'"
            )
        try:
            assumption_delta = AssumptionDelta(
                added=_string_list(delta.get("added", []), "assumption_delta.added"),
                removed=_string_list(
                    delta.get("removed", []), "assumption_delta.removed"
                ),
            )
        except CampaignModelError as exc:
            raise PortfolioError(str(exc)) from exc
        return cls(
            statement=data["statement"],
            claim_type=claim_type,
            domain=data["domain"],
            scope=data["scope"],
            method_family=str(data["method_family"]),
            material_difference=data["material_difference"],
            assumption_delta=assumption_delta,
            evidence_plan_description=plan.get("description", ""),
            evidence_kind=kind,
            quantifiers=tuple(data.get("quantifiers", ())),
            assumptions=tuple(data.get("assumptions", ())),
            tolerance=data.get("tolerance"),
            units=data.get("units"),
            deliverable=data.get("deliverable"),
            direction=data.get("direction"),
            crux=data.get("crux"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "claim_type": self.claim_type.value,
            "domain": self.domain,
            "scope": self.scope,
            "method_family": self.method_family,
            "material_difference": self.material_difference,
            "assumption_delta": self.assumption_delta.to_dict(),
            "evidence_plan": {
                "description": self.evidence_plan_description,
                "kind": self.evidence_kind.value,
            },
            "quantifiers": list(self.quantifiers),
            "assumptions": list(self.assumptions),
            "tolerance": self.tolerance,
            "units": self.units,
            "deliverable": self.deliverable,
            "direction": self.direction,
            "crux": self.crux,
        }


@dataclass(frozen=True)
class Portfolio:
    """Selected claim plus preserved, materially different alternatives."""

    selected: PortfolioCandidate
    alternatives: tuple[PortfolioCandidate, ...] = ()
    schema_version: str = PORTFOLIO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_SCHEMA_VERSION:
            raise PortfolioError(
                f"Unknown portfolio schema version {self.schema_version!r}; "
                f"expected {PORTFOLIO_SCHEMA_VERSION!r}"
            )
        if not isinstance(self.selected, PortfolioCandidate):
            raise PortfolioError("selected must be a PortfolioCandidate")
        alternatives = tuple(self.alternatives)
        for item in alternatives:
            if not isinstance(item, PortfolioCandidate):
                raise PortfolioError("alternatives must be PortfolioCandidates")
        object.__setattr__(self, "alternatives", alternatives)
        if len(self.candidates()) > MAX_CANDIDATES:
            raise PortfolioError(
                f"A portfolio holds at most {MAX_CANDIDATES} candidates "
                f"(progressive widening cap); got {len(self.candidates())}"
            )
        # Material difference is enforced structurally: no two candidates may
        # share a normalized method family.
        families = [item.method_family for item in self.candidates()]
        duplicates = sorted(
            {family for family in families if families.count(family) > 1}
        )
        if duplicates:
            raise PortfolioError(
                "Candidates must be materially different; duplicated method "
                f"families: {duplicates}"
            )
        if self.selected.crux is None:
            raise PortfolioError(
                "The selected candidate must state its crux: the exact "
                "blocking point or next discriminating obligation"
            )

    def candidates(self) -> tuple[PortfolioCandidate, ...]:
        return (self.selected, *self.alternatives)

    def method_families(self) -> tuple[str, ...]:
        return tuple(item.method_family for item in self.candidates())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Portfolio":
        if not isinstance(data, Mapping):
            raise PortfolioError("Portfolio must be a JSON object")
        data = dict(data)
        allowed = {"schema_version", "selected", "alternatives"}
        missing = sorted({"schema_version", "selected"} - set(data))
        unknown = sorted(set(data) - allowed)
        if missing or unknown:
            raise PortfolioError(
                f"Portfolio fields invalid: missing={missing}, unknown={unknown}"
            )
        alternatives = data.get("alternatives", [])
        if not isinstance(alternatives, (list, tuple)):
            raise PortfolioError("alternatives must be a list")
        return cls(
            selected=PortfolioCandidate.from_dict(data["selected"]),
            alternatives=tuple(
                PortfolioCandidate.from_dict(item) for item in alternatives
            ),
            schema_version=data["schema_version"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selected": self.selected.to_dict(),
            "alternatives": [item.to_dict() for item in self.alternatives],
        }


@dataclass(frozen=True)
class PortfolioParseResult:
    """Fail-soft parse outcome: the cycle never crashes on a bad block."""

    portfolio: Portfolio | None
    error: str | None
    conjecture_text: str
    raw_block: str | None = None


def extract_portfolio_block(text: str) -> tuple[str | None, str]:
    """Return (last fenced portfolio JSON, text with every block removed)."""
    if not isinstance(text, str) or not text:
        return None, text if isinstance(text, str) else ""
    matches = list(_FENCE_RE.finditer(text))
    if not matches:
        return None, text
    stripped = _FENCE_RE.sub("", text).strip()
    return matches[-1].group(1).strip(), stripped


def parse_portfolio(text: str) -> PortfolioParseResult:
    """Fail-soft: absent or invalid blocks are reported, never raised."""
    block, stripped = extract_portfolio_block(text)
    if block is None:
        return PortfolioParseResult(
            portfolio=None,
            error="portfolio block missing from synthesis output",
            conjecture_text=stripped,
        )
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        return PortfolioParseResult(
            portfolio=None,
            error=f"portfolio block is not valid JSON: {exc}",
            conjecture_text=stripped,
            raw_block=block,
        )
    try:
        portfolio = Portfolio.from_dict(data)
    except PortfolioError as exc:
        return PortfolioParseResult(
            portfolio=None,
            error=str(exc),
            conjecture_text=stripped,
            raw_block=block,
        )
    return PortfolioParseResult(
        portfolio=portfolio,
        error=None,
        conjecture_text=stripped,
        raw_block=block,
    )


def forbidden_family_violations(
    portfolio: Portfolio, forbidden_families: Iterable[str]
) -> tuple[str, ...]:
    """R4: method families already exhausted must not be proposed again."""
    forbidden = {str(item).strip().lower() for item in forbidden_families if item}
    return tuple(
        candidate.method_family
        for candidate in portfolio.candidates()
        if candidate.method_family.lower() in forbidden
    )


# ---------------------------------------------------------------------------
# Prompt builders (deterministic text; no model calls)
# ---------------------------------------------------------------------------


def negative_prompt_block(forbidden_families: Iterable[str]) -> str:
    """R4 constraint text; empty string when nothing is forbidden."""
    families = sorted(
        {str(item).strip() for item in forbidden_families if str(item).strip()}
    )
    if not families:
        return ""
    return (
        "The following method families are exhausted or refuted for this "
        "objective. DO NOT use them: "
        + ", ".join(families)
        + ". Reflect on your plan and choose materially different methods."
    )


def portfolio_instruction_block(
    *,
    deliverables: Iterable[str] = (),
    allowed_evidence_kinds: Iterable[EvidenceKind] = (),
    forbidden_families: Iterable[str] = (),
) -> str:
    """Instruction appended to the synthesis prompt to request the block."""
    claim_types = ", ".join(item.value for item in ClaimType)
    kinds = [item.value for item in allowed_evidence_kinds] or [
        item.value for item in EvidenceKind
    ]
    lines = [
        "STRUCTURED PORTFOLIO (mandatory addendum): after the final consensus "
        "conjecture, append exactly one fenced block tagged "
        f"```{PORTFOLIO_FENCE_TAG} containing one JSON object. This is the "
        "only exception to the no-meta-commentary rule. Preserve materially "
        "different minority proposals as alternatives instead of erasing "
        "them.",
        "JSON shape:",
        '{"schema_version": "' + PORTFOLIO_SCHEMA_VERSION + '",',
        ' "selected": {CANDIDATE}, "alternatives": [up to 3 CANDIDATEs]}',
        "CANDIDATE = {statement, claim_type, domain, scope, quantifiers, "
        "assumptions, tolerance, units, method_family, material_difference, "
        'assumption_delta: {"added": [], "removed": []}, '
        'evidence_plan: {"description", "kind"}, deliverable, direction, '
        "crux}",
        f"claim_type is one of: {claim_types}.",
        "evidence_plan.kind is one of: " + ", ".join(kinds) + ".",
        "method_family is a short lowercase snake_case family name; every "
        "candidate must use a different method family.",
        "evidence_plan.description states the cheapest evidence that "
        "discriminates this candidate from the others.",
        "The selected candidate MUST include crux: the exact blocking point "
        "or next discriminating obligation for this cycle.",
        "Only include alternatives that are materially different from the "
        "selected claim; an empty list is acceptable and honest.",
        "Never include empty strings inside list fields; omit entries you "
        "cannot fill.",
    ]
    deliverable_list = [str(item).strip() for item in deliverables if str(item).strip()]
    if deliverable_list:
        lines.append(
            "Each candidate's deliverable must be exactly one of: "
            + "; ".join(deliverable_list)
            + "."
        )
    negative = negative_prompt_block(forbidden_families)
    if negative:
        lines.append(negative)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversion into campaign domain records (stage-1 bridge to the first slice)
# ---------------------------------------------------------------------------


def portfolio_to_records(
    portfolio: Portfolio,
    campaign: Campaign,
    *,
    source_commit: str,
    created_at: str,
    id_factory: Callable[[str], str] = new_record_id,
    plan_cost: BudgetVector = DEFAULT_PLAN_COST,
    branch_budget: BudgetVector = DEFAULT_BRANCH_BUDGET,
    parent_branch_id: str | None = None,
    parent_episode_id: str | None = None,
) -> tuple[tuple[Claim, Branch], ...]:
    """Convert candidates into validated (Claim, Branch) pairs, selected first.

    Conversion fails closed: a candidate without a deliverable, or naming a
    deliverable the campaign does not define, is a contract violation.  The
    resulting Branch records start PROPOSED; admissibility stays the job of
    ``core.campaign_policy.evaluate_branch_admissibility``.
    """
    records: list[tuple[Claim, Branch]] = []
    for candidate in portfolio.candidates():
        if candidate.deliverable is None:
            raise PortfolioError(
                "Candidate cannot be converted without a deliverable "
                f"reference: {candidate.statement[:80]!r}"
            )
        if candidate.deliverable not in campaign.deliverables:
            raise PortfolioError(
                f"Candidate references unknown deliverable "
                f"{candidate.deliverable!r}; campaign defines "
                f"{list(campaign.deliverables)}"
            )
        try:
            claim = Claim(
                claim_id=id_factory("claim"),
                campaign_id=campaign.campaign_id,
                created_at=created_at,
                source_commit=source_commit,
                statement=candidate.statement,
                claim_type=candidate.claim_type,
                domain=candidate.domain,
                scope=candidate.scope,
                quantifiers=candidate.quantifiers,
                assumptions=candidate.assumptions,
                tolerance=candidate.tolerance,
                units=candidate.units,
                unresolved_obligations=(
                    (candidate.crux,) if candidate.crux else ()
                ),
            )
            branch = Branch(
                branch_id=id_factory("branch"),
                campaign_id=campaign.campaign_id,
                created_at=created_at,
                source_commit=source_commit,
                direction=candidate.direction or candidate.statement,
                method_family=candidate.method_family,
                material_difference=candidate.material_difference,
                assumption_delta=candidate.assumption_delta,
                evidence_plan=EvidencePlan(
                    description=candidate.evidence_plan_description,
                    kind=candidate.evidence_kind,
                    estimated_cost=plan_cost,
                ),
                priority_vector=NEUTRAL_PRIORITY_VECTOR,
                budget=branch_budget,
                deliverable_refs=(candidate.deliverable,),
                claim_refs=(claim.claim_id,),
                parent_branch_id=parent_branch_id,
                parent_episode_id=parent_episode_id,
            )
        except CampaignModelError as exc:
            raise PortfolioError(
                f"Candidate failed campaign record validation: {exc}"
            ) from exc
        records.append((claim, branch))
    return tuple(records)
