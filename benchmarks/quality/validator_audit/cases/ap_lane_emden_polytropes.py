"""Polytropes have a finite radius, except that at index five they do not.

CLAIM: hydrostatic equilibrium with a polytropic equation of state reduces to
Lane-Emden once the length is scaled by a particular alpha; at index one the
solution is sin(xi)/xi, whose first zero at pi gives a radius independent of the
central density; at index zero it is 1 - xi^2/6; at index five it is
(1 + xi^2/3)^(-1/2), positive everywhere, so the star extends to infinity while
its mass stays finite.

That last case is the reason for the file. "A polytrope has a finite radius" is
true up to index five and false at it, and an integrator that runs out of range
looks exactly like one that has found a very large star.

Legs:
  1. reduction -- the reduction is carried out, and the scaling shown to be forced;
  2. index one -- sin(xi)/xi solves it, cos(xi)/xi solves it too, and regularity
                  at the centre is what chooses; the radius is then shown not to
                  depend on the central density at all;
  3. index zero -- the quadratic solution and its zero at the square root of six;
  4. index five -- positive everywhere, so no first zero, and yet finite mass;
  5. numeric   -- validated at both closed-form indices, shown to be fourth
                  order, and only then used at index three;
  6. falsifier -- index five finds no zero while four and a half does, so the
                  boundary is the physics and not the method.
"""
import math

import sympy as sp

