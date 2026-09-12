"""Append-only local persistence for ASTRA 2.0 campaigns.

Implements the storage half of the first-slice contract: one
``events.jsonl`` ledger per campaign, canonical hash-chained envelopes,
fail-closed replay, explicit ``TRUNCATED_TAIL`` recovery that blocks appends
until the tail is archived, atomic ``checkpoint.json`` publication via a
temporary file plus ``os.replace``, and a single-writer lock.  The ledger is
always the authority; checkpoints are derived views.

The store performs no model, network, MCP, or remote calls.  The first slice
re-reads and replays the ledger on every append: correctness and auditability
over throughput, which is appropriate at campaign scale.
"""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core import campaign_policy
from core.campaign_models import (
    Actor,
    CHECKPOINT_SCHEMA_VERSION,
    CampaignModelError,
    EventEnvelope,
    canonical_json,
    new_record_id,
    normalize_utc_timestamp,
    utc_now_iso,
    validate_record_id,
    validate_source_commit,
)
from core.campaign_policy import CampaignPolicyError, CampaignState
from core.runtime_resources import _pid_alive

EVENTS_FILENAME = "events.jsonl"
CHECKPOINT_FILENAME = "checkpoint.json"
LOCK_FILENAME = "writer.lock"

HEALTH_EMPTY = "EMPTY"
HEALTH_HEALTHY = "HEALTHY"
HEALTH_TRUNCATED_TAIL = "TRUNCATED_TAIL"


class CampaignStoreError(RuntimeError):
    """Base error for campaign persistence failures."""


class LedgerCorruptionError(CampaignStoreError):
    """Corruption before the final ledger line; always fails closed."""


class TruncatedTailError(CampaignStoreError):
    """The final ledger line is incomplete; appends are blocked."""


class SingleWriterError(CampaignStoreError):
    """A second simultaneous writer was rejected."""


class CheckpointError(CampaignStoreError):
    """A checkpoint failed validation against the authoritative ledger."""


@dataclass(frozen=True)
class LedgerHealth:
    status: str
    valid_events: int
    tail_bytes: int


@dataclass(frozen=True)
class ReplayResult:
    state: CampaignState
    health: LedgerHealth
    last_sequence: int
    last_event_sha256: str | None


