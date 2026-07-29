"""Budgeted Bayesian experiment planning for ASTRA.

This module is deliberately narrower than ASTRA's analytical research loop.  It
selects numerical evaluations when an objective is expensive, while ASTRA's
symbolic, formal, and human gates remain responsible for scientific acceptance.

The implementation uses only NumPy and SciPy so it can run in ASTRA's existing
production environment.  It provides:

* bounded continuous parameters;
* a Matérn-5/2 Gaussian-process surrogate with fitted hyperparameters;
* expected improvement for minimization or maximization;
* Latin-hypercube initialization and diversity-aware batch suggestions;
* explicit separation of valid observations from operational failures; and
* a small budgeted runner suitable for local or oracle-backed evaluators.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.stats import norm, qmc


Point = Dict[str, float]
CandidateFilter = Callable[[Mapping[str, float]], bool]
Evaluator = Callable[[Mapping[str, float]], Any]


@dataclass(frozen=True)
class ContinuousParameter:
    """One bounded continuous search variable."""

    name: str
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Parameter names must be non-empty.")
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError(f"Bounds for {self.name!r} must be finite.")
        if self.lower >= self.upper:
            raise ValueError(
                f"Lower bound must be smaller than upper bound for {self.name!r}."
            )


@dataclass
class Observation:
    """One attempted objective evaluation."""

    point: Point
    value: Optional[float]
    status: str
    metadata: Dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return (
            self.status == "OK"
            and self.value is not None
            and math.isfinite(self.value)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "point": dict(self.point),
            "value": self.value,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


def expected_improvement(
    mean: np.ndarray,
    standard_deviation: np.ndarray,
    best: float,
    xi: float = 0.01,
) -> np.ndarray:
    """Expected improvement for a minimization objective.

    ``mean`` and ``best`` must already use minimization semantics.  The planner
    negates maximization targets before calling this function.
    """

    mean = np.asarray(mean, dtype=float)
    standard_deviation = np.asarray(standard_deviation, dtype=float)
    improvement = best - mean - float(xi)
    result = np.zeros_like(mean)
    usable = standard_deviation > 1e-12
    if np.any(usable):
        z = improvement[usable] / standard_deviation[usable]
        result[usable] = (
            improvement[usable] * norm.cdf(z)
            + standard_deviation[usable] * norm.pdf(z)
        )
    return np.maximum(result, 0.0)


class GaussianProcessSurrogate:
    """Small Matérn-5/2 GP with maximum-likelihood hyperparameters."""

    def __init__(self, jitter: float = 1e-9) -> None:
        self.jitter = float(jitter)
        self._x: Optional[np.ndarray] = None
        self._y_mean = 0.0
        self._y_scale = 1.0
        self._length_scales: Optional[np.ndarray] = None
        self._signal = 1.0
        self._noise = 1e-4
        self._factor: Optional[Tuple[np.ndarray, bool]] = None
        self._alpha: Optional[np.ndarray] = None

    @staticmethod
    def _kernel(
        left: np.ndarray,
        right: np.ndarray,
        length_scales: np.ndarray,
        signal: float,
    ) -> np.ndarray:
        scaled = (
            left[:, np.newaxis, :] - right[np.newaxis, :, :]
        ) / length_scales[np.newaxis, np.newaxis, :]
        radius_squared = np.sum(scaled * scaled, axis=2)
        radius = np.sqrt(np.maximum(radius_squared, 0.0))
        root_five_radius = math.sqrt(5.0) * radius
        return (signal * signal) * (
            1.0 + root_five_radius + (5.0 / 3.0) * radius_squared
        ) * np.exp(-root_five_radius)

    def fit(self, x: np.ndarray, y: np.ndarray) -> "GaussianProcessSurrogate":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float).reshape(-1)
        if x.ndim != 2 or x.shape[0] != y.shape[0]:
            raise ValueError("GP inputs must have shape (observations, dimensions).")
        if x.shape[0] < 2:
            raise ValueError("At least two valid observations are required for a GP.")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("GP training data must be finite.")

        self._x = x
        self._y_mean = float(np.mean(y))
        raw_scale = float(np.std(y))
        self._y_scale = raw_scale if raw_scale > 1e-12 else 1.0
        normalized_y = (y - self._y_mean) / self._y_scale
        dimensions = x.shape[1]

        def negative_log_likelihood(theta: np.ndarray) -> float:
            length_scales = np.exp(theta[:dimensions])
            signal = float(np.exp(theta[dimensions]))
            noise = float(np.exp(theta[dimensions + 1]))
            covariance = self._kernel(x, x, length_scales, signal)
            covariance.flat[:: covariance.shape[0] + 1] += (
                noise * noise + self.jitter
            )
            try:
                factor = cho_factor(
                    covariance,
                    lower=True,
                    check_finite=False,
                )
                alpha = cho_solve(factor, normalized_y, check_finite=False)
            except np.linalg.LinAlgError:
                return 1e30
            log_determinant_half = float(
                np.sum(np.log(np.diag(factor[0])))
            )
            return (
                0.5 * float(np.dot(normalized_y, alpha))
                + log_determinant_half
                + 0.5 * x.shape[0] * math.log(2.0 * math.pi)
            )

        lower_length = math.log(0.02)
        upper_length = math.log(3.0)
        bounds = (
            [(lower_length, upper_length)] * dimensions
            + [(math.log(0.05), math.log(5.0))]
            + [(math.log(1e-6), math.log(0.5))]
        )
        starts = [
            np.array(
                [math.log(0.25)] * dimensions
                + [math.log(1.0), math.log(1e-3)]
            ),
            np.array(
                [math.log(0.6)] * dimensions
                + [math.log(1.0), math.log(1e-2)]
            ),
            np.array(
                [math.log(0.12)] * dimensions
                + [math.log(0.7), math.log(1e-4)]
            ),
        ]
        fitted = [
            minimize(
                negative_log_likelihood,
                start,
                method="L-BFGS-B",
                bounds=bounds,
            )
            for start in starts
        ]
        best_fit = min(fitted, key=lambda item: float(item.fun))
        theta = np.asarray(best_fit.x, dtype=float)
        self._length_scales = np.exp(theta[:dimensions])
        self._signal = float(np.exp(theta[dimensions]))
        self._noise = float(np.exp(theta[dimensions + 1]))

        covariance = self._kernel(
            x,
            x,
            self._length_scales,
            self._signal,
        )
        covariance.flat[:: covariance.shape[0] + 1] += (
            self._noise * self._noise + self.jitter
        )
        self._factor = cho_factor(
            covariance,
            lower=True,
            check_finite=False,
        )
        self._alpha = cho_solve(
            self._factor,
            normalized_y,
            check_finite=False,
        )
        return self

    def predict(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if (
            self._x is None
            or self._length_scales is None
            or self._factor is None
            or self._alpha is None
        ):
            raise RuntimeError("The GP must be fitted before prediction.")
        x = np.asarray(x, dtype=float)
        if x.ndim != 2 or x.shape[1] != self._x.shape[1]:
            raise ValueError("Prediction dimensions do not match GP training data.")
        cross_covariance = self._kernel(
            x,
            self._x,
            self._length_scales,
            self._signal,
        )
        normalized_mean = cross_covariance @ self._alpha
        solved = cho_solve(
            self._factor,
            cross_covariance.T,
            check_finite=False,
        ).T
        latent_variance = (
            self._signal * self._signal
            - np.sum(cross_covariance * solved, axis=1)
        )
        latent_variance = np.maximum(latent_variance, 1e-14)
        mean = self._y_mean + self._y_scale * normalized_mean
        standard_deviation = self._y_scale * np.sqrt(latent_variance)
        return mean, standard_deviation

    def hyperparameters(self) -> Dict[str, Any]:
        if self._length_scales is None:
            return {}
        return {
            "length_scales": self._length_scales.tolist(),
            "signal": self._signal,
            "noise": self._noise,
        }


class BayesianExperimentPlanner:
    """Select expensive continuous evaluations under a fixed budget."""

    def __init__(
        self,
        parameters: Sequence[ContinuousParameter],
        direction: str = "minimize",
        seed: int = 0,
        initial_points: Optional[int] = None,
        candidate_pool_size: int = 4096,
        xi: float = 0.01,
        candidate_filter: Optional[CandidateFilter] = None,
    ) -> None:
        self.parameters = tuple(parameters)
        if not self.parameters:
            raise ValueError("At least one continuous parameter is required.")
        if len({parameter.name for parameter in self.parameters}) != len(
            self.parameters
        ):
            raise ValueError("Parameter names must be unique.")
        normalized_direction = direction.strip().lower()
        if normalized_direction not in {"minimize", "maximize"}:
            raise ValueError("Direction must be 'minimize' or 'maximize'.")
        self.direction = normalized_direction
        self.seed = int(seed)
        self.initial_points = (
            int(initial_points)
            if initial_points is not None
            else max(4, 2 * len(self.parameters) + 1)
        )
        if self.initial_points < 2:
            raise ValueError("At least two initial points are required.")
        self.candidate_pool_size = max(int(candidate_pool_size), 256)
        self.xi = float(xi)
        self.candidate_filter = candidate_filter
        self.observations: List[Observation] = []
        self._last_hyperparameters: Dict[str, Any] = {}
        initial_sampler = qmc.LatinHypercube(
            d=len(self.parameters),
            seed=self.seed,
        )
        self._initial_design = initial_sampler.random(self.initial_points)

    def _to_unit(self, point: Mapping[str, float]) -> np.ndarray:
        values = []
        for parameter in self.parameters:
            if parameter.name not in point:
                raise ValueError(f"Missing parameter {parameter.name!r}.")
            value = float(point[parameter.name])
            if not math.isfinite(value):
                raise ValueError(f"Parameter {parameter.name!r} must be finite.")
            if value < parameter.lower or value > parameter.upper:
                raise ValueError(
                    f"Parameter {parameter.name!r}={value} lies outside "
                    f"[{parameter.lower}, {parameter.upper}]."
                )
            values.append(
                (value - parameter.lower) / (parameter.upper - parameter.lower)
            )
        return np.asarray(values, dtype=float)

    def _from_unit(self, row: np.ndarray) -> Point:
        return {
            parameter.name: float(
                parameter.lower
                + float(row[index]) * (parameter.upper - parameter.lower)
            )
            for index, parameter in enumerate(self.parameters)
        }

    def _allowed(self, row: np.ndarray) -> bool:
        point = self._from_unit(row)
        return self.candidate_filter is None or bool(self.candidate_filter(point))

    def _attempted_unit_points(self) -> np.ndarray:
        if not self.observations:
            return np.empty((0, len(self.parameters)), dtype=float)
        return np.vstack(
            [self._to_unit(observation.point) for observation in self.observations]
        )

    @staticmethod
    def _far_from(
        row: np.ndarray,
        existing: np.ndarray,
        threshold: float = 1e-8,
    ) -> bool:
        if existing.size == 0:
            return True
        distances = np.linalg.norm(existing - row[np.newaxis, :], axis=1)
        return bool(np.all(distances > threshold))

    def _initial_suggestions(self, count: int) -> List[np.ndarray]:
        attempted = self._attempted_unit_points()
        suggestions = []
        for row in self._initial_design:
            if not self._allowed(row) or not self._far_from(row, attempted):
                continue
            suggestions.append(row)
            attempted = np.vstack([attempted, row])
            if len(suggestions) >= count:
                break
        return suggestions

    def _valid_training_data(self) -> Tuple[np.ndarray, np.ndarray]:
        valid = [observation for observation in self.observations if observation.is_valid]
        if not valid:
            return (
                np.empty((0, len(self.parameters)), dtype=float),
                np.empty((0,), dtype=float),
            )
        x = np.vstack([self._to_unit(observation.point) for observation in valid])
        values = np.asarray([observation.value for observation in valid], dtype=float)
        if self.direction == "maximize":
            values = -values
        return x, values

    def _candidate_pool(self) -> np.ndarray:
        dimensions = len(self.parameters)
        exponent = int(math.ceil(math.log(self.candidate_pool_size, 2)))
        sampler = qmc.Sobol(
            d=dimensions,
            scramble=True,
            seed=self.seed + 104729 * (len(self.observations) + 1),
        )
        global_pool = sampler.random_base2(exponent)[: self.candidate_pool_size]
        training_x, training_y = self._valid_training_data()
        if training_x.shape[0]:
            best_index = int(np.argmin(training_y))
            best = training_x[best_index]
            local_rng = np.random.default_rng(
                self.seed + 7919 * (len(self.observations) + 1)
            )
            local_pool = np.clip(
                best
                + local_rng.normal(
                    0.0,
                    0.08,
                    size=(max(256, self.candidate_pool_size // 4), dimensions),
                ),
                0.0,
                1.0,
            )
            return np.vstack([global_pool, local_pool])
        return global_pool

    def suggest(self, batch_size: int = 1) -> List[Point]:
        """Return unevaluated points.

        Before enough evidence exists, suggestions come from a frozen
        Latin-hypercube design.  Later suggestions maximize expected improvement.
        A batch is selected greedily with a small separation guard; it is a
        practical batch heuristic, not an assertion of exact joint q-EI.
        """

        batch_size = int(batch_size)
        if batch_size < 1:
            raise ValueError("Batch size must be positive.")
        initial = self._initial_suggestions(batch_size)
        if initial:
            return [self._from_unit(row) for row in initial]

        training_x, training_y = self._valid_training_data()
        if training_x.shape[0] < 2:
            pool = self._candidate_pool()
            attempted = self._attempted_unit_points()
            fallback = []
            for row in pool:
                if self._allowed(row) and self._far_from(row, attempted):
                    fallback.append(row)
                    attempted = np.vstack([attempted, row])
                if len(fallback) >= batch_size:
                    break
            return [self._from_unit(row) for row in fallback]

        surrogate = GaussianProcessSurrogate().fit(training_x, training_y)
        self._last_hyperparameters = surrogate.hyperparameters()
        pool = self._candidate_pool()
        attempted = self._attempted_unit_points()
        eligible = np.asarray(
            [
                row
                for row in pool
                if self._allowed(row) and self._far_from(row, attempted)
            ],
            dtype=float,
        )
        if eligible.size == 0:
            return []
        mean, standard_deviation = surrogate.predict(eligible)
        acquisition = expected_improvement(
            mean,
            standard_deviation,
            best=float(np.min(training_y)),
            xi=self.xi,
        )
        order = np.argsort(-acquisition, kind="mergesort")
        chosen: List[np.ndarray] = []
        separation = 0.02 / math.sqrt(len(self.parameters))
        for index in order:
            row = eligible[int(index)]
            if chosen:
                chosen_array = np.vstack(chosen)
                if not self._far_from(row, chosen_array, threshold=separation):
                    continue
            chosen.append(row)
            if len(chosen) >= batch_size:
                break
        if len(chosen) < batch_size:
            for index in order:
                row = eligible[int(index)]
                if any(np.allclose(row, item, atol=1e-12) for item in chosen):
                    continue
                chosen.append(row)
                if len(chosen) >= batch_size:
                    break
        return [self._from_unit(row) for row in chosen]

    def observe(
        self,
        point: Mapping[str, float],
        value: Optional[float],
        status: str = "OK",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Observation:
        """Record evidence without folding execution failures into the GP."""

        normalized_point = self._from_unit(self._to_unit(point))
        normalized_status = status.strip().upper() or "ERROR"
        normalized_value = None if value is None else float(value)
        if normalized_status == "OK" and (
            normalized_value is None or not math.isfinite(normalized_value)
        ):
            raise ValueError("Successful observations require a finite value.")
        observation = Observation(
            point=normalized_point,
            value=normalized_value,
            status=normalized_status,
            metadata=dict(metadata or {}),
        )
        self.observations.append(observation)
        return observation

    def best_observation(self) -> Optional[Observation]:
        valid = [observation for observation in self.observations if observation.is_valid]
        if not valid:
            return None
        selector = min if self.direction == "minimize" else max
        return selector(valid, key=lambda observation: float(observation.value))

    def state(self) -> Dict[str, Any]:
        best = self.best_observation()
        return {
            "schema_version": "1.0",
            "direction": self.direction,
            "seed": self.seed,
            "parameters": [asdict(parameter) for parameter in self.parameters],
            "settings": {
                "initial_points": self.initial_points,
                "candidate_pool_size": self.candidate_pool_size,
                "xi": self.xi,
            },
            "attempts": len(self.observations),
            "valid_observations": sum(
                observation.is_valid for observation in self.observations
            ),
            "operational_failures": sum(
                not observation.is_valid for observation in self.observations
            ),
            "best": best.to_dict() if best is not None else None,
            "last_gp_hyperparameters": dict(self._last_hyperparameters),
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
        }


def run_budgeted_search(
    planner: BayesianExperimentPlanner,
    evaluator: Evaluator,
    budget: int,
    batch_size: int = 1,
) -> Dict[str, Any]:
    """Evaluate planner suggestions until the attempt budget is exhausted.

    An evaluator may return either a numeric value or ``(value, metadata)``.
    Exceptions are recorded as operational failures and are never converted into
    bad objective values.
    """

    budget = int(budget)
    if budget < 1:
        raise ValueError("Budget must be positive.")
    while len(planner.observations) < budget:
        remaining = budget - len(planner.observations)
        suggestions = planner.suggest(min(int(batch_size), remaining))
        if not suggestions:
            break
        for point in suggestions:
            try:
                evaluated = evaluator(point)
                if (
                    isinstance(evaluated, tuple)
                    and len(evaluated) == 2
                ):
                    value, metadata = evaluated
                else:
                    value, metadata = evaluated, {}
                planner.observe(
                    point,
                    float(value),
                    status="OK",
                    metadata=metadata,
                )
            except Exception as exc:  # evidence separation is intentional
                planner.observe(
                    point,
                    None,
                    status="ERROR",
                    metadata={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
    return planner.state()
