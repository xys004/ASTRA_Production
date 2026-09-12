"""Append-only ledger, truncated-tail recovery, checkpoints, single writer."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.campaign_models import (
    Actor,
    AssumptionDelta,
    Branch,
    BudgetVector,
    Campaign,
    Claim,
    ClaimType,
    EvidenceKind,
    EvidencePlan,
    PriorityVector,
)
from core.campaign_store import (
    CampaignStore,
    CampaignStoreError,
    CheckpointError,
    HEALTH_EMPTY,
    HEALTH_HEALTHY,
    HEALTH_TRUNCATED_TAIL,
    LedgerCorruptionError,
    SingleWriterError,
    TruncatedTailError,
)

COMMIT = "a" * 40
TS = "2026-08-12T00:00:00Z"
SHA = "b" * 64
CAMPAIGN_ID = "cmp_store-0001"


def make_budget(**overrides) -> BudgetVector:
    base = dict(
        cycles=10,
        model_calls=40,
        wall_seconds=3600,
        execution_seconds=1800,
        human_interventions=2,
        remote_jobs=4,
    )
    base.update(overrides)
    return BudgetVector(**base)


def make_campaign(campaign_id: str = CAMPAIGN_ID) -> Campaign:
    return Campaign(
        campaign_id=campaign_id,
        created_at=TS,
        source_commit=COMMIT,
        objective="Decide whether the bounded identity family holds.",
        success_definition="Every mandatory deliverable has credible evidence.",
        deliverables=("identity proof",),
        frozen_resources={"brief.md": SHA},
        allowed_evidence_classes=(EvidenceKind.SYMBOLIC,),
        budget=make_budget(),
    )


def make_claim(campaign_id: str = CAMPAIGN_ID) -> Claim:
    return Claim(
        claim_id="clm_store-0001",
        campaign_id=campaign_id,
        created_at=TS,
        source_commit=COMMIT,
        statement="For all real x, x**2 >= 0.",
        claim_type=ClaimType.UNIVERSAL,
        domain="real analysis",
        scope="all real x",
        quantifiers=("forall x in R",),
    )


def make_branch(campaign_id: str = CAMPAIGN_ID) -> Branch:
    return Branch(
        branch_id="brn_store-0001",
        campaign_id=campaign_id,
        created_at=TS,
        source_commit=COMMIT,
        direction="Exact residual simplification.",
        method_family="symbolic_residual",
        material_difference="Exact simplification instead of sampling.",
        assumption_delta=AssumptionDelta(),
        evidence_plan=EvidencePlan(
            description="Symbolic residual check.",
            kind=EvidenceKind.SYMBOLIC,
            estimated_cost=make_budget(
                cycles=1,
                model_calls=4,
                wall_seconds=600,
                execution_seconds=120,
                human_interventions=0,
                remote_jobs=0,
            ),
        ),
        priority_vector=PriorityVector(
            information_gain=0.8,
            evidence_strength=0.2,
            methodological_independence=0.9,
            goal_advancement=0.7,
            estimated_cost=0.3,
            instability_risk=0.1,
        ),
        budget=make_budget(cycles=4),
        deliverable_refs=("identity proof",),
        claim_refs=("clm_store-0001",),
    )


class CampaignStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = CampaignStore(
            self.root, CAMPAIGN_ID, source_commit=COMMIT
        )
        self.addCleanup(self.store.close)

    def seed(self, store: CampaignStore | None = None, *, count: int = 4):
        """Append a deterministic prefix: create, activate, claim, branch."""
        target = store if store is not None else self.store
        campaign_id = target.campaign_id
        steps = [
            (
                "evt_seed-0001",
                "CAMPAIGN_CREATED",
                {"campaign": make_campaign(campaign_id).to_dict()},
            ),
            ("evt_seed-0002", "CAMPAIGN_STATUS_CHANGED", {"status": "ACTIVE"}),
            (
                "evt_seed-0003",
                "CLAIM_RECORDED",
                {"claim": make_claim(campaign_id).to_dict()},
            ),
            (
                "evt_seed-0004",
                "BRANCH_CREATED",
                {"branch": make_branch(campaign_id).to_dict()},
            ),
        ]
        appended = []
        for event_id, event_type, payload in steps[:count]:
            appended.append(
                target.append_event(
                    event_type=event_type,
                    payload=payload,
                    actor=Actor.SYSTEM,
                    occurred_at=TS,
                    event_id=event_id,
                )
            )
        return appended

    def ledger_lines(self, store: CampaignStore | None = None) -> list[str]:
        target = store if store is not None else self.store
        return [
            line
            for line in target.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class AppendReplayTests(CampaignStoreTestCase):
    def test_empty_ledger_replays_to_empty_state(self):
        result = self.store.replay()
        self.assertEqual(result.health.status, HEALTH_EMPTY)
        self.assertEqual(result.last_sequence, 0)
        self.assertIsNone(result.state.campaign)

    def test_append_and_replay_are_deterministic(self):
        self.seed()
        first = self.store.replay()
        second = self.store.replay()
        self.assertEqual(first.state.to_dict(), second.state.to_dict())
        self.assertEqual(first.last_event_sha256, second.last_event_sha256)
        self.assertEqual(first.health.status, HEALTH_HEALTHY)
        self.assertEqual(first.last_sequence, 4)
        self.assertEqual(
            first.state.campaign.campaign_id, CAMPAIGN_ID
        )
        self.assertIn("brn_store-0001", first.state.branches)

    def test_sequences_are_contiguous_and_hash_chained(self):
        self.seed()
        envelopes = [json.loads(line) for line in self.ledger_lines()]
        self.assertEqual([e["sequence"] for e in envelopes], [1, 2, 3, 4])
        self.assertIsNone(envelopes[0]["previous_event_sha256"])
        for previous, current in zip(envelopes, envelopes[1:]):
            self.assertEqual(
                current["previous_event_sha256"], previous["event_sha256"]
            )

    def test_idempotent_duplicate_append_is_a_noop(self):
        appended = self.seed()
        before = self.ledger_lines()
        again = self.store.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "ACTIVE"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
            event_id="evt_seed-0002",
        )
        self.assertEqual(again.event_sha256, appended[1].event_sha256)
        self.assertEqual(self.ledger_lines(), before)

    def test_duplicate_event_id_with_different_content_fails_closed(self):
        self.seed()
        with self.assertRaises(CampaignStoreError):
            self.store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": "PAUSED"},
                actor=Actor.SYSTEM,
                occurred_at=TS,
                event_id="evt_seed-0002",
            )

    def test_semantically_invalid_event_is_rejected_before_writing(self):
        self.seed()
        before = self.ledger_lines()
        with self.assertRaises(CampaignStoreError):
            self.store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": "COMPLETED"},  # deliverable unresolved
                actor=Actor.SYSTEM,
                occurred_at=TS,
            )
        self.assertEqual(self.ledger_lines(), before)


class ImmutabilityTests(CampaignStoreTestCase):
    def test_mutating_a_prior_event_is_detected(self):
        self.seed()
        lines = self.ledger_lines()
        tampered = lines[1].replace('"ACTIVE"', '"PAUSED"')
        self.assertNotEqual(tampered, lines[1])
        content = "\n".join([lines[0], tampered, *lines[2:]]) + "\n"
        self.store.events_path.write_text(content, encoding="utf-8")
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay()

    def test_reordering_events_breaks_the_chain(self):
        self.seed()
        lines = self.ledger_lines()
        content = "\n".join([lines[0], lines[2], lines[1], lines[3]]) + "\n"
        self.store.events_path.write_text(content, encoding="utf-8")
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay()

    def test_sequence_gap_fails_closed(self):
        self.seed()
        lines = self.ledger_lines()
        content = "\n".join([lines[0], *lines[2:]]) + "\n"
        self.store.events_path.write_text(content, encoding="utf-8")
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay()

    def test_corruption_before_the_final_line_always_fails(self):
        self.seed()
        lines = self.ledger_lines()
        content = "\n".join([lines[0], "{not json", *lines[2:]]) + "\n"
        self.store.events_path.write_text(content, encoding="utf-8")
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay()
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay(allow_truncated_tail=True)


class TruncatedTailTests(CampaignStoreTestCase):
    def truncate_tail(self) -> bytes:
        tail = b'{"schema_version": "astra-campaign-event/0.1", "event_id"'
        with open(self.store.events_path, "ab") as fh:
            fh.write(tail)
        return tail

    def test_truncated_tail_is_reported_and_blocks_appends(self):
        self.seed()
        self.truncate_tail()
        with self.assertRaises(TruncatedTailError):
            self.store.replay()
        result = self.store.replay(allow_truncated_tail=True)
        self.assertEqual(result.health.status, HEALTH_TRUNCATED_TAIL)
        self.assertEqual(result.last_sequence, 4)
        with self.assertRaises(TruncatedTailError):
            self.store.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": "PAUSED"},
                actor=Actor.SYSTEM,
                occurred_at=TS,
            )

    def test_unterminated_final_line_counts_as_truncated_tail(self):
        self.seed()
        raw = self.store.events_path.read_bytes()
        self.store.events_path.write_bytes(raw.rstrip(b"\n"))
        result = self.store.replay(allow_truncated_tail=True)
        self.assertEqual(result.health.status, HEALTH_TRUNCATED_TAIL)
        self.assertEqual(result.last_sequence, 3)

    def test_archiving_the_tail_restores_a_healthy_ledger(self):
        self.seed()
        tail = self.truncate_tail()
        archive = self.store.archive_truncated_tail()
        self.assertEqual(archive.read_bytes(), tail)
        self.assertEqual(self.store.health().status, HEALTH_HEALTHY)
        appended = self.store.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "PAUSED"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        self.assertEqual(appended.sequence, 5)

    def test_archive_refuses_when_there_is_no_tail(self):
        self.seed()
        with self.assertRaises(CampaignStoreError):
            self.store.archive_truncated_tail()


class CheckpointTests(CampaignStoreTestCase):
    def test_checkpoint_round_trip_matches_replay(self):
        self.seed()
        self.store.write_checkpoint()
        payload = self.store.load_checkpoint()
        replayed = self.store.replay()
        self.assertEqual(payload["last_sequence"], replayed.last_sequence)
        self.assertEqual(
            payload["state"], replayed.state.to_dict()
        )

    def test_checkpoint_remains_valid_after_more_events(self):
        self.seed()
        self.store.write_checkpoint()
        self.store.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "PAUSED"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        payload = self.store.load_checkpoint()
        self.assertEqual(payload["last_sequence"], 4)

    def test_tampered_checkpoint_fails_against_the_ledger(self):
        self.seed()
        self.store.write_checkpoint()
        payload = json.loads(
            self.store.checkpoint_path.read_text(encoding="utf-8")
        )
        payload["state"]["spent"]["cycles"] = 9
        self.store.checkpoint_path.write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with self.assertRaises(CheckpointError):
            self.store.load_checkpoint()

    def test_checkpoint_anchor_hash_must_match_the_ledger(self):
        self.seed()
        self.store.write_checkpoint()
        payload = json.loads(
            self.store.checkpoint_path.read_text(encoding="utf-8")
        )
        payload["last_event_sha256"] = "0" * 64
        self.store.checkpoint_path.write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with self.assertRaises(CheckpointError):
            self.store.load_checkpoint()

    def test_interrupted_publication_preserves_the_previous_checkpoint(self):
        self.seed(count=2)
        self.store.write_checkpoint()
        before = self.store.checkpoint_path.read_text(encoding="utf-8")
        self.seed(count=4)  # idempotent for the first two, appends the rest
        with patch(
            "core.campaign_store.os.replace",
            side_effect=OSError("simulated crash"),
        ):
            with self.assertRaises(OSError):
                self.store.write_checkpoint()
        self.assertEqual(
            self.store.checkpoint_path.read_text(encoding="utf-8"), before
        )
        leftovers = list(self.store.campaign_dir.glob("checkpoint.json.tmp-*"))
        self.assertEqual(leftovers, [])
        payload = self.store.load_checkpoint()
        self.assertEqual(payload["last_sequence"], 2)
        self.store.write_checkpoint()
        self.assertEqual(self.store.load_checkpoint()["last_sequence"], 4)

    def test_checkpointing_an_empty_ledger_fails(self):
        with self.assertRaises(CampaignStoreError):
            self.store.write_checkpoint()


class SingleWriterTests(CampaignStoreTestCase):
    def test_second_simultaneous_writer_is_rejected(self):
        self.seed()  # the seeding store now holds the writer lock
        rival = CampaignStore(self.root, CAMPAIGN_ID, source_commit=COMMIT)
        self.addCleanup(rival.close)
        with self.assertRaises(SingleWriterError):
            rival.append_event(
                event_type="CAMPAIGN_STATUS_CHANGED",
                payload={"status": "PAUSED"},
                actor=Actor.SYSTEM,
                occurred_at=TS,
            )
        self.store.close()
        appended = rival.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "PAUSED"},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        self.assertEqual(appended.sequence, 5)

    def test_reads_do_not_require_the_writer_lock(self):
        self.seed()
        reader = CampaignStore(self.root, CAMPAIGN_ID, source_commit=COMMIT)
        self.addCleanup(reader.close)
        result = reader.replay()
        self.assertEqual(result.last_sequence, 4)


class CampaignIsolationTests(CampaignStoreTestCase):
    def test_campaigns_under_one_root_stay_isolated(self):
        other_id = "cmp_store-0002"
        other = CampaignStore(self.root, other_id, source_commit=COMMIT)
        self.addCleanup(other.close)
        self.seed()
        self.seed(other, count=2)
        mine = self.store.replay()
        theirs = other.replay()
        self.assertEqual(mine.last_sequence, 4)
        self.assertEqual(theirs.last_sequence, 2)
        self.assertEqual(theirs.state.campaign.campaign_id, other_id)
        self.assertNotEqual(
            self.store.events_path, other.events_path
        )

    def test_a_foreign_ledger_is_rejected_not_absorbed(self):
        other = CampaignStore(self.root, "cmp_store-0002", source_commit=COMMIT)
        self.addCleanup(other.close)
        self.seed(other, count=2)
        self.store.campaign_dir.mkdir(parents=True, exist_ok=True)
        self.store.events_path.write_bytes(other.events_path.read_bytes())
        with self.assertRaises(LedgerCorruptionError):
            self.store.replay()


if __name__ == "__main__":
    unittest.main()