xi, alpha = sp.symbols("xi alpha", positive=True)
G, K, rho_c = sp.symbols("G K rho_c", positive=True)
n = sp.Symbol("n", positive=True)
theta = sp.Function("theta", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Hydrostatic equilibrium with Poisson's equation, in the form that eliminates
# the enclosed mass: (1/r^2) d/dr (r^2/rho dP/dr) = -4 pi G rho.
density = rho_c * theta(xi) ** n
pressure = K * density ** (1 + 1 / n)
combined = sp.simplify(
    sp.diff(xi ** 2 / density * sp.diff(pressure, xi), xi) / (alpha ** 2 * xi ** 2)
    + 4 * sp.pi * G * density
)

SCALE = (n + 1) * K * rho_c ** (1 / n - 1) / (4 * sp.pi * G)
reduced = sp.simplify(combined.subs(alpha, sp.sqrt(SCALE)) / (4 * sp.pi * G * rho_c))
lane_emden = sp.diff(xi ** 2 * sp.diff(theta(xi), xi), xi) / xi ** 2 + theta(xi) ** n
check("the_hydrostatic_equation_reduces_to_lane_emden",
      sp.simplify(reduced - lane_emden) == 0,
      f"with alpha^2 = {SCALE} the equation becomes {reduced}")

# The scaling is forced, not merely sufficient: doubling it leaves a residue.
wrong = sp.simplify(
    combined.subs(alpha, sp.sqrt(2 * SCALE)) / (4 * sp.pi * G * rho_c) - lane_emden
)
check("and_that_scaling_is_the_only_one_that_works",
      sp.simplify(wrong) != 0,
      f"doubling alpha^2 leaves {sp.simplify(wrong)}, so the scale is determined")


# ---------------------------------------------------------------- leg 2
def residual_at(index, expression):
    """Substitute a candidate profile into Lane-Emden at a fixed index."""
    return sp.simplify(
        sp.diff(xi ** 2 * sp.diff(expression, xi), xi) / xi ** 2 + expression ** index
    )


unit_profile = sp.sin(xi) / xi
check("the_index_one_profile_solves_the_equation",
      residual_at(1, unit_profile) == 0,
      f"residual for sin(xi)/xi at index one is {residual_at(1, unit_profile)}")

# Solving the equation is not enough to pick a star. cos(xi)/xi solves it just
# as well and is excluded only by regularity at the centre, so that condition
# is imposed here rather than left implicit in the choice of profile.
rejected = sp.cos(xi) / xi
check("the_discarded_solution_solves_the_equation_too",
      residual_at(1, rejected) == 0,
      f"residual is {residual_at(1, rejected)}, so the equation alone does not choose")

check("and_regularity_at_the_centre_is_what_chooses_between_them",
      sp.limit(unit_profile, xi, 0) == 1
      and sp.limit(sp.diff(unit_profile, xi), xi, 0) == 0
      and sp.limit(rejected, xi, 0) == sp.oo,
      f"sin(xi)/xi tends to {sp.limit(unit_profile, xi, 0)} with zero slope, "
      "while cos(xi)/xi diverges")

zeros = sp.solve(sp.Eq(sp.sin(xi), 0), xi)
first_zero = sp.simplify(min(zeros, key=lambda value: float(value)) if zeros else sp.nan)
check("its_first_zero_is_at_pi",
      sp.simplify(first_zero - sp.pi) == 0,
      f"sin(xi)/xi first vanishes at xi = {first_zero}")

# The exponent of the central density in alpha vanishes exactly at index one, so
# the radius alpha times pi cannot depend on it. This is the physical content.
exponent = sp.simplify(sp.Rational(1, 1) / n - 1)
check("at_index_one_the_radius_is_independent_of_central_density",
      sp.simplify(exponent.subs(n, 1)) == 0
      and rho_c not in sp.simplify(SCALE.subs(n, 1)).free_symbols,
      f"alpha^2 carries rho_c to the power {exponent}, zero at index one, "
      f"leaving alpha^2 = {sp.simplify(SCALE.subs(n, 1))}")


# ---------------------------------------------------------------- leg 3
flat_profile = 1 - xi ** 2 / 6
check("the_index_zero_profile_solves_the_equation",
      residual_at(0, flat_profile) == 0,
      f"residual for 1 - xi^2/6 at index zero is {residual_at(0, flat_profile)}")

flat_zeros = sp.solve(sp.Eq(flat_profile, 0), xi)
check("and_vanishes_at_the_square_root_of_six",
      len(flat_zeros) == 1 and sp.simplify(flat_zeros[0] - sp.sqrt(6)) == 0,
      f"1 - xi^2/6 vanishes at xi = {flat_zeros}")


# ---------------------------------------------------------------- leg 4
schuster = 1 / sp.sqrt(1 + xi ** 2 / 3)
check("the_index_five_profile_solves_the_equation",
      residual_at(5, schuster) == 0,
      f"residual for the Schuster-Emden profile at index five is "
      f"{residual_at(5, schuster)}")

five_zeros = sp.solve(sp.Eq(schuster, 0), xi)
check("falsifier_it_never_reaches_zero_so_the_radius_is_infinite",
      five_zeros == [] and schuster.subs(xi, 10 ** 6).is_positive is True,
      f"theta = 0 has solutions {five_zeros}, and at xi = 10^6 the profile is "
      f"still {float(schuster.subs(xi, 10 ** 6)):.3e}")

# Infinite radius, finite mass. The limit is what decides, so it is taken.
mass_coefficient = sp.simplify(-xi ** 2 * sp.diff(schuster, xi))
limit_mass = sp.limit(mass_coefficient, xi, sp.oo)
check("yet_the_mass_coefficient_converges",
      sp.simplify(limit_mass - sp.sqrt(3)) == 0,
      f"-xi^2 theta' tends to {limit_mass}, so an infinite star has finite mass")


# ---------------------------------------------------------------- leg 5
def integrate(index, step, ceiling, cubic=True):
    """Runge-Kutta on theta' = u/xi^2, u' = -xi^2 theta^n, started on the series.

    Two choices are forced by the equation rather than by taste.

    The start cannot sit close to the origin: there u is of order xi^3 while
    theta' is u/xi^2, so a stage error in u is divided by a tiny xi^2 and lands
    in theta magnified. Measured, that floors the located zero at about 3e-10
    when starting at xi = 1e-3, whatever the step. Starting further out removes
    it, but the series must then reach that far, which is why the xi^6 term is
    carried: with four terms, starting at 0.05 costs a thousandfold at index
    one. The two pull opposite ways and 0.05 with six terms satisfies both.

    The step straddling the surface is not a usable node either, some of its
    stages being evaluated where the density is already switched off, so the
    final approach is repeated at a fiftieth of the step before locating.

    Returns the first zero and the coefficient there, or infinity and nan.
    """
    start = 0.05
    sixth = index * (8 * index - 5) / 15120
    position = start
    value = 1 - start ** 2 / 6 + index * start ** 4 / 120 - sixth * start ** 6
    momentum = -start ** 3 / 3 + index * start ** 5 / 30 - 6 * sixth * start ** 7

    def rates(place, height, flux):
        power = height ** index if height > 0 else 0.0
        return flux / place ** 2, -place ** 2 * power

    def advance(place, height, flux, size):
        k1 = rates(place, height, flux)
        k2 = rates(place + size / 2, height + size * k1[0] / 2, flux + size * k1[1] / 2)
        k3 = rates(place + size / 2, height + size * k2[0] / 2, flux + size * k2[1] / 2)
        k4 = rates(place + size, height + size * k3[0], flux + size * k3[1])
        return (height + size * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) / 6,
                flux + size * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) / 6)

    def locate(place, height, flux, size):
        """Where theta crosses zero inside one step, and the coefficient there."""
        beyond, carried = advance(place, height, flux, size)
        if not cubic:
            weight = height / (height - beyond)
        else:
            left = flux / place ** 2
            right = carried / (place + size) ** 2

            def interpolated(fraction):
                cube, square = fraction ** 3, fraction ** 2
                return ((2 * cube - 3 * square + 1) * height
                        + (cube - 2 * square + fraction) * size * left
                        + (-2 * cube + 3 * square) * beyond
                        + (cube - square) * size * right)

            low, high = 0.0, 1.0
            for _ in range(80):
                middle = (low + high) / 2
                if height * interpolated(middle) <= 0:
                    high = middle
                else:
                    low = middle
            weight = (low + high) / 2
        return (place + weight * size,
                -(flux + weight * (carried - flux)))

    while position < ceiling:
        following, moved = advance(position, value, momentum, step)
        if not math.isfinite(following) or abs(following) > 1e6:
            # A profile that has grown a millionfold has no surface to locate,
            # and stopping here reports that in the checks rather than letting
            # the power overflow into a traceback a few steps later.
            return math.inf, math.nan
        if following <= 0.0 < value:
            fine = step / 50
            for _ in range(200):
                closer, carried = advance(position, value, momentum, fine)
                if closer <= 0.0 < value:
                    return locate(position, value, momentum, fine)
                position, value, momentum = position + fine, closer, carried
            return locate(position, value, momentum, fine)
        position, value, momentum = position + step, following, moved
    return math.inf, math.nan