class CampaignStore:
    """Single-writer, append-only store for one campaign ledger."""

    def __init__(
        self, root: Path | str, campaign_id: str, *, source_commit: str
    ) -> None:
        self.campaign_id = validate_record_id(campaign_id, "campaign")
        self.source_commit = validate_source_commit(source_commit)
        self.root = Path(root)
        self.campaign_dir = self.root / self.campaign_id
        self.events_path = self.campaign_dir / EVENTS_FILENAME
        self.checkpoint_path = self.campaign_dir / CHECKPOINT_FILENAME
        self.lock_path = self.campaign_dir / LOCK_FILENAME
        self._lock_fd: int | None = None

    # -- writer lock -------------------------------------------------------

    def _lock_holder_pid(self) -> int | None:
        """The pid recorded in the lock file, if it is readable."""
        try:
            for line in self.lock_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("pid="):
                    return int(line.partition("=")[2].strip())
        except (OSError, ValueError):
            return None
        return None

    def _acquire_writer(self) -> None:
        if self._lock_fd is not None:
            return
        self.campaign_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(
                    self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
            except FileExistsError as exc:
                # A single-writer lock with no liveness check turns any crash
                # into a permanently wedged campaign, which a long-running
                # research programme cannot afford - it bit twice on 2026-08-16,
                # once from a script that raised mid-append and once from one
                # that never called close(). The cycle lock in
                # core/runtime_resources.py already solves this the same way, so
                # the behaviour is consistent rather than new.
                holder = self._lock_holder_pid()
                if attempt == 0 and (holder is None or not _pid_alive(holder)):
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(self.lock_path)
                    continue
                raise SingleWriterError(
                    f"Another writer (pid {holder}) holds {self.lock_path}; "
                    "the first slice is single-writer"
                ) from exc
            os.write(
                fd, f"pid={os.getpid()}\nacquired={utc_now_iso()}\n".encode()
            )
            self._lock_fd = fd
            return

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.lock_path)

    def __enter__(self) -> "CampaignStore":
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()

    # -- ledger reading ----------------------------------------------------

    def _read_envelopes(self) -> tuple[list[EventEnvelope], LedgerHealth]:
        if not self.events_path.exists():
            return [], LedgerHealth(HEALTH_EMPTY, 0, 0)
        raw = self.events_path.read_bytes()
        if not raw:
            return [], LedgerHealth(HEALTH_EMPTY, 0, 0)

        # Split into newline-terminated segments; any bytes after the final
        # newline are an incomplete tail by definition.
        segments: list[bytes] = []
        tail = b""
        remainder = raw
        while True:
            index = remainder.find(b"\n")
            if index < 0:
                tail = remainder
                break
            segments.append(remainder[: index + 1])
            remainder = remainder[index + 1 :]

        parsed: list[dict[str, Any]] = []
        tail_bytes = len(tail)
        for position, segment in enumerate(segments):
            text = segment.decode("utf-8", errors="replace").strip()
            if not text:
                raise LedgerCorruptionError(
                    f"Blank ledger line at position {position + 1}"
                )
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                is_final_segment = position == len(segments) - 1 and not tail
                if is_final_segment:
                    tail_bytes = len(segment)
                    break
                raise LedgerCorruptionError(
                    f"Corrupt ledger line at position {position + 1}: {exc}"
                ) from exc
            parsed.append(data)

        envelopes: list[EventEnvelope] = []
        for position, data in enumerate(parsed):
            try:
                envelope = EventEnvelope.from_dict(data)
            except CampaignModelError as exc:
                raise LedgerCorruptionError(
                    f"Invalid envelope at position {position + 1}: {exc}"
                ) from exc
            if envelope.campaign_id != self.campaign_id:
                raise LedgerCorruptionError(
                    f"Envelope at position {position + 1} belongs to "
                    f"{envelope.campaign_id}, not {self.campaign_id}"
                )
            envelopes.append(envelope)

        if tail_bytes:
            health = LedgerHealth(
                HEALTH_TRUNCATED_TAIL, len(envelopes), tail_bytes
            )
        elif envelopes:
            health = LedgerHealth(HEALTH_HEALTHY, len(envelopes), 0)
        else:
            health = LedgerHealth(HEALTH_EMPTY, 0, 0)
        return envelopes, health

    def health(self) -> LedgerHealth:
        _, health = self._read_envelopes()
        return health

    def replay(self, *, allow_truncated_tail: bool = False) -> ReplayResult:
        """Validate and fold the ledger; fail closed on any corruption."""
        envelopes, health = self._read_envelopes()
        if health.status == HEALTH_TRUNCATED_TAIL and not allow_truncated_tail:
            raise TruncatedTailError(
                f"{self.events_path} has an incomplete final line "
                f"({health.tail_bytes} bytes); replay the valid prefix with "
                "allow_truncated_tail=True and archive the tail before "
                "appending"
            )
        try:
            state = campaign_policy.replay_events(envelopes)
        except CampaignPolicyError as exc:
            raise LedgerCorruptionError(f"Ledger replay failed: {exc}") from exc
        return ReplayResult(
            state=state,
            health=health,
            last_sequence=state.last_sequence,
            last_event_sha256=state.last_event_sha256,
        )

    # -- appending ---------------------------------------------------------

    def append_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        actor: Actor,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> EventEnvelope:
        """Append one validated event; idempotent for exact re-delivery."""
        self._acquire_writer()
        envelopes, health = self._read_envelopes()
        if health.status == HEALTH_TRUNCATED_TAIL:
            raise TruncatedTailError(
                f"{self.events_path} has an unrepaired truncated tail; "
                "archive it before appending"
            )

        if event_id is not None:
            validate_record_id(event_id, "event")
            existing = next(
                (item for item in envelopes if item.event_id == event_id), None
            )
            if existing is not None:
                same_content = (
                    existing.event_type == event_type
                    and existing.actor is actor
                    and canonical_json(existing.payload)
                    == canonical_json(dict(payload))
                    and (
                        occurred_at is None
                        or normalize_utc_timestamp(occurred_at)
                        == existing.occurred_at
                    )
                )
                if same_content:
                    return existing
                raise CampaignStoreError(
                    f"Duplicate event id {event_id} with different content "
                    "fails closed"
                )

        try:
            state = campaign_policy.replay_events(envelopes)
        except CampaignPolicyError as exc:
            raise LedgerCorruptionError(f"Ledger replay failed: {exc}") from exc

        try:
            envelope = EventEnvelope.create(
                event_id=event_id if event_id is not None else new_record_id("event"),
                campaign_id=self.campaign_id,
                sequence=state.last_sequence + 1,
                event_type=event_type,
                occurred_at=(
                    occurred_at if occurred_at is not None else utc_now_iso()
                ),
                source_commit=self.source_commit,
                actor=actor,
                payload=payload,
                previous_event_sha256=state.last_event_sha256,
            )
            campaign_policy.apply_event(state, envelope)
        except (CampaignModelError, CampaignPolicyError) as exc:
            raise CampaignStoreError(f"Event rejected: {exc}") from exc

        self.campaign_dir.mkdir(parents=True, exist_ok=True)
        line = canonical_json(envelope.to_dict()) + "\n"
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return envelope

    # -- truncated tail recovery -------------------------------------------

    def archive_truncated_tail(self) -> Path:
        """Move the incomplete final line aside so appends can resume."""
        self._acquire_writer()
        envelopes, health = self._read_envelopes()
        if health.status != HEALTH_TRUNCATED_TAIL:
            raise CampaignStoreError(
                f"No truncated tail to archive; ledger is {health.status}"
            )
        raw = self.events_path.read_bytes()
        valid_length = len(raw) - health.tail_bytes
        tail = raw[valid_length:]
        archive_path = self.campaign_dir / (
            f"events.tail.seq{health.valid_events + 1}.corrupt"
        )
        counter = 1
        while archive_path.exists():
            archive_path = self.campaign_dir / (
                f"events.tail.seq{health.valid_events + 1}.corrupt.{counter}"
            )
            counter += 1
        archive_path.write_bytes(tail)
        with open(self.events_path, "r+b") as fh:
            fh.truncate(valid_length)
            fh.flush()
            os.fsync(fh.fileno())
        return archive_path

    # -- checkpoints -------------------------------------------------------

    def write_checkpoint(self) -> Path:
        """Publish a checkpoint atomically: temp file, fsync, os.replace."""
        self._acquire_writer()
        result = self.replay()
        if result.health.status == HEALTH_EMPTY:
            raise CampaignStoreError("Cannot checkpoint an empty ledger")
        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "created_at": utc_now_iso(),
            "source_commit": self.source_commit,
            "last_sequence": result.last_sequence,
            "last_event_sha256": result.last_event_sha256,
            "state": result.state.to_dict(),
            "state_sha256": result.state.state_sha256(),
        }
        temp_path = self.campaign_dir / (
            f"{CHECKPOINT_FILENAME}.tmp-{os.getpid()}"
        )
        try:
            with open(temp_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(canonical_json(payload))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, self.checkpoint_path)
        except OSError:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_path)
            raise
        return self.checkpoint_path

    def load_checkpoint(self) -> dict[str, Any]:
        """Load a checkpoint and validate it against the authoritative ledger."""
        if not self.checkpoint_path.exists():
            raise CheckpointError(f"No checkpoint at {self.checkpoint_path}")
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckpointError(f"Checkpoint is not valid JSON: {exc}") from exc
        if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError(
                f"Unknown checkpoint schema version: "
                f"{payload.get('schema_version')!r}"
            )
        if payload.get("campaign_id") != self.campaign_id:
            raise CheckpointError(
                f"Checkpoint campaign {payload.get('campaign_id')!r} does not "
                f"match {self.campaign_id}"
            )
        try:
            state = CampaignState.from_dict(payload["state"])
        except (KeyError, CampaignModelError, ValueError) as exc:
            raise CheckpointError(f"Checkpoint state invalid: {exc}") from exc
        if state.state_sha256() != payload.get("state_sha256"):
            raise CheckpointError("Checkpoint state hash mismatch")

        # The ledger remains the authority: the checkpointed sequence must
        # exist with the same hash, and replaying that prefix must reproduce
        # the stored state exactly.
        envelopes, _health = self._read_envelopes()
        last_sequence = payload.get("last_sequence")
        if (
            not isinstance(last_sequence, int)
            or last_sequence < 1
            or last_sequence > len(envelopes)
        ):
            raise CheckpointError(
                f"Checkpoint sequence {last_sequence!r} is outside the ledger "
                f"({len(envelopes)} events)"
            )
        anchor = envelopes[last_sequence - 1]
        if anchor.event_sha256 != payload.get("last_event_sha256"):
            raise CheckpointError(
                "Checkpoint anchor hash does not match the ledger"
            )
        try:
            replayed = campaign_policy.replay_events(envelopes[:last_sequence])
        except CampaignPolicyError as exc:
            raise LedgerCorruptionError(f"Ledger replay failed: {exc}") from exc
        if replayed.to_dict() != state.to_dict():
            raise CheckpointError(
                "Checkpoint state does not match the replayed ledger prefix"
            )
        return payload
