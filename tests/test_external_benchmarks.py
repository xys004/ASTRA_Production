import json
import tempfile
import unittest
from pathlib import Path

from core.external_benchmarks import (
    _lean_theorems,
    audit_external_sources,
    cache_root,
    load_ainsteinbench,
    load_frontierscience,
    load_minif2f,
    load_scicode,
)
from core.external_evaluators import (
    ainstein_patch_paths,
    clean_lean_proof,
    evaluate_frontier_answer,
    minif2f_source,
    normalize_final_answer,
    parse_ainstein_msb_log,
    resolve_ainstein_image,
    unsafe_ainstein_patch_paths,
)
from core.external_evaluators import evaluate_scicode_code
from core.architecture_configs import architecture_environment, architecture_roles
from scripts.run_external_benchmarks import (
    _frontier_evaluation,
    _patch_from_response,
)
from scripts.run_external_comparison import (
    _markdown_cell,
    _summarize,
    parser as comparison_parser,
)


class ExternalBenchmarkTests(unittest.TestCase):
    def test_comparison_markdown_escapes_diagnostic_pipes(self):
        self.assertEqual(
            _markdown_cell("provider A | provider B\nquota"),
            r"provider A \| provider B quota",
        )

    def test_comparison_summary_excludes_operational_errors_from_pass_rate(self):
        records = [
            {
                "configuration": "agy-only",
                "state": "complete",
                "status": "PASS",
                "duration_s": 100,
                "effective_models": ["gemini-primary"],
            },
            {
                "configuration": "agy-only",
                "state": "complete",
                "status": "TOOL_ERROR",
                "duration_s": 20,
                "effective_models": [],
            },
        ]
        summary = _summarize(
            records,
            ["agy-only"],
            {"agy_cli": "gemini-primary"},
        )
        agy = summary["by_configuration"]["agy-only"]
        self.assertEqual(agy["completed"], 2)
        self.assertEqual(agy["scored"], 1)
        self.assertEqual(agy["operational_errors"], 1)
        self.assertEqual(agy["pass_rate"], 1.0)
        self.assertEqual(agy["latency_s"]["total"], 100.0)

    def test_comparison_parser_accepts_selective_resume_configurations(self):
        args = comparison_parser().parse_args(
            [
                "--resume",
                "checkpoint.json",
                "--config",
                "codex-only,claude-only",
            ]
        )
        self.assertEqual(args.config, "codex-only,claude-only")

    def test_public_comparison_preserves_equal_proposal_topology(self):
        for name in (
            "codex-only",
            "claude-only",
            "agy-only",
            "homogeneous-proposers",
        ):
            roles = architecture_roles(name)
            self.assertEqual(len(roles["proposers"]), 2)
            self.assertEqual(len(set(roles["proposers"])), 1)
        full = architecture_roles("full")
        control = architecture_roles("homogeneous-proposers")
        self.assertEqual(full["proposers"], ["codex_cli", "agy_cli"])
        self.assertEqual(control["proposers"], ["codex_cli", "codex_cli"])
        for role in ("synthesizer", "author", "reviewer", "repairer"):
            self.assertEqual(full[role], control[role])
        env = architecture_environment(
            "agy-only",
            base={"ASTRA_TRANSLATOR_MODELS": "claude-opus-4-8,sonnet"},
        )
        self.assertEqual(env["ASTRA_CONJECTURE_PROVIDER"], "agy_cli,agy_cli")
        self.assertEqual(env["ASTRA_TRANSLATOR_PROVIDER"], "agy_cli")
        self.assertEqual(env["ASTRA_REVIEWER_PROVIDER"], "agy_cli")
        self.assertEqual(env["ASTRA_TRANSLATOR_MODELS"], "")

    def test_ainstein_patch_extraction_preserves_terminal_newline(self):
        response = (
            "```diff\n"
            "diff --git a/pkg/core.py b/pkg/core.py\n"
            "--- a/pkg/core.py\n"
            "+++ b/pkg/core.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "```"
        )
        patch = _patch_from_response(response)
        self.assertTrue(patch.endswith("\n"))
        self.assertFalse(patch.endswith("\n\n"))

    def test_ainstein_patch_extraction_rejects_narrative_and_fragments(self):
        self.assertEqual(
            _patch_from_response("I would first inspect the repository."),
            "",
        )
        self.assertEqual(
            _patch_from_response('or gate_class_name == "MCMTGate"'),
            "",
        )

    def test_ainstein_patch_extraction_rejects_malformed_hunk_with_valid_tail(self):
        response = (
            "```diff\n"
            "diff --git a/pkg/core.py b/pkg/core.py\n"
            "--- a/pkg/core.py\n"
            "+++ b/pkg/core.py\n"
            "@@ def broken(\n"
            "-old\n"
            "+new\n"
            "diff --git a/note.txt b/note.txt\n"
            "--- a/note.txt\n"
            "+++ b/note.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "```"
        )
        self.assertEqual(_patch_from_response(response), "")

    def test_final_answer_normalization(self):
        self.assertEqual(
            normalize_final_answer("work\nFINAL ANSWER: `\\(2.31 \\times 10^{6}\\)`"),
            "2.31\\times10^{6}",
        )

    def test_frontier_numeric_equivalence(self):
        result = evaluate_frontier_answer(
            "FINAL ANSWER: 2.31 \\times 10^{6}",
            "`\\( 2.31 \\times 10^6 \\)`",
        )
        self.assertEqual(result["status"], "PASS")

    def test_frontier_numeric_equivalence_accepts_latex_units(self):
        result = evaluate_frontier_answer(
            "derivation\nFINAL ANSWER: \\(2.31\\times10^6\\ \\mathrm{K}\\)",
            "`\\( 2.31 \\times 10^6 K\\)`",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["candidate_unit"], "k")
        self.assertEqual(result["reference_unit"], "k")

    def test_frontier_reviewer_rejection_is_scientific_abstention(self):
        result = _frontier_evaluation(
            "Reasoning\nFINAL ANSWER: candidate",
            "reference",
            {"error": "Independent reviewer did not approve the validation strategy"},
        )
        self.assertEqual(result["status"], "ABSTAIN")
        self.assertEqual(result["method"], "independent_review_rejected")
        self.assertIn("candidate_answer_evaluation", result)

    def test_frontier_timeout_remains_operational_error(self):
        result = _frontier_evaluation(
            "Partial candidate",
            "reference",
            {"error": "TIMEOUT after 10s"},
        )
        self.assertEqual(result["status"], "TOOL_ERROR")

    def test_lean_statement_parser_hides_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.lean"
            path.write_text(
                "theorem one (x : ℕ) : x = x :=\nbegin\n  refl,\nend\n\n"
                "theorem two : 1 = 1 := by norm_num\n",
                encoding="utf-8",
            )
            parsed = list(_lean_theorems(path))
        self.assertEqual([name for name, _ in parsed], ["one", "two"])
        self.assertNotIn("refl", parsed[0][1])

    def test_lean_proof_extraction_and_source(self):
        if not (cache_root() / "miniF2F").exists():
            self.skipTest("miniF2F cache not prepared")
        case = next(
            item
            for item in load_minif2f()
            if item.id == "minif2f_validation_mathd_algebra_182"
        )
        proof = clean_lean_proof("```lean\nbegin\n  ring_nf\nend\n```")
        source = minif2f_source(case, proof)
        self.assertIn("theorem mathd_algebra_182", source)
        self.assertIn("begin\n  ring_nf\nend", source)
        self.assertNotIn("sorry", source)

    def test_ainstein_image_mapping_and_official_log_protocol(self):
        self.assertEqual(
            resolve_ainstein_image("mswebench/pyscf_m_pyscf:pr-2373"),
            "shuoxin/pyscf_m_pyscf:pr-2373",
        )
        parsed = parse_ainstein_msb_log(
            "PASSED test_a\nPASSED test_b\nFAILED test_c - assertion\n"
        )
        self.assertEqual(parsed["passed_count"], 2)
        self.assertEqual(parsed["failed_count"], 1)

    def test_ainstein_prompt_includes_public_issue_but_hides_reference_patch(self):
        if not (cache_root() / "AInsteinBench").exists():
            self.skipTest("AInsteinBench cache not prepared")
        case = next(
            item
            for item in load_ainsteinbench()
            if item.id == "ainsteinbench_MSB_pyscf_pyscf_pr2373"
        )
        self.assertIn("spin-forbidden transitions", case.prompt)
        self.assertNotIn("diff --git", case.prompt)
        self.assertNotIn("_contract_multipole", case.prompt)

    def test_ainstein_candidate_cannot_modify_tests(self):
        patch = (
            "diff --git a/pkg/core.py b/pkg/core.py\n"
            "--- a/pkg/core.py\n+++ b/pkg/core.py\n"
            "diff --git a/pkg/tests/test_core.py b/pkg/tests/test_core.py\n"
            "--- a/pkg/tests/test_core.py\n+++ b/pkg/tests/test_core.py\n"
        )
        self.assertEqual(
            ainstein_patch_paths(patch),
            ["pkg/core.py", "pkg/tests/test_core.py"],
        )
        self.assertEqual(
            unsafe_ainstein_patch_paths(patch),
            ["pkg/tests/test_core.py"],
        )
        deleted_test = (
            "diff --git a/pkg/testing/reference.py b/dev/null\n"
            "--- a/pkg/testing/reference.py\n"
            "+++ /dev/null\n"
        )
        self.assertEqual(
            unsafe_ainstein_patch_paths(deleted_test),
            ["pkg/testing/reference.py"],
        )

    @unittest.skipUnless(
        (cache_root() / "SciCode_dataset").exists(),
        "external benchmark cache not prepared",
    )
    def test_pinned_cache_counts(self):
        self.assertEqual(len(load_scicode()), 338)
        self.assertEqual(len(load_minif2f()), 488)
        self.assertEqual(len(load_frontierscience()), 160)
        self.assertEqual(len(load_ainsteinbench()), 244)
        self.assertTrue(audit_external_sources()["ok"])

    @unittest.skipUnless(
        (cache_root() / "SciCode" / "eval" / "data" / "test_data.h5").exists(),
        "SciCode numerical evaluator not downloaded",
    )
    def test_scicode_official_targets_accept_development_gold_code(self):
        case = next(item for item in load_scicode() if item.id == "scicode_29_1")
        result = evaluate_scicode_code(case, case.reference, timeout=60)
        self.assertEqual(result["status"], "PASS", result.get("stderr"))


if __name__ == "__main__":
    unittest.main()
