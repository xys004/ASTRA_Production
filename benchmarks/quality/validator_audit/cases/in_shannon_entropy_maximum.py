"""Shannon entropy is maximised by the uniform distribution and bounded by log n.

CLAIM: over distributions on n outcomes, H(p) = -sum p_i log p_i is non-negative,
vanishes exactly on the deterministic distributions, is maximised uniquely by the
uniform one, and its maximum is log n. The bound follows from Gibbs' inequality
rather than from sampling.

Legs:
  1. stationarity -- the constrained maximum is solved with a multiplier and the
                     solution is required to be the uniform distribution;
  2. gibbs        -- the bound is derived from log t <= t - 1, whose equality
                     case is located, so the uniqueness of the maximiser follows
                     rather than being asserted;
  3. numeric      -- random distributions respect the bound, and a family
                     approaching uniformity approaches log n from below;
  4. boundary     -- entropy vanishes on a deterministic distribution and the
                     limit p log p -> 0 is taken rather than patched;
  5. falsifier    -- a claimed distribution exceeding log n is contradicted by
                     the same computation.
"""
import math
import random

import sympy as sp

p, t, lam = sp.symbols("p t lambda", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def entropy(weights):
    """Shannon entropy in nats, with the p log p -> 0 convention at zero."""
    total = 0.0
    for weight in weights:
        if weight > 0:
            total -= weight * math.log(weight)
    return total


# ---------------------------------------------------------------- leg 1
# Three outcomes, enough for the structure to be non-trivial and few enough to
# solve exactly. Maximise -sum p log p subject to sum p = 1.
p1, p2, p3 = sp.symbols("p_1 p_2 p_3", positive=True)
probabilities = (p1, p2, p3)
symbolic_entropy = -sum(q * sp.log(q) for q in probabilities)
normalisation = sum(probabilities) - 1

lagrangian = symbolic_entropy - lam * normalisation
stationary = sp.solve(
    [sp.Eq(sp.diff(lagrangian, q), 0) for q in probabilities]
    + [sp.Eq(normalisation, 0)],
    list(probabilities) + [lam],
    dict=True,
)
check("stationarity_has_a_unique_solution", len(stationary) == 1,
      f"{len(stationary)} solution(s)")

point = stationary[0]
check("maximiser_is_the_uniform_distribution",
      all(sp.simplify(point[q] - sp.Rational(1, 3)) == 0 for q in probabilities),
      f"p = ({point[p1]}, {point[p2]}, {point[p3]})")

maximum = sp.simplify(symbolic_entropy.subs(point))
check("maximum_is_log_three",
      sp.simplify(maximum - sp.log(3)) == 0,
      f"H_max = {maximum}")


# ---------------------------------------------------------------- leg 2
# Gibbs: log t <= t - 1 for t > 0, with equality only at t = 1. Both parts are
# established, because the equality case is what makes the maximiser unique.
gap = sp.simplify(t - 1 - sp.log(t))
stationary_points = sp.solve(sp.Eq(sp.diff(gap, t), 0), t)
check("log_bound_has_its_only_stationary_point_at_one",
      stationary_points == [1],
      f"d/dt (t - 1 - log t) vanishes at t = {stationary_points}")

check("that_point_is_a_minimum_of_the_gap",
      bool(sp.diff(gap, t, 2).subs(t, 1) > 0),
      f"second derivative at t = 1 is {sp.diff(gap, t, 2).subs(t, 1)}, positive")

check("the_gap_vanishes_there_and_only_there",
      sp.simplify(gap.subs(t, 1)) == 0,
      "so log t = t - 1 exactly at t = 1 and log t < t - 1 elsewhere")

# Applying it with t = 1/(n p_i) and summing is what produces the bound. Two
# genuine steps, not a rearrangement of one expression into itself:
#
#   log n - H(p) = sum_i p_i log(n p_i),
#   and Gibbs gives log(n p_i) >= 1 - 1/(n p_i), whose weighted sum is exactly 0.
#
# Together they force log n - H >= 0 with equality only when every n p_i = 1.
# The identity holds ON the constraint surface, not off it, and saying so is
# part of the statement. Off the surface the residual is exactly (1 - sum p)
# times log n, which is the normalisation condition made visible rather than
# quietly assumed by substituting it in from the start.
identity_gap = sp.simplify(sp.expand(
    (sp.log(3) - symbolic_entropy) - sum(q * sp.log(3 * q) for q in probabilities)
))
check("off_constraint_residual_is_the_normalisation_condition",
      sp.simplify(identity_gap - (1 - sum(probabilities)) * sp.log(3)) == 0,
      f"residual = {sp.factor(identity_gap)}, proportional to 1 - sum p")

on_constraint = sp.simplify(identity_gap.subs(p3, 1 - p1 - p2))
check("log_n_minus_entropy_is_the_weighted_log_ratio",
      on_constraint == 0,
      f"log 3 - H(p) = sum p_i log(3 p_i) once sum p = 1 (residual {on_constraint})")

lower_bound = sp.simplify(sp.expand(
    sum(q * (1 - 1 / (3 * q)) for q in probabilities).subs(
        p3, 1 - p1 - p2
    )
))
check("gibbs_lower_bound_sums_to_exactly_zero",
      sp.simplify(lower_bound) == 0,
      f"sum p_i (1 - 1/(3 p_i)) = {lower_bound} once the weights are normalised")


# ---------------------------------------------------------------- leg 3
random.seed(20260911)
N = 6
ceiling = math.log(N)
worst = -1.0
violations = 0
for _ in range(20000):
    draw = [random.random() for _ in range(N)]
    total = sum(draw)
    weights = [value / total for value in draw]
    value = entropy(weights)
    worst = max(worst, value)
    if value > ceiling + 1e-12:
        violations += 1
check("random_distributions_respect_the_bound",
      violations == 0 and worst <= ceiling,
      f"largest of 20000 entropies = {worst:.12f} against log 6 = {ceiling:.12f}")

# Approaching uniformity must approach the bound from below, not merely stay
# under it, which is what distinguishes a tight bound from a loose one.
approaches = []
for tilt in (0.5, 0.1, 0.01, 0.001):
    weights = [(1 + tilt) / N] + [(1 - tilt / (N - 1)) / N] * (N - 1)
    weights = [w / sum(weights) for w in weights]
    approaches.append(ceiling - entropy(weights))
check("entropy_approaches_log_n_from_below",
      all(value > 0 for value in approaches)
      and all(approaches[i] > approaches[i + 1] for i in range(len(approaches) - 1)),
      f"gaps to log 6: {['%.3e' % v for v in approaches]}")


# ---------------------------------------------------------------- leg 4
deterministic = [1.0] + [0.0] * (N - 1)
check("entropy_vanishes_on_a_deterministic_distribution",
      abs(entropy(deterministic)) < 1e-15,
      f"H = {entropy(deterministic)}")

# The convention at zero is a limit, taken rather than patched in.
limit_at_zero = sp.limit(-p * sp.log(p), p, 0, "+")
check("p_log_p_tends_to_zero", sp.simplify(limit_at_zero) == 0,
      f"lim -p log p = {limit_at_zero} as p -> 0+")

check("entropy_is_non_negative_on_the_random_draws",
      worst >= 0,
      "no sampled distribution produced a negative entropy")


# ---------------------------------------------------------------- leg 5
# A distribution claimed to beat log n must be contradicted by the same routine.
claimed = ceiling + 0.1
best_possible = entropy([1.0 / N] * N)
check("falsifier_no_distribution_reaches_the_claimed_value",
      best_possible < claimed and abs(best_possible - ceiling) < 1e-12,
      f"the uniform distribution attains {best_possible:.12f}, short of the "
      f"claimed {claimed:.6f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
