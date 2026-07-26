import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.client_validation import (
    load_client_validation_cases,
    route_validator,
    run_client_validation_case,
    select_oracles,
)
from core.benchmarks import load_benchmarks
from core.engine_router import detect_engine
from core.formal_validators import (
    LEAN4_VERSION,
    MATHLIB4_COMMIT,
    evaluate_lean4_source,
)


class ClientValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_client_validation_cases()

    def test_minimum_suite_has_six_unique_application_cases(self):
        self.assertEqual(len(self.cases), 6)
        self.assertEqual(len({case.id for case in self.cases}), 6)
        verdicts = {case.expected_claim_verdict for case in self.cases}
        self.assertIn("VALIDATED", verdicts)
        self.assertIn("REFUTED", verdicts)

    def test_client_schema_is_separate_from_legacy_benchmarks(self):
        legacy_ids = {case.id for case in load_benchmarks()}
        self.assertFalse(
            legacy_ids & {case.id for case in self.cases},
            "Client evidence cases must not be parsed as legacy benchmarks.",
        )

    def test_router_selects_formal_and_project_backends(self):
        by_id = {case.id: case for case in self.cases}
        self.assertEqual(
            route_validator(by_id["client_grpython_zero_trace_formal"]).primary,
            "lean4",
        )
        self.assertEqual(
            route_validator(by_id["client_grpython_flat_spacetime"]).primary,
            "project_python",
        )
        self.assertIn(
            "wolfram_bridge",
            route_validator(by_id["client_formula_regression"]).alternatives,
        )

    def test_oracle_matrix_respects_case_capabilities(self):
        by_id = {case.id: case for case in self.cases}
        self.assertEqual(
            select_oracles(by_id["client_formula_regression"], "both"),
            ["local", "astrum"],
        )
        self.assertEqual(
            select_oracles(by_id["client_grpython_flat_spacetime"], "both"),
            ["local"],
        )
        self.assertEqual(
            select_oracles(by_id["client_grpython_zero_trace_formal"], "both"),
            ["astrum"],
        )

    def test_engine_router_recognizes_explicit_lean4(self):
        self.assertEqual(
            detect_engine("# ASTRA_ENGINE: lean4\nimport Mathlib\nexample : True := by trivial"),
            "lean4",
        )
        self.assertEqual(
            detect_engine("# ASTRA_ENGINE: lean\nimport Mathlib\nexample : True := by trivial"),
            "lean4",
        )

    def test_lean4_rejects_placeholders_before_execution(self):
        result = asyncio.run(
            evaluate_lean4_source(
                "import Mathlib\naxiom unproved : False",
                oracle="astrum",
            )
        )
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["forbidden"], ["axiom"])

    def test_formal_bundle_records_pinned_kernel_evidence(self):
        case = next(
            item
            for item in self.cases
            if item.id == "client_grpython_zero_trace_formal"
        )
        raw = {
            "status": "PASS",
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "engine": "lean4",
            "oracle": "astrum",
            "lean_version": LEAN4_VERSION,
            "mathlib_commit": MATHLIB4_COMMIT,
        }
        with patch(
            "core.formal_validators.evaluate_lean4_source",
            new=AsyncMock(return_value=raw),
        ):
            bundle = asyncio.run(
                run_client_validation_case(case, oracle="astrum", timeout=30)
            )
        self.assertEqual(bundle["validation"]["status"], "PASS")
        self.assertTrue(bundle["evidence"]["kernel_checked"])
        self.assertEqual(bundle["evidence"]["mathlib_commit"], MATHLIB4_COMMIT)
        self.assertEqual(len(bundle["artifact"]["sha256"]), 64)

    def test_symbolic_case_produces_complete_local_evidence(self):
        case = next(
            item for item in self.cases if item.id == "client_formula_regression"
        )
        bundle = asyncio.run(
            run_client_validation_case(case, oracle="local", timeout=30)
        )
        self.assertEqual(bundle["validation"]["status"], "PASS")
        self.assertEqual(bundle["validation"]["claim_verdict"], "VALIDATED")
        self.assertEqual(bundle["evidence"]["residual"], "0")


if __name__ == "__main__":
    unittest.main()
