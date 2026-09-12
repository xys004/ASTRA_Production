"""Stage 4: explicit campaign resume over the checkpoint and ledger."""
import tempfile
import unittest
from pathlib import Path

from core.campaign_decision import campaign_step, select_initial_branch
from core.campaign_models import Actor, Campaign, EvidenceKind
from core.campaign_resume import (
    CHECKPOINT_INVALID_REBUILT,
    CHECKPOINT_MISSING_REBUILT,
    CHECKPOINT_NONE,
    CHECKPOINT_NOT_REBUILT,
    CHECKPOINT_STALE_REBUILT,
    CHECKPOINT_VALID,
    resume_campaign,
)
from core.campaign_store import CampaignStore

from test_campaign_executor import (
    CAMPAIGN_ID,
    COMMIT,
    SEED_BRANCH_ID,
    SHA,
    TS,
    fixed_now,
    make_budget,
    make_cycle_result,
    make_id_factory,
    seed_store,
)


async def validated_runner(_request):
    return make_cycle_result()


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    def fresh_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    async def test_empty_ledger_resumes_to_empty(self):
        root = self.fresh_root()
        store = CampaignStore(root, CAMPAIGN_ID, source_commit=COMMIT)
        self.addCleanup(store.close)
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "empty")
        self.assertEqual(report.checkpoint_status, CHECKPOINT_NONE)
        self.assertEqual(report.last_sequence, 0)

    async def test_draft_campaign_asks_for_activation(self):
        root = self.fresh_root()
        store = CampaignStore(root, CAMPAIGN_ID, source_commit=COMMIT)
        self.addCleanup(store.close)
        campaign = Campaign(
            campaign_id=CAMPAIGN_ID,
            created_at=TS,
            source_commit=COMMIT,
            objective="Decide whether the bounded identity family holds.",
            success_definition="Every deliverable has credible evidence.",
            deliverables=("identity proof",),
            frozen_resources={"brief.md": SHA},
            allowed_evidence_classes=(EvidenceKind.SYMBOLIC,),
            budget=make_budget(),
        )
        store.append_event(
            event_type="CAMPAIGN_CREATED",
            payload={"campaign": campaign.to_dict()},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "activate_campaign")
        self.assertEqual(report.campaign_status, "DRAFT")

    async def test_resume_recommends_selection_then_step(self):
        store = seed_store(self.fresh_root(), self.addCleanup, activate=False)
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "select_initial_branch")
        self.assertEqual(report.admissible_branch_ids, (SEED_BRANCH_ID,))
        select_initial_branch(
            store, id_factory=make_id_factory(), now_iso=fixed_now
        )
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "campaign_step")
        self.assertEqual(report.active_branch_id, SEED_BRANCH_ID)
        self.assertEqual(report.checkpoint_status, CHECKPOINT_VALID)

    async def test_resume_continues_without_repeating_episodes(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        ids = make_id_factory()
        await campaign_step(
            store, cycle_runner=validated_runner, id_factory=ids,
            now_iso=fixed_now,
        )
        first = resume_campaign(store)
        self.assertEqual(first.episodes_recorded, 1)
        self.assertEqual(first.next_action, "campaign_step")
        self.assertEqual(first.checkpoint_status, CHECKPOINT_VALID)
        self.assertEqual(first.last_decision["action"], "CONTINUE")
        await campaign_step(
            store, cycle_runner=validated_runner, id_factory=ids,
            now_iso=fixed_now,
        )
        second = resume_campaign(store)
        self.assertEqual(second.episodes_recorded, 2)
        self.assertGreater(second.last_sequence, first.last_sequence)
        self.assertEqual(second.spent["cycles"], 2)

    async def test_stale_checkpoint_is_rebuilt_from_the_ledger(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        await campaign_step(
            store,
            cycle_runner=validated_runner,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        store.append_event(
            event_type="BUDGET_CHARGED",
            payload={"dimension": "remote_jobs", "amount": 1},
            actor=Actor.SYSTEM,
            occurred_at=TS,
        )
        report = resume_campaign(store)
        self.assertEqual(report.checkpoint_status, CHECKPOINT_STALE_REBUILT)
        self.assertEqual(
            store.load_checkpoint()["last_sequence"], report.last_sequence
        )

    async def test_missing_and_corrupt_checkpoints_are_rebuilt(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        await campaign_step(
            store,
            cycle_runner=validated_runner,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        store.checkpoint_path.unlink()
        report = resume_campaign(store)
        self.assertEqual(report.checkpoint_status, CHECKPOINT_MISSING_REBUILT)
        store.checkpoint_path.write_text("{not json", encoding="utf-8")
        report = resume_campaign(store)
        self.assertEqual(report.checkpoint_status, CHECKPOINT_INVALID_REBUILT)
        self.assertEqual(
            store.load_checkpoint()["last_sequence"], report.last_sequence
        )

    async def test_truncated_tail_blocks_resume_until_archived(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        with open(store.events_path, "ab") as fh:
            fh.write(b'{"schema_version": "astra-camp')
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "repair_truncated_tail")
        self.assertEqual(report.checkpoint_status, CHECKPOINT_NOT_REBUILT)
        self.assertTrue(any("archive" in note for note in report.notes))
        store.archive_truncated_tail()
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "campaign_step")

    async def test_paused_and_terminal_states_are_reported(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        store.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "PAUSED"},
            actor=Actor.HUMAN,
            occurred_at=TS,
        )
        self.assertEqual(
            resume_campaign(store).next_action, "await_human_review"
        )
        store.append_event(
            event_type="CAMPAIGN_STATUS_CHANGED",
            payload={"status": "CANCELLED"},
            actor=Actor.HUMAN,
            occurred_at=TS,
        )
        report = resume_campaign(store)
        self.assertEqual(report.next_action, "terminal")
        self.assertEqual(report.campaign_status, "CANCELLED")

    async def test_read_only_resume_takes_no_writer_lock(self):
        store = seed_store(self.fresh_root(), self.addCleanup)
        await campaign_step(
            store,
            cycle_runner=validated_runner,
            id_factory=make_id_factory(),
            now_iso=fixed_now,
        )
        # The seeding store still holds the writer lock; a second store can
        # inspect the campaign read-only without touching the checkpoint.
        reader = CampaignStore(store.root, CAMPAIGN_ID, source_commit=COMMIT)
        self.addCleanup(reader.close)
        report = resume_campaign(reader, rebuild_checkpoint=False)
        self.assertEqual(report.next_action, "campaign_step")
        self.assertEqual(report.checkpoint_status, CHECKPOINT_VALID)
        self.assertEqual(report.episodes_recorded, 1)
        report_dict = report.to_dict()
        self.assertEqual(report_dict["campaign_status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
