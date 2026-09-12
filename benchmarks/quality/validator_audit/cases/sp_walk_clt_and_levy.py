"""Sums of many steps go Gaussian, unless the variance is infinite.

CLAIM: for independent steps of zero mean the variance of the sum adds, so the
spread grows as the square root of the number of steps; the scaled sum
approaches a standard normal, and the approach obeys the Berry-Esseen rate; the
continuum limit is the diffusion equation, whose Gaussian solution carries the
variance the walk predicts; and every line of that collapses for a Cauchy step,
whose second moment diverges. There the sum scales as n rather than its square
root, the scaled sum keeps the shape of a single step, and an empirical variance
returns a finite-looking number that simply grows with however much data was
taken.

The last point is the trap. Nothing warns you. The estimate comes back, it has a
value, and the value is an artefact of the sample size.

Legs:
  1. adds      -- the variance of the sum is derived from independence, with the
                  cross terms shown to vanish;
  2. scale     -- the measured spread matches sigma root n inside its own
                  sampling error;
  3. normal    -- the distance to the normal falls along a ladder, stays under
                  the Berry-Esseen bound, and reaches the simulation floor;
  4. diffusion -- the Gaussian with variance twice D t solves the diffusion
                  equation, and D is matched to the walk;
  5. falsifier -- the Cauchy second moment diverges, so an empirical variance
                  grows with the sample instead of settling;
  6. stable    -- and its sum scales as n, the scaled sum keeping the shape of
                  one step, so the normal limit is simply absent.
"""
import math

import numpy as np
import sympy as sp
from sympy.stats import E as expectation
from sympy.stats import Uniform, variance

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
HALF = sp.sqrt(3)
steps = [Uniform(f"X_{index}", -HALF, HALF) for index in range(4)]
total = sum(steps)

check("each_step_has_zero_mean_and_unit_variance",
      sp.simplify(expectation(steps[0])) == 0
      and sp.simplify(variance(steps[0]) - 1) == 0,
      f"a uniform step on plus and minus root three has mean "
      f"{sp.simplify(expectation(steps[0]))} and variance "
      f"{sp.simplify(variance(steps[0]))}")

check("the_variance_of_the_sum_is_the_number_of_steps",
      sp.simplify(variance(total) - len(steps)) == 0,
      f"four independent steps give Var = {sp.simplify(variance(total))}")

# Why it adds: the cross terms are products of independent centred variables.
cross = sp.simplify(expectation(steps[0] * steps[1]))
check("because_the_cross_terms_vanish_under_independence",
      cross == 0,
      f"E[X_1 X_2] = {cross}, so the square of the sum keeps only its diagonal "
      "and the spread grows as the square root of the count")


# ---------------------------------------------------------------- leg 2
SAMPLES = 200000
LADDER = [1, 5, 20, 100]
rng = np.random.default_rng(20260912)
edge = float(HALF)
sums = {
    count: rng.uniform(-edge, edge, size=(SAMPLES, count)).sum(axis=1)
    for count in LADDER
}

# The sampling error of an estimated standard deviation is itself about
# sigma / root of twice the sample size, so the band is computed rather than set.
band = 6 / math.sqrt(2 * SAMPLES)
spreads = {count: float(np.std(values, ddof=1)) for count, values in sums.items()}
worst = max(abs(spreads[count] / math.sqrt(count) - 1) for count in LADDER)
check("the_spread_grows_as_the_square_root_of_the_number_of_steps",
      bool(worst < band),
      f"the measured spread over root n departs from one by at most {worst:.5f} "
      f"across {LADDER}, inside the {band:.5f} that {SAMPLES} samples allow")


# ---------------------------------------------------------------- leg 3
def normal_cdf(values):
    return 0.5 * (1.0 + np.vectorize(math.erf)(values / math.sqrt(2.0)))


def distance_to_normal(values):
    """The largest gap between the empirical distribution and the normal one."""
    ordered = np.sort(values)
    empirical = np.arange(1, len(ordered) + 1) / len(ordered)
    return float(np.max(np.abs(empirical - normal_cdf(ordered))))


distances = {count: distance_to_normal(values / math.sqrt(count))
             for count, values in sums.items()}
check("the_distance_to_the_normal_falls_along_the_ladder",
      all(distances[later] < distances[earlier]
          for earlier, later in zip(LADDER, LADDER[1:])),
      f"sup|F - Phi| runs {', '.join(f'{distances[c]:.5f}' for c in LADDER)} "
      f"over {LADDER}")

# Berry-Esseen: the gap is at most a constant times the third absolute moment
# over the cube of the spread and the root of the count. The third moment is
# computed here rather than looked up, so the bound is the theorem's and not a
# number chosen to fit.
x = sp.Symbol("x", real=True)
third = sp.simplify(sp.integrate(sp.Abs(x) ** 3 / (2 * HALF), (x, -HALF, HALF)))
bounds = {count: 0.47 * float(third) / math.sqrt(count) for count in LADDER}
check("and_stays_under_the_berry_esseen_bound_at_every_rung",
      all(distances[count] < bounds[count] for count in LADDER),
      f"the third absolute moment is {third}, giving bounds "
      f"{', '.join(f'{bounds[c]:.4f}' for c in LADDER)} against the measured "
      f"{', '.join(f'{distances[c]:.4f}' for c in LADDER)}")

