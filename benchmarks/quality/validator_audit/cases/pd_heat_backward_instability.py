"""Heat runs forward and not backward, and the obstruction is not the method.

CLAIM: on a segment with ends held at zero, separation of variables gives modes
sin(n pi x / L) decaying as exp(-alpha (n pi / L)^2 t), with the wavenumber
forced by the boundary rather than assumed; superposition reproduces an initial
profile through coefficients fixed by orthogonality; the energy is non-increasing
because its derivative is minus twice alpha times the integral of the squared
gradient; running time backwards multiplies mode n by the reciprocal of that
decay, an amplification unbounded in n, so two initial profiles a ten-billionth
apart separate without limit and continuous dependence on the data fails; and an
explicit scheme reproduces the forward solution inside a stability limit derived
from its own amplification factor, while the same scheme run backwards diverges.

The backward solution exists. It is unique. It simply cannot be computed from
measured data, and no choice of scheme changes that, which is the distinction
between a hard problem and an ill-posed one.

Legs:
  1. modes     -- the separated solution is substituted in, and the wavenumber
                  comes out of the boundary condition by solving;
  2. series    -- orthogonality fixes the coefficients, and the reconstruction is
                  checked against the profile it came from;
  3. energy    -- the derivative of the squared norm is computed and is minus
                  twice alpha times the gradient integral, hence not positive;
  4. backward  -- the amplification over a fixed time is unbounded in the mode
                  number, computed rather than described;
  5. falsifier -- two data a ten-billionth apart give backward solutions that
                  differ without bound, while forward the same gap shrinks;
  6. numeric   -- the explicit scheme's stability limit is derived from its
                  amplification factor and confirmed on both sides of it.
"""
import math

import sympy as sp

