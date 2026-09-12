"""Kepler orbits close, and closure belongs to the inverse square alone.

CLAIM: for a particle in the potential -GM/r the angle is cyclic, so r^2 thetadot
is conserved; in u = 1/r the radial equation becomes u'' + u = GM/h^2; its
bounded solutions are conics whose semi-latus rectum is forced to be h^2/GM;
the period follows from the swept-area rate and gives T^2 = 4 pi^2 a^3 / GM; and
adding a 1/r^3 term to the force changes the apsidal angle to 2 pi / sqrt(1 -
beta/h^2), so the orbit stops closing.

The last leg is the point of the case. Closure is easy to mistake for a property
of "gravity" or of the integrator, so the perturbed force is carried through the
same derivation, which predicts a specific precession, and through the same
integrator, which has to measure it.

Legs:
  1. cyclic    -- theta is absent from the Lagrangian and the conjugate momentum
                  is r^2 thetadot, both read off the Lagrangian itself;
  2. orbit     -- the conservation law is used as the operator d/dt = h u^2 d/dtheta,
                  and the radial equation becomes a linear oscillator equation;
  3. conic     -- the semi-latus rectum is SOLVED for and comes out h^2/GM, while
                  the eccentricity stays free, which is what makes it a family;
  4. period    -- Kepler's third law is derived from the areal rate and the area
                  of the ellipse;
  5. numeric   -- Runge-Kutta on the Cartesian equations returns to periapsis at
                  the predicted time and after a full turn;
  6. falsifier -- with a 1/r^3 term the derivation predicts a precession of
                  2 pi / sqrt(1 - beta/h^2) - 2 pi, and the same integrator
                  measures it, so closure is a property of the force law.
"""
import math

import sympy as sp