floor = 1.0 / math.sqrt(SAMPLES)
check("and_the_last_rung_has_reached_the_simulation_floor",
      bool(distances[LADDER[-1]] < 1.5 * floor),
      f"at {LADDER[-1]} steps the gap is {distances[LADDER[-1]]:.5f} against a "
      f"floor of {floor:.5f} set by {SAMPLES} samples, so what remains is the "
      "measurement and not the approximation")


# ---------------------------------------------------------------- leg 4
position, time, spread_symbol = sp.symbols("x t D", positive=True)
density = sp.exp(-position ** 2 / (4 * spread_symbol * time)) / sp.sqrt(
    4 * sp.pi * spread_symbol * time)
residual = sp.simplify(
    sp.diff(density, time) - spread_symbol * sp.diff(density, position, 2)
)
check("the_spreading_gaussian_solves_the_diffusion_equation",
      residual == 0,
      f"the residual is {residual} for a width growing as twice D t")

interval = sp.Symbol("tau", positive=True)
matched = sp.solve(sp.Eq(2 * spread_symbol * interval, 1), spread_symbol)
check("and_the_diffusion_constant_is_fixed_by_matching_the_walk",
      len(matched) == 1
      and sp.simplify(matched[0] - 1 / (2 * interval)) == 0,
      f"one step of unit variance every tau makes D = "
      f"{matched[0] if matched else 'none'}, which is the walk's own spread "
      "written as a rate")


# ---------------------------------------------------------------- leg 5
heavy = sp.integrate(x ** 2 / (sp.pi * (1 + x ** 2)), (x, -sp.oo, sp.oo))
check("falsifier_the_cauchy_second_moment_diverges",
      heavy == sp.oo,
      f"the integral of x squared against the Cauchy density is {heavy}, so "
      "there is no variance for the sum to add")

# Taken as a median over repeats rather than from one sample at each size: a
# single Cauchy variance is itself wildly variable, and a claim about how the
# estimate behaves cannot rest on one draw of it.
SIZES = (1000, 10000, 100000)
REPEATS = 15
growth = [
    float(np.median([np.var(rng.standard_cauchy(size), ddof=1)
                     for _ in range(REPEATS)]))
    for size in SIZES
]
check("so_an_empirical_variance_grows_with_the_sample_instead_of_settling",
      all(later > 2 * earlier for earlier, later in zip(growth, growth[1:])),
      f"the median of {REPEATS} sample variances reads "
      f"{', '.join(f'{v:,.0f}' for v in growth)} at {', '.join(f'{s:,}' for s in SIZES)} "
      "draws, more than doubling each decade, so any single figure quoted for "
      "it is a fact about the sample size")


# ---------------------------------------------------------------- leg 6
CAUCHY_LADDER = [1, 10, 100]
cauchy_sums = {
    count: rng.standard_cauchy(size=(50000, count)).sum(axis=1)
    for count in CAUCHY_LADDER
}
by_count = {count: float(np.median(np.abs(values)) / count)
            for count, values in cauchy_sums.items()}
by_root = {count: float(np.median(np.abs(values)) / math.sqrt(count))
           for count, values in cauchy_sums.items()}

check("the_cauchy_sum_scales_as_the_number_of_steps",
      all(abs(by_count[count] - 1) < 0.1 for count in CAUCHY_LADDER),
      f"the typical size over n is "
      f"{', '.join(f'{by_count[c]:.3f}' for c in CAUCHY_LADDER)} across "
      f"{CAUCHY_LADDER}, flat, so one step already has the shape of the whole")

check("while_the_square_root_scaling_runs_away",
      all(by_root[later] > 2 * by_root[earlier]
          for earlier, later in zip(CAUCHY_LADDER, CAUCHY_LADDER[1:])),
      f"the same quantity over root n is "
      f"{', '.join(f'{by_root[c]:.3f}' for c in CAUCHY_LADDER)}, growing as root "
      "n itself, which is the central limit scaling failing rather than being "
      "slow to arrive")

cauchy_distance = {
    count: distance_to_normal(values / math.sqrt(count))
    for count, values in cauchy_sums.items()
}
check("and_the_scaled_sum_does_not_approach_a_normal_at_all",
      all(cauchy_distance[count] > 0.1 for count in CAUCHY_LADDER)
      and cauchy_distance[CAUCHY_LADDER[-1]] > cauchy_distance[CAUCHY_LADDER[0]],
      f"the distance to the normal is "
      f"{', '.join(f'{cauchy_distance[c]:.3f}' for c in CAUCHY_LADDER)}, not "
      "falling but rising, so the limit is absent and not merely far off")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