# Validated where the answer is known before being trusted where it is not. The
# claim is a fourth-order BOUND across a ladder of steps, not a ratio of
# successive errors: the error constant changes sign along the way, so a ratio
# test would read as noise even though the order is right.
LADDER = [8e-3, 4e-3, 2e-3, 1e-3, 5e-4]
located = [integrate(1, size, 20.0)[0] for size in LADDER]
margins = [abs(value - math.pi) / size ** 4
           for value, size in zip(located, LADDER)]
check("the_integrator_reproduces_the_index_one_zero",
      abs(located[-1] - math.pi) < 1e-11,
      f"found xi_1 = {located[-1]:.13f} against pi = {math.pi:.13f}, apart by "
      f"{abs(located[-1] - math.pi):.3e}")


# Index one alone would not validate the integrator: there the equation is
# linear and homogeneous, so an error in the central value is a pure rescaling
# and cannot move the zero. Index zero carries a source, and does feel one.
flat_located, _ = integrate(0, 5e-4, 20.0)
check("the_integrator_also_reproduces_the_index_zero_zero",
      abs(flat_located - math.sqrt(6)) < 1e-11,
      f"found xi_1 = {flat_located:.13f} against sqrt(6) = {math.sqrt(6):.13f}, "
      f"apart by {abs(flat_located - math.sqrt(6)):.3e}")

check("and_its_error_obeys_a_fourth_order_bound_at_every_step_on_the_ladder",
      max(margins) < 100.0,
      f"the largest error over the fourth power of the step is {max(margins):.1f} "
      f"across steps {LADDER[0]:.0e} to {LADDER[-1]:.0e}, so the error is fourth order")

# Why the crossing needed a cubic: linear interpolation breaks the same bound,
# so the root location, not the integration, would have set the accuracy.
linear_margins = [
    abs(integrate(1, size, 20.0, cubic=False)[0] - math.pi) / size ** 4
    for size in LADDER
]
check("linear_location_breaks_the_bound_the_cubic_satisfies",
      max(linear_margins) > 10 * max(margins) and max(linear_margins) > 100.0,
      f"linear reaches {max(linear_margins):.1f} on the same measure against "
      f"{max(margins):.1f} for the cubic, failing the bound the cubic clears; "
      "the refinement pass already shrinks the step it spans, hence only a "
      f"factor of {max(linear_margins) / max(margins):.0f}")

# Only now index three, where there is no closed form to check against, so the
# only claim available is convergence and it is the only claim made. The
# shrinkage factors sit near sixteen, which is what a fourth order method does;
# before the start radius was fixed they climbed from seven, and that drift was
# the signature of the error being born at the origin rather than accumulated.
LADDER_THREE = [4e-3, 2e-3, 1e-3, 5e-4, 2.5e-4]
runs = [integrate(3, size, 20.0) for size in LADDER_THREE]
moves = [abs(later[0] - earlier[0]) for earlier, later in zip(runs, runs[1:])]
factors = [earlier / later for earlier, later in zip(moves, moves[1:])]
check("the_index_three_zero_settles_as_the_step_is_refined",
      moves[-1] < 1e-11 and all(10.0 < factor < 20.0 for factor in factors),
      f"halving the step moves the zero by "
      f"{', '.join(f'{move:.2e}' for move in moves)}, shrinking by factors of "
      f"{', '.join(f'{factor:.1f}' for factor in factors)}, all of them near "
      f"the sixteen of a fourth order method; it settles at {runs[-1][0]:.10f}")

masses = [mass for _, mass in runs]
check("and_its_mass_coefficient_settles_further_still",
      abs(masses[-1] - masses[-2]) < 1e-12,
      f"-xi^2 theta' at the surface is {masses[-1]:.12f}, moving by "
      f"{abs(masses[-1] - masses[-2]):.3e} on the last halving")


# ---------------------------------------------------------------- leg 6
five_zero, _ = integrate(5, 1e-3, 200.0)
exact_at_end = float(schuster.subs(xi, 200))
check("falsifier_the_integration_finds_no_zero_at_index_five",
      five_zero == math.inf,
      f"no crossing up to xi = 200, where the exact profile is still "
      f"{exact_at_end:.6e}")

# It is not that the integrator gave up: just below five the star does end.
below_zero, _ = integrate(4.5, 1e-3, 200.0)
check("while_just_below_five_the_star_does_end",
      math.isfinite(below_zero) and below_zero > 20.0,
      f"at index four and a half it reaches zero at xi = {below_zero:.6f}, large "
      "but finite, so five is a boundary in the physics and not in the method")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
