import unittest
from collections import Counter
from pathlib import Path

from core.research_programs import (
    load_research_suite,
    suite_fingerprint,
)
from core.research_trajectory_metrics import (
    blank_expert_scorecard,
    build_research_graph,
    compute_trajectory_metrics,
    score_expert_scorecards,
)
from scripts.run_research_trajectory_benchmarks import (
    CONFIGURATIONS,
    _last_json,
    _new_record,
    _next_direction,
    schedule_cells,
)


def evidence_result(status, conjecture, next_direction, branches=None):
    return {
        "status": status,
        "conjecture": conjecture,
        "code": (
            "assert 1 == 1\n"
            "print('CHECK symbolic: OK')\n"
            "print('CHECK numeric: OK')\n"
            "print('VERDICT: PASS')\n"
        ),
        "deliberation": {
            "proposals": [
                {"provider": "codex_cli", "text": "Use a symbolic invariant."},
                {"provider": "agy_cli", "text": "Search for a numerical counterexample."},
            ],
            "critiques": [{"provider": "codex_cli", "text": "Test the boundary."}],
        },
        "code_review_history": [{"status": "APPROVED"}],
        "execution": {
            "exit_code": 0,
            "verdict": "FAIL" if status == "REFUTED" else "PASS",
            "stdout": "CHECK symbolic: OK\nCHECK numeric: OK\nVERDICT: PASS",
            "stderr": "",
            "engine": "python",
            "guard": {
                "verdict_suspect": False,
                "checks_total": 2,
                "checks_ok": 2,
                "checks_fail": 0,
            },
        },
        "analysis": {"status": status, "reasoning": "Evidence changed the boundary."},
        "navigation": {
            "next_direction": next_direction,
            "parallel_branches": branches or [],
            "macro_resolved": False,
        },
        "retries": 0,
    }


