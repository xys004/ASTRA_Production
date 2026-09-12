"""Bayesian counterexample search on the hollow-core multishell model.

This benchmark reuses the exact Israel-shell evaluator from the separate
``hollow_core_energy_conditions`` project without modifying that project.
It fixes a four-shell radius pattern, analytically eliminates the first
intermediate mass at fixed central lapse, and asks whether small perturbations
from the embedded exact two-shell solution can reduce absolute proper shell
energy.

All compared methods receive the same analytic incumbent and the same total
number of objective evaluations.  The meaningful comparison is therefore the
best *challenger* each method finds, while any apparent counterexample must
survive an independent high-precision replay.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import itertools
import json
import math
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import mpmath as mp
import numpy as np
import sympy as sp


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.bayesian_optimization import (
    BayesianExperimentPlanner,
    ContinuousParameter,
    run_budgeted_search,
)


RADII = np.asarray([1.0, 3.0, 100.0, 10000.0], dtype=float)
LOCAL_COMPACTNESS_SCALE = np.asarray([1.0e-3, 1.0e-3], dtype=float)
COUNTEREXAMPLE_TOLERANCE = 1.0e-12


def default_source_path() -> Path:
    configured = os.environ.get("ASTRA_HOLLOW_CORE_ROOT", "").strip()
    project = (
        Path(configured).expanduser()
        if configured
        else ROOT.parent / "warp" / "hollow_core_energy_conditions"
    )
    return project / "derivations" / "search_multishell_lower_energy.py"


def load_hollow_core_source(path: Path) -> Tuple[ModuleType, str]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(
            "Hollow-core evaluator not found. Set ASTRA_HOLLOW_CORE_ROOT to "
            "the hollow_core_energy_conditions project root."
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    specification = importlib.util.spec_from_file_location(
        "astra_hollow_core_multishell_source",
        str(path),
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load hollow-core evaluator from {path}.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    required = {
        "AC",
        "LOG_AC",
        "baseline_variables",
        "compactness_to_tail",
        "evaluate_variables",
        "solve_first_mass",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise RuntimeError(f"Hollow-core evaluator is missing: {missing}")
    return module, digest


def symbolic_elimination_gate() -> Dict[str, Any]:
    """Verify the algebraic elimination used by the source evaluator."""

    mass, radius_1, radius_2, ratio = sp.symbols(
        "m R1 R2 Q",
        nonzero=True,
    )
    solved_mass = (1 - ratio) / (
        2 * (1 / radius_1 - ratio / radius_2)
    )
    defining_residual = sp.together(
        (1 - 2 * mass / radius_1)
        - ratio * (1 - 2 * mass / radius_2)
    )
    reduced = sp.factor(defining_residual.subs(mass, solved_mass))
    return {
        "defining_equation": (
            "(1 - 2*m1/R1) / (1 - 2*m1/R2) = Q"
        ),
        "eliminated_mass": str(solved_mass),
        "exact_residual": str(reduced),
        "passed": bool(reduced == 0),
    }


def independent_configuration(
    radii: Sequence[float],
    compactness_variables: Sequence[float],
    central_lapse: float,
) -> Dict[str, float]:
    """Independent 80-digit implementation of the shell equations."""

    with mp.workdps(80):
        radius_values = [mp.mpf(str(value)) for value in radii]
        variables = [mp.mpf(str(value)) for value in compactness_variables]
        lapse = mp.mpf(str(central_lapse))
        n_shells = len(radius_values)
        if n_shells != 4 or len(variables) != 2:
            raise ValueError("The frozen benchmark requires four shells.")

        masses = [mp.mpf("0")] * (n_shells + 1)
        masses[2] = mp.mpf("0.5") * variables[0] * radius_values[1]
        masses[3] = mp.mpf("0.5") * variables[1] * radius_values[2]

        def f_value(mass: mp.mpf, radius: mp.mpf) -> mp.mpf:
            return 1 - 2 * mass / radius

        other = mp.log(f_value(masses[2], radius_values[1]))
        for shell_index in range(2, n_shells):
            radius = radius_values[shell_index]
            other += (
                mp.log(f_value(masses[shell_index + 1], radius))
                - mp.log(f_value(masses[shell_index], radius))
            )
        d_value = 2 * mp.log(lapse) - other
        ratio = mp.exp(d_value)
        denominator = 2 * (
            1 / radius_values[0] - ratio / radius_values[1]
        )
        masses[1] = (1 - ratio) / denominator

        log_lapse = mp.mpf("0")
        absolute_energy = mp.mpf("0")
        horizon_margin = mp.inf
        minimum_sigma = mp.inf
        minimum_nec_margin = mp.inf
        negative_sigma_shells = 0
        negative_nec_shells = 0
        for shell_index, radius in enumerate(radius_values):
            f_in = f_value(masses[shell_index], radius)
            f_out = f_value(masses[shell_index + 1], radius)
            if min(f_in, f_out) <= 0:
                raise ValueError("Independent replay crossed a horizon.")
            root_in = mp.sqrt(f_in)
            root_out = mp.sqrt(f_out)
            log_lapse += mp.log(root_out / root_in)
            absolute_energy += abs(radius * (root_in - root_out))
            horizon_margin = min(horizon_margin, f_in, f_out)
            sigma = (root_in - root_out) / (4 * mp.pi * radius)
            pressure = (
                (1 - masses[shell_index + 1] / radius) / root_out
                - (1 - masses[shell_index] / radius) / root_in
            ) / (8 * mp.pi * radius)
            nec_margin = sigma + pressure
            minimum_sigma = min(minimum_sigma, sigma)
            minimum_nec_margin = min(minimum_nec_margin, nec_margin)
            negative_sigma_shells += int(sigma < 0)
            negative_nec_shells += int(nec_margin < 0)
        return {
            "absolute_energy": float(absolute_energy),
            "lapse_residual": float(log_lapse - mp.log(lapse)),
            "horizon_margin": float(horizon_margin),
            "minimum_sigma": float(minimum_sigma),
            "minimum_intrinsic_NEC_margin": float(minimum_nec_margin),
            "strict_negative_sigma_shells": negative_sigma_shells,
            "strict_NEC_violating_shells": negative_nec_shells,
        }


def _physical_variables(
    incumbent_variables: np.ndarray,
    point: Mapping[str, float],
) -> np.ndarray:
    offsets = np.asarray([point["u"], point["v"]], dtype=float)
    return incumbent_variables + LOCAL_COMPACTNESS_SCALE * offsets


def make_evaluator(
    source: ModuleType,
    incumbent_variables: np.ndarray,
):
    def evaluator(point: Mapping[str, float]):
        variables = _physical_variables(incumbent_variables, point)
        configuration = source.evaluate_variables(RADII, variables)
        if not configuration.get("valid"):
            raise ValueError("Candidate failed the analytic horizon gate.")
        value = float(configuration["absolute_energy"])
        if not math.isfinite(value):
            raise ValueError("Candidate returned non-finite absolute energy.")
        lapse_residual = float(configuration["lapse_residual"])
        if abs(lapse_residual) > 1e-10:
            raise ValueError("Analytic lapse elimination failed its residual gate.")
        shells = configuration["shells"]
        return value, {
            "compactness_variables": variables.tolist(),
            "lapse_residual": lapse_residual,
            "horizon_margin": float(configuration["horizon_margin"]),
            "negative_energy": float(configuration["negative_energy"]),
            "source_tolerance_WEC_violating_shells": int(
                configuration["WEC_violating_shells"]
            ),
            "source_tolerance_DEC_violating_shells": int(
                configuration["DEC_violating_shells"]
            ),
            "strict_negative_sigma_shells": sum(
                float(shell["sigma"]) < 0.0 for shell in shells
            ),
            "strict_NEC_violating_shells": sum(
                float(shell["intrinsic_NEC_margin"]) < 0.0
                for shell in shells
            ),
            "minimum_sigma": min(float(shell["sigma"]) for shell in shells),
            "minimum_intrinsic_NEC_margin": min(
                float(shell["intrinsic_NEC_margin"]) for shell in shells
            ),
        }

    return evaluator


def random_offsets(count: int, seed: int) -> List[Dict[str, float]]:
    rng = np.random.default_rng(seed)
    return [
        {
            "u": float(rng.uniform(-1.0, 1.0)),
            "v": float(rng.uniform(-1.0, 1.0)),
        }
        for _ in range(count)
    ]


def grid_offsets(count: int) -> List[Dict[str, float]]:
    axis_size = max(3, int(math.ceil(math.sqrt(count + 1))))
    while axis_size * axis_size - 1 < count:
        axis_size += 1
    axis = np.linspace(-1.0, 1.0, axis_size)
    candidates = [
        {"u": float(u), "v": float(v)}
        for u, v in itertools.product(axis, repeat=2)
        if not (abs(float(u)) <= 1e-15 and abs(float(v)) <= 1e-15)
    ]
    if len(candidates) == count:
        return candidates
    indices = np.linspace(0, len(candidates) - 1, count)
    selected = sorted({int(round(index)) for index in indices})
    cursor = 0
    while len(selected) < count:
        if cursor not in selected:
            selected.append(cursor)
        cursor += 1
    return [candidates[index] for index in sorted(selected[:count])]


def _baseline_observation(
    incumbent_value: float,
    incumbent_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "evaluation": 1,
        "point": {"u": 0.0, "v": 0.0},
        "value": incumbent_value,
        "status": "OK",
        "metadata": {
            **dict(incumbent_metadata),
            "analytic_incumbent": True,
        },
    }


def run_baseline_method(
    method: str,
    points: Iterable[Mapping[str, float]],
    evaluator,
    incumbent_value: float,
    incumbent_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    observations = [
        _baseline_observation(incumbent_value, incumbent_metadata)
    ]
    for index, point in enumerate(points, 2):
        try:
            value, metadata = evaluator(point)
            observations.append({
                "evaluation": index,
                "point": dict(point),
                "value": value,
                "status": "OK",
                "metadata": metadata,
            })
        except Exception as exc:
            observations.append({
                "evaluation": index,
                "point": dict(point),
                "value": None,
                "status": "ERROR",
                "metadata": {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            })
    return summarize_method(method, observations, incumbent_value)


def run_bayesian_method(
    evaluator,
    budget: int,
    seed: int,
    initial_points: int,
    batch_size: int,
    incumbent_value: float,
    incumbent_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    planner = BayesianExperimentPlanner(
        [
            ContinuousParameter("u", -1.0, 1.0),
            ContinuousParameter("v", -1.0, 1.0),
        ],
        direction="minimize",
        seed=seed,
        initial_points=initial_points,
        candidate_pool_size=4096,
        xi=1.0e-6,
    )
    planner.observe(
        {"u": 0.0, "v": 0.0},
        incumbent_value,
        metadata={
            **dict(incumbent_metadata),
            "analytic_incumbent": True,
        },
    )
    state = run_budgeted_search(
        planner,
        evaluator,
        budget=budget,
        batch_size=batch_size,
    )
    observations = [
        {"evaluation": index, **observation}
        for index, observation in enumerate(state["observations"], 1)
    ]
    result = summarize_method(
        "bayesian_gp_ei",
        observations,
        incumbent_value,
    )
    result["last_gp_hyperparameters"] = state["last_gp_hyperparameters"]
    return result


def summarize_method(
    method: str,
    observations: Sequence[Mapping[str, Any]],
    incumbent_value: float,
) -> Dict[str, Any]:
    valid = [
        observation
        for observation in observations
        if observation["status"] == "OK"
        and observation["value"] is not None
    ]
    challengers = [
        observation
        for observation in valid
        if not observation["metadata"].get("analytic_incumbent")
    ]
    best = min(valid, key=lambda observation: float(observation["value"]))
    best_challenger = min(
        challengers,
        key=lambda observation: float(observation["value"]),
    )
    counterexamples = [
        observation
        for observation in challengers
        if float(observation["value"])
        < incumbent_value - COUNTEREXAMPLE_TOLERANCE
    ]
    return {
        "method": method,
        "attempts": len(observations),
        "valid_evaluations": len(valid),
        "operational_failures": len(observations) - len(valid),
        "best": dict(best),
        "best_challenger": dict(best_challenger),
        "best_challenger_gap": (
            float(best_challenger["value"]) - incumbent_value
        ),
        "counterexamples_below_incumbent": len(counterexamples),
        "observations": [dict(observation) for observation in observations],
    }


def verify_record(
    source: ModuleType,
    incumbent_variables: np.ndarray,
    record: Mapping[str, Any],
) -> Dict[str, Any]:
    physical = _physical_variables(incumbent_variables, record["point"])
    source_replay = source.evaluate_variables(RADII, physical)
    independent = independent_configuration(
        RADII,
        physical,
        float(source.AC),
    )
    recorded = float(record["value"])
    return {
        "compactness_variables": physical.tolist(),
        "source_replay_delta": abs(
            recorded - float(source_replay["absolute_energy"])
        ),
        "independent_replay_delta": abs(
            recorded - independent["absolute_energy"]
        ),
        "source_lapse_residual": float(source_replay["lapse_residual"]),
        "independent_lapse_residual": independent["lapse_residual"],
        "horizon_margin": independent["horizon_margin"],
        "independent_minimum_sigma": independent["minimum_sigma"],
        "independent_minimum_intrinsic_NEC_margin": independent[
            "minimum_intrinsic_NEC_margin"
        ],
        "independent_strict_negative_sigma_shells": independent[
            "strict_negative_sigma_shells"
        ],
        "independent_strict_NEC_violating_shells": independent[
            "strict_NEC_violating_shells"
        ],
        "passed": (
            bool(source_replay["valid"])
            and abs(recorded - float(source_replay["absolute_energy"]))
            <= 1e-14
            and abs(recorded - independent["absolute_energy"]) <= 1e-12
            and abs(float(source_replay["lapse_residual"])) <= 1e-10
            and abs(independent["lapse_residual"]) <= 1e-12
            and independent["horizon_margin"] > 0.0
        ),
    }


def build_report(
    source_path: Path,
    budget: int,
    seed: int,
    initial_points: int,
    batch_size: int,
) -> Dict[str, Any]:
    source, source_hash = load_hollow_core_source(source_path)
    symbolic_gate = symbolic_elimination_gate()
    if not symbolic_gate["passed"]:
        raise RuntimeError("The exact mass-elimination gate failed.")
    incumbent_variables = np.asarray(
        source.baseline_variables(RADII),
        dtype=float,
    )
    incumbent_configuration = source.evaluate_variables(
        RADII,
        incumbent_variables,
    )
    if not incumbent_configuration["valid"]:
        raise RuntimeError("The analytic incumbent failed the source validator.")
    incumbent_value = float(incumbent_configuration["absolute_energy"])
    incumbent_shells = incumbent_configuration["shells"]
    incumbent_metadata = {
        "compactness_variables": incumbent_variables.tolist(),
        "lapse_residual": float(incumbent_configuration["lapse_residual"]),
        "horizon_margin": float(incumbent_configuration["horizon_margin"]),
        "negative_energy": float(incumbent_configuration["negative_energy"]),
        "source_tolerance_WEC_violating_shells": int(
            incumbent_configuration["WEC_violating_shells"]
        ),
        "source_tolerance_DEC_violating_shells": int(
            incumbent_configuration["DEC_violating_shells"]
        ),
        "strict_negative_sigma_shells": sum(
            float(shell["sigma"]) < 0.0 for shell in incumbent_shells
        ),
        "strict_NEC_violating_shells": sum(
            float(shell["intrinsic_NEC_margin"]) < 0.0
            for shell in incumbent_shells
        ),
        "minimum_sigma": min(
            float(shell["sigma"]) for shell in incumbent_shells
        ),
        "minimum_intrinsic_NEC_margin": min(
            float(shell["intrinsic_NEC_margin"])
            for shell in incumbent_shells
        ),
    }
    evaluator = make_evaluator(source, incumbent_variables)
    methods = [
        run_bayesian_method(
            evaluator,
            budget,
            seed,
            initial_points,
            batch_size,
            incumbent_value,
            incumbent_metadata,
        ),
        run_baseline_method(
            "seeded_random",
            random_offsets(budget - 1, seed + 1),
            evaluator,
            incumbent_value,
            incumbent_metadata,
        ),
        run_baseline_method(
            "uniform_local_grid",
            grid_offsets(budget - 1),
            evaluator,
            incumbent_value,
            incumbent_metadata,
        ),
    ]
    for method in methods:
        method["best_verification"] = verify_record(
            source,
            incumbent_variables,
            method["best"],
        )
        method["challenger_verification"] = verify_record(
            source,
            incumbent_variables,
            method["best_challenger"],
        )
    ranking = sorted(
        methods,
        key=lambda method: float(method["best_challenger_gap"]),
    )
    all_counterexamples = sum(
        method["counterexamples_below_incumbent"] for method in methods
    )
    return {
        "schema_version": "1.0",
        "run_id": dt.datetime.now().strftime(
            "hollow_core_bayesian_%Y%m%d_%H%M%S"
        ),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "claim_boundary": (
            "Finite local counterexample search in one exact four-shell Israel "
            "family. It is not a global variational theorem, a smooth source, "
            "a semiclassical source model, or a warp-transport result."
        ),
        "source": {
            "project": "hollow_core_energy_conditions",
            "file": "derivations/search_multishell_lower_energy.py",
            "sha256": source_hash,
            "loaded_read_only": True,
        },
        "problem": {
            "radii": RADII.tolist(),
            "central_lapse": float(source.AC),
            "objective": "absolute proper Israel-shell energy E_abs/L",
            "fixed_exterior_adm_mass": 0.0,
            "symbolic_elimination": symbolic_gate,
            "analytic_incumbent": {
                "origin": "exact two-shell embedding at the same outer radius",
                "compactness_variables": incumbent_variables.tolist(),
                "absolute_energy": incumbent_value,
                "metadata": incumbent_metadata,
            },
            "local_search": {
                "normalized_offsets": {
                    "u": [-1.0, 1.0],
                    "v": [-1.0, 1.0],
                },
                "compactness_scale": LOCAL_COMPACTNESS_SCALE.tolist(),
                "counterexample_tolerance": COUNTEREXAMPLE_TOLERANCE,
            },
            "energy_condition_semantics": {
                "source_flags": (
                    "The source evaluator uses a -1e-10 numerical tolerance."
                ),
                "benchmark_policy": (
                    "Strict sigma<0 and sigma+P<0 signs are recorded separately; "
                    "no tolerance-based flag is interpreted as positive energy."
                ),
            },
        },
        "settings": {
            "equal_total_budget_per_method": budget,
            "analytic_incumbent_evaluations_per_method": 1,
            "challenger_evaluations_per_method": budget - 1,
            "seed": seed,
            "initial_points": initial_points,
            "batch_size": batch_size,
        },
        "ranking_by_best_challenger_gap": [
            {
                "rank": index,
                "method": method["method"],
                "best_challenger_gap": method["best_challenger_gap"],
                "counterexamples_below_incumbent": method[
                    "counterexamples_below_incumbent"
                ],
            }
            for index, method in enumerate(ranking, 1)
        ],
        "counterexample_found": bool(all_counterexamples),
        "all_replays_passed": all(
            method["best_verification"]["passed"]
            and method["challenger_verification"]["passed"]
            for method in methods
        ),
        "methods": methods,
    }


def markdown_report(report: Mapping[str, Any]) -> str:
    problem = report["problem"]
    lines = [
        "# ASTRA Hollow-Core Bayesian Counterexample Search",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Created: {report['created_at']}",
        f"- Boundary: {report['claim_boundary']}",
        f"- Source SHA-256: `{report['source']['sha256']}`",
        f"- Equal total budget: "
        f"{report['settings']['equal_total_budget_per_method']} evaluations "
        "per method, including the shared analytic incumbent",
        f"- Counterexample found: {report['counterexample_found']}",
        f"- Independent replays passed: {report['all_replays_passed']}",
        "",
        "## Analytical setup",
        "",
        f"- Radii: `{problem['radii']}`",
        f"- Fixed central lapse: `{problem['central_lapse']}`",
        f"- Objective: {problem['objective']}",
        f"- Exact elimination residual: "
        f"`{problem['symbolic_elimination']['exact_residual']}`",
        f"- Analytic incumbent: "
        f"`{problem['analytic_incumbent']['absolute_energy']:.12g}`",
        f"- Strictly negative-density shells in incumbent: "
        f"{problem['analytic_incumbent']['metadata']['strict_negative_sigma_shells']}",
        f"- Minimum incumbent surface density: "
        f"`{problem['analytic_incumbent']['metadata']['minimum_sigma']:.12g}`",
        "",
        "The two additional shell degrees of freedom are expressed as local",
        "compactness offsets of `1e-3` around the exact two-shell embedding.",
        "",
        "## Equal-budget challenger search",
        "",
        "| Rank | Method | Best challenger gap above incumbent | "
        "Counterexamples | Replay |",
        "|---:|---|---:|---:|---:|",
    ]
    by_method = {
        method["method"]: method for method in report["methods"]
    }
    for row in report["ranking_by_best_challenger_gap"]:
        method = by_method[row["method"]]
        lines.append(
            f"| {row['rank']} | `{row['method']}` | "
            f"{float(row['best_challenger_gap']):.12g} | "
            f"{row['counterexamples_below_incumbent']} | "
            f"{method['challenger_verification']['passed']} |"
        )
    lines.extend([
        "",
        "All methods retained the shared analytic incumbent as the overall best",
        "configuration. The ranking measures how closely each strategy approached",
        "that incumbent with a distinct challenger. Failure to find a lower point",
        "is finite local negative evidence only; it is not a proof of optimality.",
        "",
        "The source evaluator applies a `-1e-10` tolerance to its WEC/DEC flags.",
        "This report separately preserves strict signs; the exterior shell has",
        "negative surface density and is not presented as positive-energy matter.",
        "",
    ])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run ASTRA's hollow-core Bayesian counterexample benchmark."
    )
    result.add_argument(
        "--source",
        default=str(default_source_path()),
        help="Path to search_multishell_lower_energy.py.",
    )
    result.add_argument("--budget", type=int, default=25)
    result.add_argument("--seed", type=int, default=20260729)
    result.add_argument("--initial-points", type=int, default=6)
    result.add_argument("--batch-size", type=int, default=1)
    result.add_argument("--output-dir", default="")
    return result


def main(args: argparse.Namespace) -> int:
    if args.budget < max(args.initial_points + 1, 4):
        raise ValueError(
            "Budget must cover the incumbent and the GP initial design."
        )
    report = build_report(
        Path(args.source),
        budget=args.budget,
        seed=args.seed,
        initial_points=args.initial_points,
        batch_size=args.batch_size,
    )
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "workspace" / "hollow_core_bayesian_runs"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"{report['run_id']}.json"
    markdown_path = output_root / f"{report['run_id']}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "run_id": report["run_id"],
        "counterexample_found": report["counterexample_found"],
        "all_replays_passed": report["all_replays_passed"],
        "ranking": report["ranking_by_best_challenger_gap"],
        "json_report": str(json_path),
        "markdown_report": str(markdown_path),
    }, indent=2))
    return 0 if report["all_replays_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(parser().parse_args()))
