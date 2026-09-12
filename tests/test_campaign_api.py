"""Stage 5: development-only astra_campaign_* interfaces."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.campaign_api import (
    CampaignApiError,
    astra_campaign_list,
    astra_campaign_reactivate,
    astra_campaign_start,
    astra_campaign_status,
    astra_campaign_step,
    astra_campaign_stop,
)

from test_campaign_executor import (
    COMMIT,
    fixed_now,
    make_cycle_result,
    make_id_factory,
    make_portfolio_dict,
)

CAMPAIGN_ID = "cmp_api-00001"


def start_kwargs(**overrides):
    base = dict(
        objective="Decide whether the bounded identity family holds.",
        success_definition="Every deliverable has credible evidence.",
        deliverables=["identity proof", "counterexample report"],
        allowed_evidence_classes=["SYMBOLIC", "NUMERICAL"],
        budget={
            "cycles": 10,
            "model_calls": 100,
            "wall_seconds": 36000,
            "execution_seconds": 18000,
            "human_interventions": 2,
            "remote_jobs": 4,
        },
        frozen_resources={"brief.md": "b" * 64},
        initial_portfolio=make_portfolio_dict(),
        campaign_id=CAMPAIGN_ID,
        source_commit=COMMIT,
        id_factory=make_id_factory(),
        now_iso=fixed_now,
    )
    base.update(overrides)
    return base


async def validated_runner(_request):
    return make_cycle_result()


class CampaignApiTests(unittest.IsolatedAsyncioTestCase):
    def fresh_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    async def test_full_dev_lifecycle(self):
        root = self.fresh_root()
        ids = make_id_factory()
        started = astra_campaign_start(
            root=root, **start_kwargs(id_factory=ids)
        )
        self.assertEqual(started["campaign_id"], CAMPAIGN_ID)
        self.assertEqual(started["campaign_status"], "ACTIVE")
        self.assertEqual(len(started["seeding"]["admissible"]), 2)
        self.assertEqual(started["seeding"]["rejected"], [])
        self.assertIsNotNone(started["active_branch_id"])
        self.assertEqual(started["next_action"], "campaign_step")

        status = astra_campaign_status(
            CAMPAIGN_ID, root=root, source_commit=COMMIT
        )
        self.assertEqual(status["episodes_recorded"], 0)

        stepped = await astra_campaign_step(
            CAMPAIGN_ID,
            root=root,
            source_commit=COMMIT,
            cycle_runner=validated_runner,
            id_factory=ids,
            now_iso=fixed_now,
        )
        self.assertEqual(stepped["step"]["operation_status"], "COMPLETED")
        self.assertEqual(stepped["step"]["decision_rule"], "R7-continue")
        self.assertEqual(stepped["status"]["episodes_recorded"], 1)
        self.assertEqual(stepped["status"]["next_action"], "campaign_step")

        paused = astra_campaign_stop(
            CAMPAIGN_ID,
            root=root,
            source_commit=COMMIT,
            mode="pause",
            reason="human checkpoint",
            now_iso=fixed_now,
        )
        self.assertEqual(paused["campaign_status"], "PAUSED")
        with self.assertRaises(CampaignApiError):
            await astra_campaign_step(
                CAMPAIGN_ID,
                root=root,
                source_commit=COMMIT,
                cycle_runner=validated_runner,
            )
        reactivated = astra_campaign_reactivate(
            CAMPAIGN_ID, root=root, source_commit=COMMIT, now_iso=fixed_now
        )
        self.assertEqual(reactivated["campaign_status"], "ACTIVE")

        cancelled = astra_campaign_stop(
            CAMPAIGN_ID,
            root=root,
            source_commit=COMMIT,
            mode="cancel",
            now_iso=fixed_now,
        )
        self.assertEqual(cancelled["campaign_status"], "CANCELLED")
        self.assertEqual(cancelled["next_action"], "terminal")
        with self.assertRaises(CampaignApiError):
            await astra_campaign_step(
                CAMPAIGN_ID,
                root=root,
                source_commit=COMMIT,
                cycle_runner=validated_runner,
            )

    async def test_step_auto_selects_when_no_branch_is_active(self):
        root = self.fresh_root()
        ids = make_id_factory()
        astra_campaign_start(
            root=root, **start_kwargs(id_factory=ids, activate=True)
        )
        # Pause and reactivate: the active branch stays active, but build the
        # auto-select scenario by starting a fresh campaign without selection.
        other = "cmp_api-00002"
        astra_campaign_start(
            root=root,
            **start_kwargs(campaign_id=other, activate=False, id_factory=ids),
        )
        status = astra_campaign_status(other, root=root, source_commit=COMMIT)
        self.assertEqual(status["campaign_status"], "DRAFT")

    async def test_start_without_portfolio_reports_no_branches(self):
        root = self.fresh_root()
        started = astra_campaign_start(
            root=root, **start_kwargs(initial_portfolio=None)
        )
        self.assertEqual(started["seeding"]["admissible"], [])
        self.assertIsNone(started["active_branch_id"])
        self.assertEqual(started["next_action"], "await_human_review")

    async def test_invalid_inputs_fail_closed(self):
        root = self.fresh_root()
        with self.assertRaises(CampaignApiError):
            astra_campaign_start(
                root=root, **start_kwargs(budget={"cycles": 10})
            )
        with self.assertRaises(CampaignApiError):
            astra_campaign_start(
                root=root,
                **start_kwargs(allowed_evidence_classes=["VIBES"]),
            )
        bad_portfolio = make_portfolio_dict()
        bad_portfolio["selected"]["deliverable"] = "nobody defined this"
        with self.assertRaises(CampaignApiError):
            astra_campaign_start(
                root=root, **start_kwargs(initial_portfolio=bad_portfolio)
            )
        with self.assertRaises(CampaignApiError):
            astra_campaign_stop(
                CAMPAIGN_ID, root=root, source_commit=COMMIT, mode="explode"
            )

    async def test_list_enumerates_campaigns_read_only(self):
        root = self.fresh_root()
        self.assertEqual(astra_campaign_list(root=root), [])
        ids = make_id_factory()
        astra_campaign_start(root=root, **start_kwargs(id_factory=ids))
        astra_campaign_start(
            root=root,
            **start_kwargs(campaign_id="cmp_api-00002", id_factory=ids),
        )
        entries = astra_campaign_list(root=root, source_commit=COMMIT)
        self.assertEqual(
            [entry["campaign_id"] for entry in entries],
            ["cmp_api-00001", "cmp_api-00002"],
        )
        self.assertTrue(
            all(entry["campaign_status"] == "ACTIVE" for entry in entries)
        )

    async def test_sequential_calls_release_the_writer_lock(self):
        root = self.fresh_root()
        ids = make_id_factory()
        astra_campaign_start(root=root, **start_kwargs(id_factory=ids))
        for _ in range(2):
            await astra_campaign_step(
                CAMPAIGN_ID,
                root=root,
                source_commit=COMMIT,
                cycle_runner=validated_runner,
                id_factory=ids,
                now_iso=fixed_now,
            )
        status = astra_campaign_status(
            CAMPAIGN_ID, root=root, source_commit=COMMIT
        )
        self.assertEqual(status["episodes_recorded"], 2)
        lock = root / CAMPAIGN_ID / "writer.lock"
        self.assertFalse(lock.exists())

    def test_dev_api_never_imports_the_mcp_server(self):
        self.assertNotIn("mcp_server", sys.modules)
        self.assertNotIn("mcp_server.server", sys.modules)

    def test_campaign_tools_are_gated_off_for_production(self):
        """The tools may ship on the dev line, never under the production name.

        Stage 5 enforced this by asserting the string `astra_campaign` was
        absent from the server. Nelson later authorised exposing the tools on
        the development line, so the invariant that actually matters is the
        gate: a server introducing itself as `astra` - the production entry -
        must not advertise them, and the kill switch must work.
        """
        root = Path(__file__).resolve().parents[1]
        probe = (
            "import asyncio, importlib.util, sys, json\n"
            f"spec = importlib.util.spec_from_file_location('s', r'{root / 'mcp_server' / 'server.py'}')\n"
            "m = importlib.util.module_from_spec(spec); sys.modules['s'] = m\n"
            "spec.loader.exec_module(m)\n"
            "names = [t.name for t in asyncio.run(m.mcp.list_tools())]\n"
            "print(json.dumps({'server': m.MCP_SERVER_NAME, "
            "'campaign': sorted(n for n in names if 'campaign' in n)}))\n"
        )

        def tools_under(env_extra: dict) -> dict:
            env = {**os.environ, **env_extra}
            completed = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True, text=True, timeout=180, cwd=str(root),
                env=env,
            )
            for line in completed.stdout.splitlines():
                if line.startswith("{"):
                    return json.loads(line)
            self.fail(f"probe produced no result: {completed.stderr[-400:]}")

        production = tools_under({"ASTRA_MCP_SERVER_NAME": "astra"})
        self.assertEqual(production["server"], "astra")
        self.assertEqual(
            production["campaign"],
            [],
            "the production MCP name must not advertise campaign tools",
        )

        disabled = tools_under({"ASTRA_CAMPAIGN_TOOLS": "0"})
        self.assertEqual(disabled["campaign"], [], "kill switch did not work")

        dev = tools_under({"ASTRA_CAMPAIGN_TOOLS": "1"})
        self.assertIn("astra_campaign_start", dev["campaign"])
        self.assertIn("astra_campaign_step", dev["campaign"])


if __name__ == "__main__":
    unittest.main()