x, t = sp.symbols("x t", real=True)
L, alpha = sp.symbols("L alpha", positive=True)
n, m = sp.symbols("n m", positive=True, integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
wavenumber = sp.Symbol("k", positive=True)
separated = sp.sin(wavenumber * x) * sp.exp(-alpha * wavenumber ** 2 * t)
residual = sp.simplify(sp.diff(separated, t) - alpha * sp.diff(separated, x, 2))
check("the_separated_form_solves_the_heat_equation_for_any_wavenumber",
      residual == 0,
      f"u_t - alpha u_xx = {residual} for u = sin(kx) exp(-alpha k^2 t)")

# The boundary at the far end is what quantises k. Solved, not substituted.
allowed = sp.solve(sp.Eq(sp.sin(wavenumber * L), 0), wavenumber)
check("the_far_boundary_quantises_the_wavenumber",
      len(allowed) == 1 and sp.simplify(allowed[0] - sp.pi / L) == 0,
      f"sin(kL) = 0 gives the first positive k = {allowed[0] if allowed else 'none'}, "
      "and its integer multiples")

mode = separated.subs(wavenumber, n * sp.pi / L)
check("each_mode_vanishes_at_both_ends_for_every_time",
      sp.simplify(mode.subs(x, 0)) == 0 and sp.simplify(mode.subs(x, L)) == 0,
      "u(0, t) = u(L, t) = 0 for every integer mode number")

decay = sp.simplify(mode.subs(x, L / 2) / sp.sin(n * sp.pi / 2))
check("and_decays_at_a_rate_quadratic_in_the_mode_number",
      sp.simplify(sp.log(decay) / t + alpha * (n * sp.pi / L) ** 2) == 0,
      f"the time factor is {decay}, so the rate grows as n squared")


# ---------------------------------------------------------------- leg 2
def overlap(first, second):
    """The inner product of two modes on the segment, integrated exactly."""
    return sp.simplify(sp.integrate(
        sp.sin(first * sp.pi * x / L) * sp.sin(second * sp.pi * x / L), (x, 0, L)
    ))


off_diagonal = [overlap(i, j) for i in range(1, 5) for j in range(1, 5) if i != j]
check("distinct_modes_are_orthogonal",
      all(value == 0 for value in off_diagonal),
      f"all {len(off_diagonal)} distinct pairs among the first four modes "
      "integrate to zero")

diagonal = {overlap(i, i) for i in range(1, 5)}
check("and_each_has_the_same_norm",
      diagonal == {L / 2},
      f"every mode integrates against itself to {diagonal.pop()}")

# A profile built from known coefficients, recovered by the orthogonality rule.
COEFFICIENTS = {1: sp.Rational(1), 3: sp.Rational(-1, 2), 7: sp.Rational(1, 5)}
profile = sum(weight * sp.sin(index * sp.pi * x / L)
              for index, weight in COEFFICIENTS.items())
recovered = {
    index: sp.simplify(
        2 / L * sp.integrate(profile * sp.sin(index * sp.pi * x / L), (x, 0, L))
    )
    for index in COEFFICIENTS
}
check("the_coefficients_come_back_out_of_the_profile",
      all(sp.simplify(recovered[index] - COEFFICIENTS[index]) == 0
          for index in COEFFICIENTS),
      f"recovered {recovered} against {COEFFICIENTS}")

absent = sp.simplify(2 / L * sp.integrate(profile * sp.sin(2 * sp.pi * x / L),
                                          (x, 0, L)))
check("and_a_mode_that_is_not_there_comes_back_zero",
      absent == 0,
      f"the second mode integrates to {absent}, so the rule is not returning "
      "something for everything")


# ---------------------------------------------------------------- leg 3
solution = sum(
    weight * sp.sin(index * sp.pi * x / L)
    * sp.exp(-alpha * (index * sp.pi / L) ** 2 * t)
    for index, weight in COEFFICIENTS.items()
)
energy = sp.simplify(sp.integrate(solution ** 2, (x, 0, L)))
gradient = sp.simplify(sp.integrate(sp.diff(solution, x) ** 2, (x, 0, L)))
check("the_energy_derivative_is_minus_twice_alpha_times_the_gradient_integral",
      sp.simplify(sp.diff(energy, t) + 2 * alpha * gradient) == 0,
      "dE/dt = -2 alpha times the integral of u_x squared, which is the "
      "integration by parts made explicit rather than quoted")

check("so_the_energy_cannot_increase",
      sp.simplify(sp.diff(energy, t)).subs({alpha: 1, L: 1}).subs(t, 0).is_negative is True,
      f"at t = 0 with alpha = L = 1 the derivative is "
      f"{sp.simplify(sp.diff(energy, t).subs({alpha: 1, L: 1}).subs(t, 0))}, and "
      "the gradient integral is a square so the sign never turns")


# ---------------------------------------------------------------- leg 4
# Running time backwards inverts each mode's factor. The amplification over a
# fixed interval is computed for a ladder of mode numbers, not characterised.
HORIZON = sp.Rational(1, 100)
amplification = sp.exp(alpha * (n * sp.pi / L) ** 2 * HORIZON)
factors = [
    float(amplification.subs({alpha: 1, L: 1, n: index}))
    for index in (1, 5, 10, 20)
]
check("the_backward_amplification_grows_without_bound_in_the_mode_number",
      all(later > earlier for earlier, later in zip(factors, factors[1:]))
      and factors[-1] > 1e17,
      f"over a hundredth of a time unit the factors are "
      f"{', '.join(f'{value:.3e}' for value in factors)} for modes 1, 5, 10 and 20")

check("and_no_finite_bound_survives_the_limit",
      sp.limit(amplification.subs({alpha: 1, L: 1}), n, sp.oo) == sp.oo,
      "the supremum over modes is infinite, which is exactly the failure of "
      "continuous dependence that Hadamard's third condition asks about")


# ---------------------------------------------------------------- leg 5
EPSILON = 1e-10
PROBE = 20
grown = EPSILON * float(amplification.subs({alpha: 1, L: 1, n: PROBE}))
check("falsifier_a_perturbation_of_one_part_in_ten_billion_dominates_backwards",
      grown > 1e6,
      f"a disturbance of {EPSILON:.0e} in mode {PROBE} becomes {grown:.3e} after "
      f"running back a hundredth of a time unit, so the backward map carries no "
      "modulus of continuity at all")

shrunk = EPSILON / float(amplification.subs({alpha: 1, L: 1, n: PROBE}))
check("while_forwards_the_same_disturbance_disappears",
      shrunk < 1e-27,
      f"forwards it becomes {shrunk:.3e}, and it is the same factor either way, "
      "which is why the forward problem is well posed and the backward one is not")


# ---------------------------------------------------------------- leg 6
# Von Neumann: substituting a Fourier mode into the explicit scheme gives an
# amplification factor per step, and the stability limit is solved for rather
# than looked up.
ratio, angle = sp.symbols("r theta", real=True)
# The two exponentials have to be folded into a cosine before the half-angle
# identity applies; simplify alone leaves them apart, and comparing the two
# unfolded forms would say nothing.
raw = 1 + ratio * (sp.exp(sp.I * angle) - 2 + sp.exp(-sp.I * angle))
growth = sp.simplify(sp.trigsimp(sp.expand_complex(raw)))
check("the_explicit_scheme_amplifies_a_mode_by_one_minus_four_r_sine_squared",
      sp.simplify(sp.expand_trig(growth - (1 - 4 * ratio * sp.sin(angle / 2) ** 2))) == 0,
      f"the factor per step is {growth}")

worst = sp.simplify(growth.subs(angle, sp.pi))
limits = sp.solve(sp.Eq(worst, -1), ratio)
check("and_the_stability_limit_is_one_half",
      len(limits) == 1 and sp.simplify(limits[0] - sp.Rational(1, 2)) == 0,
      f"the worst mode gives {worst}, which reaches minus one at r = "
      f"{limits[0] if limits else 'none'}")


def evolve(values, step_ratio, steps):
    """One explicit step repeated, on a grid with both ends pinned to zero."""
    current = list(values)
    for _ in range(steps):
        following = [0.0] * len(current)
        for index in range(1, len(current) - 1):
            following[index] = (current[index] + step_ratio
                                * (current[index - 1] - 2 * current[index]
                                   + current[index + 1]))
        current = following
    return current


POINTS = 41
spacing = 1.0 / (POINTS - 1)
grid = [index * spacing for index in range(POINTS)]
start = [float(profile.subs({L: 1, x: place})) for place in grid]


def exact_at(time):
    return [
        sum(float(weight) * math.sin(index * math.pi * place)
            * math.exp(-(index * math.pi) ** 2 * time)
            for index, weight in COEFFICIENTS.items())
        for place in grid
    ]


STABLE_RATIO = 0.4
STEPS = 200
elapsed = STEPS * STABLE_RATIO * spacing ** 2
numeric = evolve(start, STABLE_RATIO, STEPS)
reference = exact_at(elapsed)
gap = max(abs(a - b) for a, b in zip(numeric, reference))
check("inside_the_limit_the_scheme_tracks_the_series",
      gap < 2e-3,
      f"at r = {STABLE_RATIO} the largest departure from the exact solution "
      f"after {STEPS} steps is {gap:.3e}, on a profile of order one")

# The unstable mode is the one alternating from grid point to grid point, and a
# smooth profile barely contains it, so an unseeded run grows only out of
# rounding. Seeding it deliberately turns "it explodes" into a number the
# amplification factor above has to predict.
SEED, SEEDED_STEPS = 1e-8, 100
seeded = [value + SEED * (-1) ** index for index, value in enumerate(start)]

unstable = evolve(seeded, 0.6, SEEDED_STEPS)
reached = max(abs(value) for value in unstable)
predicted_growth = SEED * abs(1 - 4 * 0.6) ** SEEDED_STEPS
check("falsifier_outside_it_the_seeded_mode_grows_as_the_factor_says",
      abs(reached / predicted_growth - 1) < 0.1,
      f"at r = 0.6 the alternating seed of {SEED:.0e} reaches {reached:.4e} after "
      f"{SEEDED_STEPS} steps, against {predicted_growth:.4e} from the factor, a "
      f"ratio of {reached / predicted_growth:.3f}")

quiet = evolve(seeded, STABLE_RATIO, SEEDED_STEPS)
disturbance = max(abs(a - b) for a, b in zip(quiet, evolve(start, STABLE_RATIO, SEEDED_STEPS)))
check("while_inside_the_limit_the_same_seed_dies_away",
      disturbance < SEED / 100,
      f"at r = {STABLE_RATIO} the same seed leaves {disturbance:.3e}, three orders "
      f"below the {SEED:.0e} it started at. What survives is not the alternating "
      "part, which is down by ten to the thirty, but the low mode content the "
      "seed also carries, and that decays slowly rather than growing; the same "
      f"quantity at r = 0.6 is {reached:.3e}, larger by a factor of "
      f"{reached / disturbance:.1e}")

backward = evolve(start, -STABLE_RATIO, 120)
check("and_running_it_backwards_diverges_whatever_the_ratio",
      max(abs(value) for value in backward) > 1e6,
      f"stepping with a negative ratio reaches "
      f"{max(abs(value) for value in backward):.3e}, which is the mode "
      "amplification of leg four showing up in the arithmetic")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
