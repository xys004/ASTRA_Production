import unittest

import numpy as np

from scripts.run_hollow_core_bayesian_benchmark import (
    RADII,
    build_report,
    default_source_path,
    independent_configuration,
    load_hollow_core_source,
    symbolic_elimination_gate,
)


SOURCE = default_source_path()


class HollowCoreBayesianBenchmarkTests(unittest.TestCase):
    def test_first_mass_elimination_is_symbolically_exact(self):
        gate = symbolic_elimination_gate()
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["exact_residual"], "0")

    @unittest.skipUnless(
        SOURCE.is_file(),
        "optional hollow_core_energy_conditions project is unavailable",
    )
    def test_analytic_incumbent_matches_independent_high_precision_replay(self):
        source, _digest = load_hollow_core_source(SOURCE)
        variables = np.asarray(source.baseline_variables(RADII), dtype=float)
        source_result = source.evaluate_variables(RADII, variables)
        independent = independent_configuration(
            RADII,
            variables,
            float(source.AC),
        )
        self.assertTrue(source_result["valid"])
        self.assertAlmostEqual(
            source_result["absolute_energy"],
            independent["absolute_energy"],
            places=12,
        )
        self.assertLess(abs(independent["lapse_residual"]), 1e-12)
        self.assertGreaterEqual(
            independent["strict_negative_sigma_shells"],
            1,
        )
        self.assertLess(independent["minimum_sigma"], 0.0)

    @unittest.skipUnless(
        SOURCE.is_file(),
        "optional hollow_core_energy_conditions project is unavailable",
    )
    def test_small_equal_budget_report_is_fail_closed(self):
        report = build_report(
            SOURCE,
            budget=9,
            seed=20260729,
            initial_points=4,
            batch_size=1,
        )
        self.assertTrue(report["all_replays_passed"])
        self.assertGreaterEqual(
            report["problem"]["analytic_incumbent"]["metadata"][
                "strict_negative_sigma_shells"
            ],
            1,
        )
        self.assertEqual(len(report["methods"]), 3)
        self.assertTrue(
            all(method["attempts"] == 9 for method in report["methods"])
        )
        self.assertTrue(
            all(
                method["counterexamples_below_incumbent"] >= 0
                for method in report["methods"]
            )
        )


if __name__ == "__main__":
    unittest.main()