class ResearchTrajectoryBenchmarkTests(unittest.TestCase):
    def test_vnext1_configuration_is_versioned_and_bounded(self):
        current = CONFIGURATIONS["full-vnext1"]["environment"]
        legacy = CONFIGURATIONS["full-vnext0"]["environment"]
        self.assertEqual(
            current["ASTRA_VALIDATOR_REPAIR_STRATEGY"],
            "local-patch",
        )
        self.assertEqual(
            current["ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS"],
            "1",
        )
        self.assertEqual(
            legacy["ASTRA_VALIDATOR_REPAIR_STRATEGY"],
            "legacy",
        )

    def test_public_pilot_loads_and_has_one_human_intervention(self):
        suite, programs = load_research_suite()
        self.assertEqual(len(programs), 6)
        self.assertEqual(set(suite["cases"]), {program.id for program in programs})
        self.assertTrue(all(program.budget.human_interventions == 1 for program in programs))
        self.assertTrue(
            all(
                len(program.linear_control_directions) >= program.budget.max_cycles
                for program in programs
            )
        )
        serialized = str([program.to_dict() for program in programs])
        self.assertNotIn("C:/Users/", serialized)

    def test_suite_fingerprint_is_deterministic(self):
        suite, programs = load_research_suite()
        fingerprint = suite_fingerprint(suite, programs)
        self.assertEqual(fingerprint, suite_fingerprint(suite, programs))
        frozen = (
            Path(__file__).resolve().parents[1]
            / "benchmarks"
            / "research_trajectory"
            / "PROTOCOL_FINGERPRINT_V1.txt"
        ).read_text(encoding="utf-8").strip()
        self.assertEqual(fingerprint, frozen)
        self.assertEqual(len(fingerprint), 64)

    def test_schedule_covers_each_case_configuration_seed_once(self):
        _suite, programs = load_research_suite()
        configs = ["full", "codex-only", "full-linear"]
        seeds = [11, 29]
        schedule = schedule_cells(programs[:2], configs, seeds)
        self.assertEqual(len(schedule), 12)
        keys = {(program.id, configuration, seed) for program, configuration, seed in schedule}
        self.assertEqual(len(keys), 12)
        first_positions = Counter(
            schedule[index][1] for index in range(0, len(schedule), len(configs))
        )
        self.assertLessEqual(
            max(first_positions.values()) - min(first_positions.values()),
            1,
        )

    def test_reflective_and_linear_direction_policies_differ(self):
        _suite, programs = load_research_suite()
        program = programs[0]
        reflective = _new_record(
            run_id="run",
            program=program,
            configuration="full",
            seed=11,
        )
        reflective["cycles"].append(
            {
                "cycle": 1,
                "direction": "initial",
                "result": evidence_result(
                    "VALIDATED",
                    "h1",
                    "Follow evidence-selected direction.",
                ),
            }
        )
        self.assertEqual(
            _next_direction(program, reflective, 2),
            "Follow evidence-selected direction.",
        )
        linear = _new_record(
            run_id="run",
            program=program,
            configuration="full-linear",
            seed=11,
        )
        self.assertEqual(
            _next_direction(program, linear, 2),
            program.linear_control_directions[0],
        )

    def test_graph_and_metrics_capture_recovery_without_claiming_novelty(self):
        record = {
            "objective": "Investigate a scientific mechanism deeply.",
            "human_interventions": 1,
            "cycles": [
                {
                    "cycle": 1,
                    "direction": "Test an overgeneralized hypothesis.",
                    "duration_s": 10,
                    "result": evidence_result(
                        "REFUTED",
                        "All local constraints imply the global claim.",
                        "Repair the missing assumption.",
                        branches=[
                            {
                                "direction": "Explore the four-variable boundary.",
                                "motivation": "Dimension may matter.",
                            }
                        ],
                    ),
                },
                {
                    "cycle": 2,
                    "direction": "Repair the missing assumption.",
                    "duration_s": 12,
                    "result": evidence_result(
                        "VALIDATED",
                        "The corrected assumptions imply the bounded claim.",
                        "Generalize the corrected theorem.",
                    ),
                },
            ],
        }
        graph = build_research_graph(record)
        metrics = compute_trajectory_metrics(record)
        self.assertEqual(metrics["human_prompt_efficiency"], 2.0)
        self.assertEqual(metrics["autonomous_loop_yield"], 1.0)
        self.assertEqual(metrics["independent_evidence_rate"], 1.0)
        self.assertEqual(metrics["recovery_rate_after_negative_evidence"], 1.0)
        self.assertEqual(metrics["preserved_independent_branches"], 1)
        self.assertTrue(any(node["type"] == "branch" for node in graph["nodes"]))
        self.assertNotIn("novelty_score", metrics)
        self.assertNotIn("research_depth_score", metrics)

    def test_blinded_expert_scores_are_separate_and_weighted(self):
        _suite, programs = load_research_suite()
        program = programs[0]
        record = _new_record(
            run_id="run",
            program=program,
            configuration="full",
            seed=11,
        )
        weights = {name: 1 / 8 for name in program.expert_anchors}
        card = blank_expert_scorecard(
            record=record,
            expert_anchors=program.expert_anchors,
            weights=weights,
        )
        card["rater_id"] = "rater-a"
        for item in card["dimensions"].values():
            item["score_0_to_4"] = 3
        scored = score_expert_scorecards([card])
        self.assertEqual(scored["blind_research_quality_0_to_100"], 75.0)
        self.assertFalse(scored["score_vetoed"])

    def test_last_json_prefers_complete_outer_line(self):
        payload = '{"status":"VALIDATED","analysis":{"status":"VALIDATED"}}'
        self.assertEqual(_last_json("log line\n" + payload)["status"], "VALIDATED")

    def test_statusless_pipeline_error_counts_as_operational_failure(self):
        record = {
            "objective": "Investigate a scientific mechanism deeply.",
            "human_interventions": 1,
            "cycles": [
                {
                    "cycle": 1,
                    "direction": "Test one hypothesis.",
                    "duration_s": 10,
                    "result": {
                        "error": "Independent reviewer did not approve.",
                        "phase": "reviewer",
                    },
                }
            ],
        }
        metrics = compute_trajectory_metrics(record)
        self.assertEqual(metrics["operational_failure_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
