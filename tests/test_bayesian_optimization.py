import math
import unittest

import numpy as np

from core.bayesian_optimization import (
    BayesianExperimentPlanner,
    ContinuousParameter,
    GaussianProcessSurrogate,
    expected_improvement,
    run_budgeted_search,
)
from scripts.run_bayesian_optimization_pilot import (
    evaluate_point,
    grid_points,
    symbolic_problem_definition,
    verify_method_result,
)


class BayesianOptimizationTests(unittest.TestCase):
    def test_expected_improvement_is_nonnegative_and_rewards_uncertainty(self):
        mean = np.asarray([0.2, 0.2])
        standard_deviation = np.asarray([0.01, 0.5])
        acquisition = expected_improvement(
            mean,
            standard_deviation,
            best=0.15,
            xi=0.0,
        )
        self.assertTrue(np.all(acquisition >= 0.0))
        self.assertGreater(acquisition[1], acquisition[0])

    def test_gp_predicts_finite_mean_and_uncertainty(self):
        x = np.asarray([[0.0], [0.25], [0.5], [0.75], [1.0]])
        y = (x[:, 0] - 0.37) ** 2
        surrogate = GaussianProcessSurrogate().fit(x, y)
        mean, standard_deviation = surrogate.predict(
            np.asarray([[0.37], [0.9]])
        )
        self.assertTrue(np.all(np.isfinite(mean)))
        self.assertTrue(np.all(standard_deviation > 0.0))
        self.assertLess(mean[0], mean[1])

    def test_initial_design_is_deterministic_and_within_bounds(self):
        parameters = [
            ContinuousParameter("x", -2.0, 3.0),
            ContinuousParameter("y", 10.0, 20.0),
        ]
        first = BayesianExperimentPlanner(
            parameters,
            seed=17,
            initial_points=4,
            candidate_pool_size=256,
        )
        second = BayesianExperimentPlanner(
            parameters,
            seed=17,
            initial_points=4,
            candidate_pool_size=256,
        )
        suggestions = first.suggest(batch_size=4)
        self.assertEqual(suggestions, second.suggest(batch_size=4))
        self.assertEqual(len(suggestions), 4)
        for point in suggestions:
            self.assertGreaterEqual(point["x"], -2.0)
            self.assertLessEqual(point["x"], 3.0)
            self.assertGreaterEqual(point["y"], 10.0)
            self.assertLessEqual(point["y"], 20.0)

    def test_operational_failure_is_not_folded_into_gp_values(self):
        planner = BayesianExperimentPlanner(
            [ContinuousParameter("x", 0.0, 1.0)],
            seed=2,
            initial_points=2,
            candidate_pool_size=256,
        )
        failed, successful = planner.suggest(batch_size=2)
        planner.observe(
            failed,
            None,
            status="ERROR",
            metadata={"error": "solver unavailable"},
        )
        planner.observe(successful, 0.5)
        state = planner.state()
        self.assertEqual(state["attempts"], 2)
        self.assertEqual(state["valid_observations"], 1)
        self.assertEqual(state["operational_failures"], 1)
        self.assertEqual(state["best"]["value"], 0.5)

    def test_budgeted_search_respects_attempt_budget(self):
        planner = BayesianExperimentPlanner(
            [ContinuousParameter("x", -1.0, 1.0)],
            seed=9,
            initial_points=3,
            candidate_pool_size=256,
        )

        def evaluator(point):
            x = point["x"]
            return (x - 0.2) ** 2, {"replayed": True}

        state = run_budgeted_search(
            planner,
            evaluator,
            budget=7,
            batch_size=1,
        )
        self.assertEqual(state["attempts"], 7)
        self.assertEqual(state["valid_observations"], 7)
        self.assertLess(state["best"]["value"], 0.05)

    def test_hybrid_pilot_has_exact_symbolic_gate_and_replay(self):
        symbolic = symbolic_problem_definition()
        self.assertTrue(symbolic["exact_reduction_verified"])
        self.assertEqual(symbolic["reduced_residual"], "0")
        points = grid_points(9)
        best_point = min(points, key=lambda point: evaluate_point(point)[0])
        best_value = evaluate_point(best_point)[0]
        verification = verify_method_result({
            "best_point": best_point,
            "best_value": best_value,
        })
        self.assertTrue(verification["passed"])
        self.assertLessEqual(
            abs(verification["symbolic_constraint_residual"]),
            1e-14,
        )
        self.assertTrue(math.isfinite(best_value))


if __name__ == "__main__":
    unittest.main()