t = sp.Symbol("t", positive=True)
theta = sp.Symbol("theta", real=True)
GM, h, beta = sp.symbols("GM h beta", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
r_t = sp.Function("r", positive=True)(t)
theta_t = sp.Function("vartheta")(t)
lagrangian = (sp.diff(r_t, t) ** 2 + r_t ** 2 * sp.diff(theta_t, t) ** 2) / 2 + GM / r_t

angular_gradient = sp.simplify(sp.diff(lagrangian, theta_t))
check("the_angle_is_cyclic", angular_gradient == 0,
      f"dL/dtheta = {angular_gradient}, so the angle appears only through its rate")

conjugate = sp.simplify(sp.diff(lagrangian, sp.diff(theta_t, t)))
check("the_conjugate_momentum_is_r_squared_thetadot",
      sp.simplify(conjugate - r_t ** 2 * sp.diff(theta_t, t)) == 0,
      f"p_theta = {conjugate}")

# The radial Euler-Lagrange equation, likewise derived rather than written down.
radial_el = sp.simplify(
    sp.diff(sp.diff(lagrangian, sp.diff(r_t, t)), t) - sp.diff(lagrangian, r_t)
)
check("the_radial_equation_is_the_usual_one",
      sp.simplify(radial_el
                  - (sp.diff(r_t, t, 2) - r_t * sp.diff(theta_t, t) ** 2 + GM / r_t ** 2)) == 0,
      f"rddot - r thetadot^2 + GM/r^2 = 0, obtained as {sp.simplify(radial_el)}")


# ---------------------------------------------------------------- leg 2
# The conservation law is not restated here; it is USED, as the operator that
# converts a time derivative into a derivative with respect to the angle. Every
# statement below therefore depends on leg 1 having held.
u = sp.Function("u", positive=True)(theta)


def along_the_orbit(expression):
    """d/dt = (h u^2) d/dtheta, which is r^2 thetadot = h rewritten."""
    return h * u ** 2 * sp.diff(expression, theta)


radius = 1 / u
radial_speed = sp.simplify(along_the_orbit(radius))
check("the_radial_speed_is_minus_h_times_u_prime",
      sp.simplify(radial_speed + h * sp.diff(u, theta)) == 0,
      f"rdot = {radial_speed}")

radial_acceleration = sp.simplify(along_the_orbit(radial_speed))
angular_speed = h * u ** 2

# The equation transformed here is the one leg 1 DERIVED, not a retyped
# copy of it. Substituting the three atoms is what carries the Lagrangian
# into this leg, so a wrong potential upstream shows up as a wrong orbit
# equation here instead of being quietly re-entered correctly.
radial_law = sp.simplify(radial_el)
residual = sp.simplify(radial_law.subs([
    (sp.Derivative(r_t, t, 2), radial_acceleration),
    (sp.Derivative(theta_t, t), angular_speed),
    (r_t, radius),
]))
orbit_equation = sp.simplify(-residual / (h ** 2 * u ** 2))
check("the_substitution_gives_a_linear_oscillator_equation",
      sp.simplify(orbit_equation - (sp.diff(u, theta, 2) + u - GM / h ** 2)) == 0,
      f"u'' + u - GM/h^2 = 0, obtained as {orbit_equation}")


# ---------------------------------------------------------------- leg 3
# Do not assert the semi-latus rectum: impose the conic and solve for it. If the
# equation were different the solve would return a different value or none.
e = sp.Symbol("e", nonnegative=True)
p_sym = sp.Symbol("p", positive=True)
trial = (1 + e * sp.cos(theta)) / p_sym
trial_residual = sp.simplify(sp.diff(trial, theta, 2) + trial - GM / h ** 2)
required = sp.solve(sp.Eq(trial_residual, 0), p_sym)
check("the_conic_forces_one_semi_latus_rectum",
      len(required) == 1,
      f"the conic solves the equation only for p = {required or 'nothing'}")

# Summed rather than indexed: with the single solution the uniqueness check just
# made, the sum IS that solution, and with no solution the value is nan, which
# fails the comparison below instead of raising an IndexError. The alternative,
# testing the list against None, would be a statement about the solver.
solved_p = sp.simplify(sum(required)) if required else sp.nan
check("that_semi_latus_rectum_is_h_squared_over_GM",
      sp.simplify(solved_p - h ** 2 / GM) == 0,
      f"p = {solved_p}")

# The eccentricity, by contrast, is an integration constant: with p fixed the
# residual vanishes for symbolic e, so a whole family solves the same equation.
family_residual = sp.simplify(trial_residual.subs(p_sym, h ** 2 / GM))
check("the_eccentricity_stays_free",
      family_residual == 0,
      f"residual for arbitrary e is {family_residual}")


# ---------------------------------------------------------------- leg 4
semi_latus = h ** 2 / GM
semi_major = sp.simplify(semi_latus / (1 - e ** 2))
semi_minor = sp.simplify(semi_major * sp.sqrt(1 - e ** 2))

areal_rate = sp.simplify(radius ** 2 * angular_speed / 2)
check("the_areal_rate_is_half_the_angular_momentum",
      sp.simplify(areal_rate - h / 2) == 0,
      f"dA/dt = {areal_rate}, constant, which is the second law")

period = sp.simplify(sp.pi * semi_major * semi_minor / areal_rate)
check("the_period_squared_is_four_pi_squared_a_cubed_over_GM",
      sp.simplify(period ** 2 - 4 * sp.pi ** 2 * semi_major ** 3 / GM) == 0,
      f"T = {period}")


# ---------------------------------------------------------------- leg 5
GM_NUM = 1.0
E_NUM = 0.6
A_NUM = 1.0
P_NUM = A_NUM * (1 - E_NUM ** 2)
H_NUM = math.sqrt(GM_NUM * P_NUM)
R_PERI = A_NUM * (1 - E_NUM)
V_PERI = H_NUM / R_PERI
DT = 5e-5


def integrate(beta_value, steps):
    """Runge-Kutta on xddot = -(GM/r^3 + beta/r^4) x, started at periapsis.

    Returns the time and the polar angle of the next periapsis, found by
    interpolating the crossing of rdot back through zero.
    """
    state = [R_PERI, 0.0, 0.0, V_PERI]

    def derivatives(s):
        x, y, vx, vy = s
        radius_now = math.hypot(x, y)
        pull = GM_NUM / radius_now ** 3 + beta_value / radius_now ** 4
        return [vx, vy, -pull * x, -pull * y]

    def radial_rate(s):
        return s[0] * s[2] + s[1] * s[3]

    def step(s):
        k1 = derivatives(s)
        k2 = derivatives([a + 0.5 * DT * b for a, b in zip(s, k1)])
        k3 = derivatives([a + 0.5 * DT * b for a, b in zip(s, k2)])
        k4 = derivatives([a + DT * b for a, b in zip(s, k3)])
        return [a + DT * (b + 2 * c + 2 * d + f) / 6
                for a, b, c, d, f in zip(s, k1, k2, k3, k4)]

    # The crossing sought is inbound to outbound. It cannot fire at the start,
    # where the rate is exactly zero rather than negative, so no separate flag
    # for "has been through apoapsis" is needed and none is kept.
    time_now = 0.0
    previous_rate = radial_rate(state)
    for _ in range(steps):
        following = step(state)
        rate_now = radial_rate(following)
        if previous_rate < 0.0 <= rate_now:
            # Linear interpolation in the radial rate across the last step.
            weight = -previous_rate / (rate_now - previous_rate)
            hit = [a + weight * (b - a) for a, b in zip(state, following)]
            angle = math.atan2(hit[1], hit[0]) % (2 * math.pi)
            return time_now + weight * DT, angle
        state, previous_rate = following, rate_now
        time_now += DT
    # No crossing inside the window. Returning infinity and a nan makes the
    # checks below fail on their own terms rather than raising later.
    return math.inf, math.nan


predicted_period = 2 * math.pi * A_NUM ** 1.5 / math.sqrt(GM_NUM)
ONE_TURN_STEPS = int(1.2 * predicted_period / DT)
window = ONE_TURN_STEPS * DT
measured_period, measured_angle = integrate(0.0, ONE_TURN_STEPS)
check("the_integration_locates_a_periapsis_inside_the_window",
      measured_period < window,
      f"periapsis recovered at t = {measured_period:.9f} inside a window of "
      f"{window:.6f}")
check("the_measured_period_matches_keplers_third_law",
      abs(measured_period - predicted_period) / predicted_period < 1e-6,
      f"measured {measured_period:.9f} against 2 pi a^(3/2)/sqrt(GM) = "
      f"{predicted_period:.9f}, relative gap "
      f"{abs(measured_period - predicted_period) / predicted_period:.3e}")

# Closure: the second periapsis sits at the same angle as the first.
closure_gap = min(measured_angle, 2 * math.pi - measured_angle)
check("the_orbit_closes_on_itself",
      closure_gap < 1e-6,
      f"the second periapsis is {closure_gap:.3e} rad from the first, so the "
      "apsidal angle is a full turn")


# ---------------------------------------------------------------- leg 6
# Carry the extra force through the SAME derivation. The orbit equation stays
# linear, so the apsidal angle is exact and the prediction is sharp.
perturbed_residual = sp.simplify(residual + beta / radius ** 3)
perturbed_equation = sp.simplify(-perturbed_residual / (h ** 2 * u ** 2))
omega_squared = sp.Symbol("omega_squared", positive=True)
difference = sp.expand(
    perturbed_equation - (sp.diff(u, theta, 2) + omega_squared * u - GM / h ** 2)
)
frequencies = sp.solve(sp.Eq(difference, 0), omega_squared)
# Summed rather than indexed, for the reason given in leg 3: if the perturbed
# equation were not linear in u there would be no constant frequency to find,
# and the remaining checks should report that rather than raise.
solved_frequency = sp.simplify(sum(frequencies)) if frequencies else sp.nan
check("the_perturbed_orbit_equation_is_still_linear_with_a_shifted_frequency",
      len(frequencies) == 1
      and sp.simplify(solved_frequency - (1 - beta / h ** 2)) == 0,
      f"u'' + ({solved_frequency}) u = GM/h^2")

apsidal = sp.simplify(2 * sp.pi / sp.sqrt(solved_frequency))
BETA_NUM = 0.1 * H_NUM ** 2
evaluated = sp.N(apsidal.subs({beta: BETA_NUM, h: H_NUM}))
predicted_angle = (float(evaluated)
                   if evaluated.is_number and evaluated.is_real else math.nan)
check("the_prediction_is_a_precession_not_a_closed_orbit",
      abs(predicted_angle - 2 * math.pi) > 0.3,
      f"apsidal angle 2 pi / sqrt(1 - beta/h^2) = {predicted_angle:.9f} rad "
      f"against {2 * math.pi:.9f} for a closed orbit")

_perturbed_time, perturbed_angle = integrate(BETA_NUM, int(2.0 * predicted_period / DT))
swept = perturbed_angle % (2 * math.pi)
check("falsifier_the_same_integrator_measures_the_predicted_precession",
      abs(swept - (predicted_angle - 2 * math.pi)) < 1e-5,
      f"the second periapsis lands {swept:.9f} rad past the first, and the "
      f"derivation asked for {predicted_angle - 2 * math.pi:.9f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
