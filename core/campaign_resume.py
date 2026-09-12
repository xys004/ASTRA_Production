"""Stage 4: explicit campaign resume over the checkpoint and ledger.

Resuming a campaign means rebuilding the loop's working state after any
interruption — a crash, a machine change, or simply a new session — without
repeating episodes and without trusting anything but the ledger.  The
checkpoint is a validated accelerator, never an authority: when it is stale,
missing, or corrupt, resume falls back to a full replay and republishes a
fresh checkpoint atomically.  A truncated ledger tail blocks resumption until
it is explicitly archived, exactly as the first-slice contract demands.

``resume_campaign`` also recommends the next action deterministically so the
caller (a human, the dev interfaces of stage 5, or a future controller) never
has to guess where the loop stopped:

- ``empty``                  : no events yet; create the campaign first.
- ``activate_campaign``      : campaign exists but is still DRAFT.
- ``select_initial_branch``  : ACTIVE campaign, no ACTIVE branch, at least
                               one admissible candidate.
- ``campaign_step``          : ACTIVE campaign with an ACTIVE branch.
- ``await_human_review``     : PAUSED campaign, or ACTIVE with no viable
                               branch left.
- ``terminal``               : COMPLETED / EXHAUSTED / CANCELLED.
- ``repair_truncated_tail``  : the ledger tail must be archived before any
                               further writes.

No model, network, MCP, or remote calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.campaign_models import BranchStatus, CampaignStatus
from core.campaign_policy import CampaignState
from core.campaign_store import (
    CampaignStore,
    CheckpointError,
    HEALTH_TRUNCATED_TAIL,
    TruncatedTailError,
)

CHECKPOINT_VALID = "VALID"
CHECKPOINT_STALE_REBUILT = "STALE_REBUILT"
CHECKPOINT_MISSING_REBUILT = "MISSING_REBUILT"
CHECKPOINT_INVALID_REBUILT = "INVALID_REBUILT"
CHECKPOINT_NOT_REBUILT = "NOT_REBUILT"
CHECKPOINT_NONE = "NONE"


@dataclass(frozen=True)
class ResumeReport:
    campaign_id: str
    health: str
    next_action: str
    checkpoint_status: str
    campaign_status: str | None = None
    last_sequence: int = 0
    last_event_sha256: str | None = None
    active_branch_id: str | None = None
    admissible_branch_ids: tuple[str, ...] = ()
    unresolved_deliverables: tuple[str, ...] = ()
    episodes_recorded: int = 0
    decisions_recorded: int = 0
    last_decision: dict | None = None
    spent: dict | None = None
    remaining: dict | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "health": self.health,
            "next_action": self.next_action,
            "checkpoint_status": self.checkpoint_status,
            "campaign_status": self.campaign_status,
            "last_sequence": self.last_sequence,
            "last_event_sha256": self.last_event_sha256,
            "active_branch_id": self.active_branch_id,
            "admissible_branch_ids": list(self.admissible_branch_ids),
            "unresolved_deliverables": list(self.unresolved_deliverables),
            "episodes_recorded": self.episodes_recorded,
            "decisions_recorded": self.decisions_recorded,
            "last_decision": self.last_decision,
            "spent": self.spent,
            "remaining": self.remaining,
            "notes": list(self.notes),
        }


def _next_action(state: CampaignState) -> tuple[str, tuple[str, ...]]:
    if state.campaign is None:
        return "empty", ("no campaign has been created in this ledger",)
    status = state.campaign.status
    if status is CampaignStatus.DRAFT:
        return "activate_campaign", ()
    if status is CampaignStatus.PAUSED:
        return "await_human_review", ("the campaign is paused",)
    if status in {
        CampaignStatus.COMPLETED,
        CampaignStatus.EXHAUSTED,
        CampaignStatus.CANCELLED,
    }:
        return "terminal", (f"the campaign ended as {status.value}",)
    if state.active_branch_id() is not None:
        return "campaign_step", ()
    admissible = [
        branch_id
        for branch_id, branch in state.branches.items()
        if branch.status is BranchStatus.ADMISSIBLE
    ]
    if admissible:
        return "select_initial_branch", ()
    return "await_human_review", (
        "the campaign is ACTIVE but no branch is active or admissible",
    )


def resume_campaign(
    store: CampaignStore, *, rebuild_checkpoint: bool = True
) -> ResumeReport:
    """Rebuild working state from the ledger, using the checkpoint safely.

    ``rebuild_checkpoint=False`` keeps the call strictly read-only (no writer
    lock is taken), which is what a status query wants while another process
    may hold the campaign open.
    """
    # 1. Tail health gates everything: an unrepaired tail blocks resumption.
    #    Ledger corruption before the final line propagates fail-closed.
    try:
        result = store.replay()
    except TruncatedTailError:
        health = store.health()
        partial = store.replay(allow_truncated_tail=True)
        state = partial.state
        return ResumeReport(
            campaign_id=store.campaign_id,
            health=HEALTH_TRUNCATED_TAIL,
            next_action="repair_truncated_tail",
            checkpoint_status=CHECKPOINT_NOT_REBUILT,
            campaign_status=(
                state.campaign.status.value
                if state.campaign is not None
                else None
            ),
            last_sequence=partial.last_sequence,
            last_event_sha256=partial.last_event_sha256,
            episodes_recorded=len(state.episodes),
            decisions_recorded=len(state.decisions),
            notes=(
                f"ledger tail is truncated ({health.tail_bytes} bytes); "
                "archive it with archive_truncated_tail() before any "
                "further append",
            ),
        )

    state = result.state
    notes: list[str] = []

    # 2. Checkpoint validation: the ledger stays the authority.
    if result.last_sequence == 0:
        checkpoint_status = CHECKPOINT_NONE
    else:
        try:
            payload = store.load_checkpoint()
            if payload["last_sequence"] == result.last_sequence:
                checkpoint_status = CHECKPOINT_VALID
            else:
                checkpoint_status = (
                    CHECKPOINT_STALE_REBUILT
                    if rebuild_checkpoint
                    else CHECKPOINT_NOT_REBUILT
                )
                notes.append(
                    f"checkpoint stopped at sequence "
                    f"{payload['last_sequence']} of {result.last_sequence}"
                )
        except CheckpointError as exc:
            missing = "No checkpoint" in str(exc)
            if rebuild_checkpoint:
                checkpoint_status = (
                    CHECKPOINT_MISSING_REBUILT
                    if missing
                    else CHECKPOINT_INVALID_REBUILT
                )
            else:
                checkpoint_status = CHECKPOINT_NOT_REBUILT
            notes.append(f"checkpoint unusable: {exc}")
        if rebuild_checkpoint and checkpoint_status in {
            CHECKPOINT_STALE_REBUILT,
            CHECKPOINT_MISSING_REBUILT,
            CHECKPOINT_INVALID_REBUILT,
        }:
            store.write_checkpoint()

    # 3. Deterministic next action.
    next_action, action_notes = _next_action(state)
    notes.extend(action_notes)

    campaign = state.campaign
    last_decision = None
    if state.decisions:
        last_decision = list(state.decisions.values())[-1].to_dict()
    return ResumeReport(
        campaign_id=store.campaign_id,
        health=result.health.status,
        next_action=next_action,
        checkpoint_status=checkpoint_status,
        campaign_status=campaign.status.value if campaign else None,
        last_sequence=result.last_sequence,
        last_event_sha256=result.last_event_sha256,
        active_branch_id=state.active_branch_id(),
        admissible_branch_ids=tuple(
            branch_id
            for branch_id, branch in state.branches.items()
            if branch.status is BranchStatus.ADMISSIBLE
        ),
        unresolved_deliverables=(
            state.unresolved_deliverables() if campaign else ()
        ),
        episodes_recorded=len(state.episodes),
        decisions_recorded=len(state.decisions),
        last_decision=last_decision,
        spent=state.spent.to_dict() if campaign else None,
        remaining=state.remaining_budget().to_dict() if campaign else None,
        notes=tuple(notes),
    )
