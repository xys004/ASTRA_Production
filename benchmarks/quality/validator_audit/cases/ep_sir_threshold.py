"""An SIR epidemic grows only above threshold, and its peak sits at a fixed S.

CLAIM: for S' = -b S I / N, I' = b S I / N - g I, R' = g I, the population is
conserved; the infected count grows at time zero exactly when b S(0) / (g N) > 1;
the peak of I occurs precisely when S = g N / b; and the final susceptible
fraction solves s = exp(-R0 (1 - s)), which has a root strictly inside (0, 1)
whenever R0 > 1.

Each analytic statement is paired with a numeric integration of the same system,
so the two must agree and a disagreement would localise the error here.

Legs:
  1. conservation -- the total derivative of S + I + R vanishes identically;
  2. threshold    -- the sign of I'(0) is solved for, giving the condition on
                     R0 rather than asserting it;
  3. peak         -- I' = 0 is solved for S, and the answer is g N / b;
  4. final size   -- the transcendental equation is derived from dS/dR and its
                     root bracketed, with the sub-threshold case shown to have
                     no interior root;
  5. numeric      -- integrating the system confirms growth above threshold,
                     decay below it, and the peak location;
  6. falsifier    -- below threshold the infected count never rises, which the
                     same integration detects.
"""
import math

import sympy as sp

