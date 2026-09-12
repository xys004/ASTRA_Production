"""Run ASTRA's hybrid symbolic-numerical Bayesian-planning pilot.

The pilot is intentionally synthetic.  An exact symbolic relation eliminates a
dependent variable, then three equal-budget numerical strategies explore the
remaining space:

* Gaussian-process Bayesian optimization;
* seeded random search; and
* a uniform grid.

The script demonstrates evidence plumbing and budget accounting.  It is not a
physics result and does not claim that Bayesian optimization is superior on all
ASTRA workloads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import mpmath as mp
import numpy as np
import sympy as sp
from scipy.optimize import differential_evolution


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.bayesian_optimization import (
    BayesianExperimentPlanner,
    ContinuousParameter,
    run_budgeted_search,
)


BOUNDS = {
    "x": (-0.9, 0.9),
    "y": (-0.9, 0.9),
}


def symbolic_problem_definition() -> Dict[str, Any]:
    """Derive and verify the exact reduction used by the numerical planner."""

    x, y, z = sp.symbols("x y z", real=True)
    constraint = x**2 + y**2 + z - 1
    derived_z = sp.solve(sp.Eq(constraint, 0), z)[0]
    reduced_residual = sp.simplify(constraint.subs(z, derived_z))
    return {
        "variables": ["x", "y", "z"],
        "independent_variables": ["x", "y"],
        "constraint": str(constraint),
        "derived_relation": f"z = {sp.sstr(derived_z)}",
        "exact_reduction_verified": bool(reduced_residual == 0),
        "reduced_residual": str(reduced_residual),
    }


def dependent_z(x: float, y: float) -> float:
    return 1.0 - x * x - y * y


def hybrid_proxy_loss(x: float, y: float) -> float:
    """A deterministic, multimodal proxy evaluated after symbolic reduction."""

    z = dependent_z(x, y)
    smooth = (
        (x - 0.314159) ** 2
        + 1.35 * (y + 0.271828) ** 2
        + 0.04 * (z - 0.82) ** 2
    )
    ripples = (
        0.006 * (1.0 - math.cos(19.0 * x + 5.0 * y))
        + 0.004 * (1.0 - math.cos(11.0 * y - 3.0 * x))
    )
    return smooth + ripples


def independent_high_precision_loss(x: float, y: float) -> float:
    """Independent high-precision replay of the proxy objective."""

    with mp.workdps(60):
        x_mp = mp.mpf(str(x))
        y_mp = mp.mpf(str(y))
        z_mp = 1 - x_mp * x_mp - y_mp * y_mp
        smooth = (
            (x_mp - mp.mpf("0.314159")) ** 2
            + mp.mpf("1.35") * (y_mp + mp.mpf("0.271828")) ** 2
            + mp.mpf("0.04") * (z_mp - mp.mpf("0.82")) ** 2
        )
        ripples = (
            mp.mpf("0.006") * (1 - mp.cos(19 * x_mp + 5 * y_mp))
            + mp.mpf("0.004") * (1 - mp.cos(11 * y_mp - 3 * x_mp))
        )
        return float(smooth + ripples)


def evaluate_point(point: Mapping[str, float]) -> Tuple[float, Dict[str, Any]]:
    x = float(point["x"])
    y = float(point["y"])
    z = dependent_z(x, y)
    value = hybrid_proxy_loss(x, y)
    return value, {
        "dependent_z": z,
        "constraint_residual": x * x + y * y + z - 1.0,
        "symbolic_relation": "z = 1 - x**2 - y**2",
    }


def _record_sequence(
    method: str,
    points: Iterable[Mapping[str, float]],
) -> Dict[str, Any]:
    observations: List[Dict[str, Any]] = []
    best_value = math.inf
    best_point: Dict[str, float] = {}
    for index, point in enumerate(points, 1):
        value, metadata = evaluate_point(point)
        if value < best_value:
            best_value = value
            best_point = {name: float(number) for name, number in point.items()}
        observations.append({
            "evaluation": index,
            "point": {name: float(number) for name, number in point.items()},
            "value": value,
            "best_so_far": best_value,
            "metadata": metadata,
        })
    return {
        "method": method,
        "evaluations": len(observations),
        "best_value": best_value,
        "best_point": best_point,
        "observations": observations,
    }


def run_bayesian(
    budget: int,
    seed: int,
    initial_points: int,
    batch_size: int,
) -> Dict[str, Any]:
    planner = BayesianExperimentPlanner(
        parameters=[
            ContinuousParameter("x", *BOUNDS["x"]),
            ContinuousParameter("y", *BOUNDS["y"]),
        ],
        direction="minimize",
        seed=seed,
        initial_points=initial_points,
        candidate_pool_size=4096,
        xi=0.005,
    )
    state = run_budgeted_search(
        planner,
        evaluate_point,
        budget=budget,
        batch_size=batch_size,
    )
    best = state["best"]
    observations = []
    best_so_far = math.inf
    for index, observation in enumerate(state["observations"], 1):
        value = observation["value"]
        if observation["status"] == "OK" and value is not None:
            best_so_far = min(best_so_far, float(value))
        observations.append({
            "evaluation": index,
            **observation,
            "best_so_far": best_so_far,
        })
    return {
        "method": "bayesian_gp_ei",
        "evaluations": state["attempts"],
        "valid_observations": state["valid_observations"],
        "operational_failures": state["operational_failures"],
        "best_value": best["value"] if best else None,
        "best_point": best["point"] if best else {},
        "last_gp_hyperparameters": state["last_gp_hyperparameters"],
        "observations": observations,
    }


def random_points(budget: int, seed: int) -> List[Dict[str, float]]:
    rng = np.random.default_rng(seed)
    return [
        {
            "x": float(rng.uniform(*BOUNDS["x"])),
            "y": float(rng.uniform(*BOUNDS["y"])),
        }
        for _ in range(budget)
    ]


def grid_points(budget: int) -> List[Dict[str, float]]:
    axis_size = int(math.ceil(math.sqrt(budget)))
    axes = {
        name: np.linspace(lower, upper, axis_size)
        for name, (lower, upper) in BOUNDS.items()
    }
    full_grid = [
        {"x": float(x), "y": float(y)}
        for x, y in itertools.product(axes["x"], axes["y"])
    ]
    if len(full_grid) == budget:
        return full_grid
    indices = np.linspace(0, len(full_grid) - 1, budget)
    selected = sorted({int(round(index)) for index in indices})
    cursor = 0
    while len(selected) < budget:
        if cursor not in selected:
            selected.append(cursor)
        cursor += 1
    return [full_grid[index] for index in sorted(selected[:budget])]


def reference_solution(seed: int) -> Dict[str, Any]:
    result = differential_evolution(
        lambda row: hybrid_proxy_loss(float(row[0]), float(row[1])),
        bounds=[BOUNDS["x"], BOUNDS["y"]],
        seed=seed,
        polish=True,
        tol=1e-11,
        atol=1e-13,
        updating="immediate",
        workers=1,
    )
    point = {"x": float(result.x[0]), "y": float(result.x[1])}
    return {
        "method": "independent_differential_evolution_reference",
        "budget_matched": False,
        "point": point,
        "value": float(result.fun),
        "success": bool(result.success),
        "evaluations": int(result.nfev),
    }


def verify_method_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    point = result["best_point"]
    x = float(point["x"])
    y = float(point["y"])
    recorded = float(result["best_value"])
    direct_replay = hybrid_proxy_loss(x, y)
    independent_replay = independent_high_precision_loss(x, y)
    z = dependent_z(x, y)
    return {
        "symbolic_constraint_residual": x * x + y * y + z - 1.0,
        "direct_replay_delta": abs(recorded - direct_replay),
        "independent_replay_delta": abs(recorded - independent_replay),
        "passed": (
            abs(x * x + y * y + z - 1.0) <= 1e-14
            and abs(recorded - direct_replay) <= 1e-14
            and abs(recorded - independent_replay) <= 1e-12
        ),
    }


def build_report(
    budget: int,
    seed: int,
    initial_points: int,
    batch_size: int,
) -> Dict[str, Any]:
    symbolic = symbolic_problem_definition()
    if not symbolic["exact_reduction_verified"]:
        raise RuntimeError("The symbolic reduction failed its exact gate.")
    methods = [
        run_bayesian(budget, seed, initial_points, batch_size),
        _record_sequence(
            "seeded_random",
            random_points(budget, seed + 1),
        ),
        _record_sequence("uniform_grid", grid_points(budget)),
    ]
    reference = reference_solution(seed + 2)
    for result in methods:
        result["regret_to_reference"] = max(
            0.0,
            float(result["best_value"]) - float(reference["value"]),
        )
        result["verification"] = verify_method_result(result)
    ranked = sorted(methods, key=lambda result: float(result["best_value"]))
    return {
        "schema_version": "1.0",
        "run_id": dt.datetime.now().strftime("bayesian_pilot_%Y%m%d_%H%M%S"),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "claim_boundary": (
            "Synthetic hybrid-planning pilot. It tests budgeted numerical search "
            "after exact symbolic reduction; it is not a scientific result, a "
            "formal proof, or a general superiority claim."
        ),
        "problem": {
            "name": "exact-constraint multimodal proxy",
            "bounds": {
                name: list(bounds) for name, bounds in BOUNDS.items()
            },
            "symbolic": symbolic,
            "numerical_objective": (
                "deterministic smooth-plus-ripple proxy after eliminating z"
            ),
        },
        "settings": {
            "equal_evaluation_budget_per_method": budget,
            "seed": seed,
            "initial_points": initial_points,
            "batch_size": batch_size,
        },
        "reference": reference,
        "ranking": [
            {
                "rank": index,
                "method": result["method"],
                "best_value": result["best_value"],
                "regret_to_reference": result["regret_to_reference"],
            }
            for index, result in enumerate(ranked, 1)
        ],
        "all_final_verifications_passed": all(
            result["verification"]["passed"] for result in methods
        ),
        "methods": methods,
    }


def markdown_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# ASTRA Hybrid Bayesian-Optimization Pilot",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Created: {report['created_at']}",
        f"- Boundary: {report['claim_boundary']}",
        f"- Equal budget: {report['settings']['equal_evaluation_budget_per_method']} "
        "evaluations per method",
        f"- Exact symbolic reduction: "
        f"{report['problem']['symbolic']['exact_reduction_verified']}",
        f"- Independent final replays passed: "
        f"{report['all_final_verifications_passed']}",
        "",
        "## Symbolic gate",
        "",
        f"- Constraint: `{report['problem']['symbolic']['constraint']}`",
        f"- Derived relation: `{report['problem']['symbolic']['derived_relation']}`",
        f"- Reduced residual: `{report['problem']['symbolic']['reduced_residual']}`",
        "",
        "## Equal-budget comparison",
        "",
        "| Rank | Method | Best value | Regret to independent reference | Verified |",
        "|---:|---|---:|---:|---:|",
    ]
    methods = {
        result["method"]: result for result in report["methods"]
    }
    for row in report["ranking"]:
        result = methods[row["method"]]
        lines.append(
            f"| {row['rank']} | `{row['method']}` | "
            f"{float(row['best_value']):.10g} | "
            f"{float(row['regret_to_reference']):.10g} | "
            f"{result['verification']['passed']} |"
        )
    lines.extend([
        "",
        "The differential-evolution reference is not budget matched; it estimates",
        "regret and is not included in the ranking budget.",
        "",
        "## Interpretation",
        "",
        "The GP selects numerical evaluations only after the symbolic relation has",
        "been derived and checked exactly. Operational failures would be recorded",
        "separately rather than converted into unfavorable objective values. The",
        "best numerical candidate is replayed independently, but scientific",
        "acceptance would still require ASTRA's domain validators and human gate.",
        "",
    ])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run ASTRA's hybrid symbolic-numerical Bayesian pilot."
    )
    result.add_argument("--budget", type=int, default=25)
    result.add_argument("--seed", type=int, default=20260729)
    result.add_argument("--initial-points", type=int, default=6)
    result.add_argument("--batch-size", type=int, default=1)
    result.add_argument("--output-dir", default="")
    return result


def main(args: argparse.Namespace) -> int:
    if args.budget < max(args.initial_points, 2):
        raise ValueError("Budget must cover at least the initial design.")
    report = build_report(
        budget=args.budget,
        seed=args.seed,
        initial_points=args.initial_points,
        batch_size=args.batch_size,
    )
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "workspace" / "bayesian_optimization_runs"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"{report['run_id']}.json"
    markdown_path = output_root / f"{report['run_id']}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "run_id": report["run_id"],
        "ranking": report["ranking"],
        "all_final_verifications_passed": report[
            "all_final_verifications_passed"
        ],
        "json_report": str(json_path),
        "markdown_report": str(markdown_path),
    }, indent=2))
    return 0 if report["all_final_verifications_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(parser().parse_args()))
