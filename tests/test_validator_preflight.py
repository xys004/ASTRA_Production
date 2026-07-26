import unittest
import importlib.util

from core.code_patching import apply_exact_edit_patch
from core.validator_preflight import (
    audit_validation_code,
    preflight_as_review,
    repair_validation_code,
    smoke_validation_code,
)


class ValidatorPreflightTests(unittest.TestCase):
    def test_caught_operational_exception_cannot_become_refutation(self):
        code = """
ok = True
try:
    import unavailable_engine
except Exception:
    ok = False
print("VERDICT: PASS" if ok else "VERDICT: FAIL")
"""
        audit = audit_validation_code(code)
        labels = {item["label"] for item in audit["findings"]}
        self.assertEqual(audit["status"], "REVISE")
        self.assertIn("swallowed_exception", labels)

    def test_reraised_exception_is_operational_and_allowed(self):
        code = """
try:
    import unavailable_engine
except Exception:
    raise
print("VERDICT: PASS")
"""
        audit = audit_validation_code(code)
        self.assertEqual(audit["status"], "APPROVED")

    def test_indeterminate_is_zero_cannot_prove_nonzero(self):
        code = """
import sympy as sp
x = sp.symbols("x")
ok = x.is_zero is not True
print("VERDICT: PASS" if ok else "VERDICT: FAIL")
"""
        audit = audit_validation_code(code)
        labels = {item["label"] for item in audit["findings"]}
        self.assertIn("unknown_as_pass", labels)

    def test_indeterminate_is_zero_gets_safe_local_repair(self):
        code = """
import sympy as sp
x = sp.symbols("x")
ok = x.is_zero is not True
print("VERDICT: PASS" if ok else "VERDICT: FAIL")
"""
        result = repair_validation_code(code)
        self.assertTrue(result["changed"])
        self.assertIn("x.is_zero is False", result["code"])
        self.assertEqual(audit_validation_code(result["code"])["status"], "APPROVED")

    def test_module_level_swallowed_exception_is_reraised_locally(self):
        code = """
ok = True
try:
    import unavailable_engine
except Exception:
    ok = False
print("VERDICT: PASS" if ok else "VERDICT: FAIL")
"""
        result = repair_validation_code(code)
        self.assertTrue(result["changed"])
        self.assertIn("raise  # ASTRA vNext.1", result["code"])
        self.assertEqual(audit_validation_code(result["code"])["status"], "APPROVED")

    def test_expected_numeric_retry_inside_helper_is_not_overblocked(self):
        code = """
def bootstrap(samples):
    accepted = []
    for sample in samples:
        try:
            accepted.append(fit(sample))
        except Exception:
            continue
    if not accepted:
        raise RuntimeError("no converged bootstrap samples")
    return accepted
ok = len(bootstrap(data)) > 20
print("VERDICT: PASS" if ok else "VERDICT: FAIL")
"""
        self.assertEqual(audit_validation_code(code)["status"], "APPROVED")

    def test_non_python_formal_artifact_is_left_for_its_oracle(self):
        code = """# ASTRA_ENGINE: lean
import Mathlib
example : 1 + 1 = 2 := by norm_num
"""
        audit = audit_validation_code(code)
        smoke = smoke_validation_code(code)
        self.assertEqual(audit["status"], "APPROVED")
        self.assertEqual(audit["engine"], "lean4")
        self.assertIsNone(smoke["compiled"])

    def test_compile_import_smoke_is_nonblocking_for_remote_dependencies(self):
        code = """
import astra_dependency_that_does_not_exist
print("VERDICT: PASS")
"""
        smoke = smoke_validation_code(code)
        self.assertEqual(smoke["status"], "APPROVED")
        self.assertTrue(smoke["compiled"])
        self.assertIn(
            "astra_dependency_that_does_not_exist",
            smoke["missing_modules"],
        )
        self.assertTrue(smoke["runtime_checks"])

    def test_preflight_review_is_structured_and_patch_oriented(self):
        audit = audit_validation_code(
            'try:\n import missing\nexcept Exception:\n pass\nprint("VERDICT: FAIL")'
        )
        review = preflight_as_review(audit)
        self.assertEqual(review["status"], "REVISE")
        self.assertEqual(review["source"], "deterministic_preflight")
        self.assertIn("Operational failures", review["revision_instructions"])

    @unittest.skipUnless(
        importlib.util.find_spec("einsteinpy"),
        "EinsteinPy is not installed",
    )
    def test_installed_einsteinpy_accepts_list_and_tuple_symbols(self):
        import sympy as sp
        from einsteinpy.symbolic import MetricTensor, RiemannCurvatureTensor

        t, x = sp.symbols("t x")
        metric = sp.diag(-1, 1).tolist()
        for symbols in ([t, x], (t, x)):
            tensor = MetricTensor(metric, symbols)
            curvature = RiemannCurvatureTensor.from_metric(tensor).tensor()
            self.assertTrue(
                all(
                    sp.simplify(curvature[a, b, c, d]).is_zero is True
                    for a in range(2)
                    for b in range(2)
                    for c in range(2)
                    for d in range(2)
                )
            )

    def test_exact_patch_applies_only_unique_local_replacement(self):
        code = "x = 1\nok = x == 1\nprint(ok)\n"
        result = apply_exact_edit_patch(
            code,
            {
                "status": "PATCH",
                "reason": "Tighten the check.",
                "edits": [{"old": "ok = x == 1", "new": "ok = (x - 1) == 0"}],
            },
        )
        self.assertEqual(result["status"], "APPLIED")
        self.assertIn("ok = (x - 1) == 0", result["code"])
        self.assertEqual(result["edit_count"], 1)

    def test_exact_patch_rejects_ambiguous_or_whole_script_rewrite(self):
        ambiguous = apply_exact_edit_patch(
            "x = 1\nx = 1\n",
            {"edits": [{"old": "x = 1", "new": "x = 2"}]},
        )
        self.assertEqual(ambiguous["status"], "REJECTED")
        wholesale = apply_exact_edit_patch(
            "a" * 100,
            {"edits": [{"old": "a" * 70, "new": "b"}]},
        )
        self.assertEqual(wholesale["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