t = sp.Symbol("t", nonnegative=True)
b, g, N = sp.symbols("b g N", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


S = sp.Function("S", positive=True)(t)
I = sp.Function("I", positive=True)(t)
R = sp.Function("R", nonnegative=True)(t)

dS = -b * S * I / N
dI = b * S * I / N - g * I
dR = g * I


# ---------------------------------------------------------------- leg 1
# Differentiate the actual total and substitute the system, rather than adding
# the three right-hand sides. The two agree here, but only the first form is a
# statement about S + I + R; the second never mentions the total at all.
total = S + I + R
total_rate = sp.simplify(
    sp.diff(total, t).subs({
        sp.Derivative(S, t): dS,
        sp.Derivative(I, t): dI,
        sp.Derivative(R, t): dR,
    })
)
check("population_is_conserved", total_rate == 0,
      f"d(S + I + R)/dt = {total_rate} after substituting the system")


# ---------------------------------------------------------------- leg 2
# Growth at time zero. Solve the inequality rather than reading it off.
S0, I0 = sp.symbols("S_0 I_0", positive=True)
growth_rate = sp.simplify(dI.subs({S: S0, I: I0}))
factored = sp.factor(growth_rate)
check("initial_growth_rate_factors_through_the_threshold",
      sp.simplify(factored - I0 * (b * S0 / N - g)) == 0,
      f"I'(0) = {factored}")

condition = sp.solve(sp.Eq(b * S0 / N - g, 0), S0)
check("growth_changes_sign_at_S_equals_gN_over_b",
      len(condition) == 1 and sp.simplify(condition[0] - g * N / b) == 0,
      f"I'(0) = 0 at S_0 = {condition[0] if condition else 'none'}")

# In terms of R0 = b/g the condition is R0 S0/N > 1, which is the standard form.
R0 = sp.Symbol("R_0", positive=True)
restated = sp.simplify((b * S0 / N - g).subs(b, R0 * g) / g)
check("threshold_in_terms_of_R0_is_R0_S0_over_N_greater_than_one",
      sp.simplify(restated - (R0 * S0 / N - 1)) == 0,
      f"I'(0) > 0 iff {restated} > 0")


# ---------------------------------------------------------------- leg 3
peak = sp.solve(sp.Eq(dI, 0), S)
non_trivial = [value for value in peak if sp.simplify(value) != 0]
check("peak_condition_solves_to_a_single_susceptible_level",
      len(non_trivial) == 1,
      f"I' = 0 at S = {non_trivial}")
check("peak_is_at_S_equals_gN_over_b",
      sp.simplify(non_trivial[0] - g * N / b) == 0,
      f"S_peak = {sp.simplify(non_trivial[0])}")


# ---------------------------------------------------------------- leg 4
# dS/dR = -b S / (g N), so S = S0 exp(-R0 R / N) and the final size follows.
s_sym, r0_sym = sp.symbols("s R_zero", positive=True)
dS_dR = sp.simplify(dS / dR)
check("dS_over_dR_is_minus_R0_S_over_N",
      sp.simplify(dS_dR + (b / g) * S / N) == 0,
      f"dS/dR = {dS_dR}")

# The residual solved numerically below is generated FROM this symbolic
# equation, so the two cannot drift apart: editing the equation changes what is
# bracketed, and a stray symbolic statement nobody uses cannot survive here.
final_size = sp.Eq(s_sym, sp.exp(-r0_sym * (1 - s_sym)))
residual_expr = sp.simplify(final_size.lhs - final_size.rhs)
residual_fn = sp.lambdify((s_sym, r0_sym), residual_expr, "math")

check("final_size_residual_is_generated_from_the_equation",
      abs(residual_fn(1.0, 2.5)) < 1e-15,
      f"s = 1 is the trivial root of {final_size}, residual "
      f"{residual_fn(1.0, 2.5):.3e}")


def final_fraction(r0_value):
    """Solve s = exp(-R0 (1 - s)) numerically, excluding the trivial root s = 1."""
    lower, upper = 1e-12, 1 - 1e-12

    def residual(value):
        return residual_fn(value, r0_value)

    if residual(lower) * residual(upper) > 0:
        return None
    for _ in range(200):
        middle = (lower + upper) / 2
        if residual(lower) * residual(middle) <= 0:
            upper = middle
        else:
            lower = middle
    return (lower + upper) / 2


def brackets_a_root(r0_value):
    """Does the residual change sign strictly inside (0, 1)?

    Stated as a sign change rather than as a null return, because the existence
    of an interior root IS a sign change; testing a sentinel for None would say
    something about the solver's return convention instead.
    """
    return residual_fn(1e-12, r0_value) * residual_fn(1 - 1e-12, r0_value) < 0


check("above_threshold_the_residual_changes_sign_inside_the_unit_interval",
      brackets_a_root(2.5),
      f"at R0 = 2.5 the residual runs from {residual_fn(1e-12, 2.5):.6f} to "
      f"{residual_fn(1 - 1e-12, 2.5):.3e}")

above = final_fraction(2.5)
check("above_threshold_the_final_size_equation_has_an_interior_root",
      0 < above < 1,
      f"R0 = 2.5 gives s_inf = {above:.9f}")

check("below_threshold_the_residual_keeps_one_sign",
      not brackets_a_root(0.8),
      f"at R0 = 0.8 the residual runs from {residual_fn(1e-12, 0.8):.6f} to "
      f"{residual_fn(1 - 1e-12, 0.8):.3e}, never crossing, so only s = 1 solves it")


# ---------------------------------------------------------------- leg 5
def integrate(beta, gamma, population, infected0, steps, dt):
    """Fourth-order Runge-Kutta on the same system, independent of the algebra."""
    s_value = population - infected0
    i_value = infected0
    peak_i = i_value
    peak_s = s_value

    def derivatives(sv, iv):
        return (-beta * sv * iv / population,
                beta * sv * iv / population - gamma * iv)

    for _ in range(steps):
        k1s, k1i = derivatives(s_value, i_value)
        k2s, k2i = derivatives(s_value + 0.5 * dt * k1s, i_value + 0.5 * dt * k1i)
        k3s, k3i = derivatives(s_value + 0.5 * dt * k2s, i_value + 0.5 * dt * k2i)
        k4s, k4i = derivatives(s_value + dt * k3s, i_value + dt * k3i)
        s_value += dt * (k1s + 2 * k2s + 2 * k3s + k4s) / 6
        i_value += dt * (k1i + 2 * k2i + 2 * k3i + k4i) / 6
        if i_value > peak_i:
            peak_i = i_value
            peak_s = s_value
    return s_value, i_value, peak_i, peak_s


POP, I_START, GAMMA = 1_000_000.0, 10.0, 0.2
beta_above = 2.5 * GAMMA
final_s, _final_i, peak_i, peak_s = integrate(
    beta_above, GAMMA, POP, I_START, 200000, 0.005
)

check("above_threshold_an_epidemic_occurs",
      peak_i > 100 * I_START,
      f"peak infected {peak_i:,.0f} against {I_START:,.0f} at the start")

predicted_peak_s = GAMMA * POP / beta_above
check("peak_occurs_at_the_predicted_susceptible_level",
      abs(peak_s - predicted_peak_s) / predicted_peak_s < 1e-3,
      f"peak at S = {peak_s:,.1f}, predicted g N / b = {predicted_peak_s:,.1f}")

check("integration_matches_the_final_size_equation",
      abs(final_s / POP - above) < 1e-4,
      f"integrated s_inf = {final_s / POP:.9f}, equation gives {above:.9f}")


# ---------------------------------------------------------------- leg 6
beta_below = 0.8 * GAMMA
_s_low, _i_low, peak_low, _ps_low = integrate(
    beta_below, GAMMA, POP, I_START, 200000, 0.005
)
check("falsifier_below_threshold_the_infected_count_never_rises",
      peak_low <= I_START * (1 + 1e-9),
      f"peak infected {peak_low:.6f} never exceeds the initial {I_START:.1f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
