"""A daughter reaches equilibrium with its parent only if it is shorter lived.

CLAIM: for A decaying to B decaying away, the Bateman solution follows from the
pair of rate equations and is verified by substitution; the daughter activity
peaks where the two exponentials cross, at a time solved for rather than quoted;
when the daughter is much shorter lived the activities equalise, and when it is
merely shorter lived they settle at a fixed ratio above one; and when the
daughter is the LONGER lived of the two there is no equilibrium at all, the ratio
growing without bound because the parent disappears first.

"Secular equilibrium" is taught as what a decay chain does. It is what a decay
chain does under a condition on the two half-lives, and the condition is the part
that gets dropped.

Legs:
  1. bateman   -- the rate equations are solved and the solution substituted
                  back, so the closed form is earned;
  2. peak      -- the daughter's maximum is solved for and matched numerically;
  3. secular   -- the ratio tends to one as the daughter becomes fast;
  4. transient -- for a merely faster daughter it tends to a constant above one,
                  obtained as a limit;
  5. falsifier -- for a slower daughter the same limit diverges, so there is no
                  equilibrium to reach;
  6. numeric   -- integrating the pair reproduces all three regimes.
"""
import math

import sympy as sp

time = sp.Symbol("t", positive=True)
lam_a, lam_b = sp.symbols("lambda_A lambda_B", positive=True)
start = sp.Symbol("N_0", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
parent = start * sp.exp(-lam_a * time)
daughter_function = sp.Function("N_B")(time)
equation = sp.Eq(sp.diff(daughter_function, time),
                 lam_a * parent - lam_b * daughter_function)
solution = sp.dsolve(equation, daughter_function,
                     ics={daughter_function.subs(time, 0): 0})
daughter = sp.simplify(solution.rhs)

check("the_parent_obeys_its_own_rate_equation",
      sp.simplify(sp.diff(parent, time) + lam_a * parent) == 0,
      f"dN_A/dt + lambda_A N_A = "
      f"{sp.simplify(sp.diff(parent, time) + lam_a * parent)}")

residual = sp.simplify(
    sp.diff(daughter, time) - (lam_a * parent - lam_b * daughter)
)
check("and_the_solved_daughter_satisfies_hers",
      residual == 0,
      f"substituting the solution back leaves {residual}, and it starts from "
      f"{sp.simplify(sp.limit(daughter, time, 0))}")

closed = sp.simplify(
    daughter - start * lam_a / (lam_b - lam_a)
    * (sp.exp(-lam_a * time) - sp.exp(-lam_b * time))
)
check("the_solution_is_the_bateman_form",
      closed == 0,
      "the difference from the textbook expression is zero, so the solver and "
      "the closed form agree rather than one being assumed")


# ---------------------------------------------------------------- leg 2
peak_times = sp.solve(sp.Eq(sp.diff(daughter, time), 0), time)
check("the_daughter_peaks_at_one_time",
      len(peak_times) == 1,
      f"dN_B/dt vanishes at {peak_times}")

# Summed rather than indexed: with the uniqueness just checked the sum is
# that one root, and with no root at all the value is nan, which fails the
# comparison below instead of raising.
peak = sp.simplify(sum(peak_times)) if peak_times else sp.nan
check("and_that_time_is_the_log_ratio_over_the_difference",
      sp.simplify(peak - sp.log(lam_b / lam_a) / (lam_b - lam_a)) == 0,
      f"t_max = {peak}, which is symmetric in the two constants and positive "
      "whichever is the larger")


# ---------------------------------------------------------------- leg 3
# Activity is the decay constant times the number, so the ratio is what a
# detector compares. The long-time limit is taken with the faster exponential
# already gone.
ratio = sp.simplify(lam_b * daughter / (lam_a * parent))
late = sp.simplify(sp.limit(ratio, time, sp.oo))
check("the_late_activity_ratio_is_a_constant_when_the_daughter_is_faster",
      sp.simplify(late.subs({lam_a: 1, lam_b: 3}) - sp.Rational(3, 2)) == 0,
      f"the ratio tends to {late} as time grows, which at lambda_B three times "
      f"lambda_A is {late.subs({lam_a: 1, lam_b: 3})}")

secular = sp.limit(late.subs(lam_a, lam_b / sp.Symbol("R", positive=True)),
                   sp.Symbol("R", positive=True), sp.oo)
check("and_it_approaches_one_as_the_daughter_becomes_much_faster",
      sp.simplify(secular - 1) == 0,
      f"letting the ratio of constants run away gives {secular}, which is "
      "secular equilibrium and is a limit rather than a definition")


# ---------------------------------------------------------------- leg 4
check("for_a_merely_faster_daughter_the_constant_exceeds_one",
      bool(late.subs({lam_a: 1, lam_b: sp.Rational(3, 2)}) > 1)
      and sp.simplify(late - lam_b / (lam_b - lam_a)) == 0,
      f"the constant is {sp.simplify(late)}, which is "
      f"{late.subs({lam_a: 1, lam_b: sp.Rational(3, 2)})} when the daughter is "
      "only half again as fast, so transient equilibrium sits above one and not at it")


# ---------------------------------------------------------------- leg 5
# With the daughter slower, the parent's exponential dies first and the ratio no
# longer settles. Taken as a limit at fixed constants rather than by inspection.
slow_ratio = sp.simplify(ratio.subs({lam_a: 3, lam_b: 1}))
runaway = sp.limit(slow_ratio, time, sp.oo)
check("falsifier_a_slower_daughter_never_reaches_equilibrium",
      runaway == sp.oo,
      f"with the daughter three times slower the ratio tends to {runaway}, so "
      "there is no constant to settle at and the word equilibrium does not apply")

# Divided by the exponential of the DIFFERENCE of the two constants. A limit of
# zero would mean it grows more slowly than that and an infinite one that it
# grows faster; what says "at exactly this rate" is a finite nonzero constant.
rate_constant = sp.simplify(sp.limit(slow_ratio / sp.exp(2 * time), time, sp.oo))
expected_constant = sp.simplify((lam_b / (lam_a - lam_b)).subs({lam_a: 3, lam_b: 1}))
check("because_the_late_behaviour_is_governed_by_the_survivor",
      rate_constant.is_finite is True and rate_constant != 0
      and sp.simplify(rate_constant - expected_constant) == 0,
      f"dividing by that exponential leaves {rate_constant}, finite and not "
      f"zero and equal to lambda_B over their difference, {expected_constant}, "
      "so the ratio grows at exactly the rate the two constants set: the parent "
      "vanishing out from under the daughter")


# ---------------------------------------------------------------- leg 6
def integrate(rate_parent, rate_daughter, span, step=1e-4):
    """Runge-Kutta on the pair, returning the activity ratio at the end."""
    amount_a, amount_b = 1.0, 0.0

    def rates(a_value, b_value):
        return -rate_parent * a_value, rate_parent * a_value - rate_daughter * b_value

    steps = int(span / step)
    for _ in range(steps):
        k1 = rates(amount_a, amount_b)
        k2 = rates(amount_a + step * k1[0] / 2, amount_b + step * k1[1] / 2)
        k3 = rates(amount_a + step * k2[0] / 2, amount_b + step * k2[1] / 2)
        k4 = rates(amount_a + step * k3[0], amount_b + step * k3[1])
        amount_a += step * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) / 6
        amount_b += step * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) / 6
    return rate_daughter * amount_b / (rate_parent * amount_a)


secular_measured = integrate(0.01, 5.0, 6.0)
check("integration_reproduces_secular_equilibrium",
      abs(secular_measured - 1.0) < 0.01,
      f"with the daughter five hundred times faster the measured ratio is "
      f"{secular_measured:.6f} against the limit of one")

transient_measured = integrate(1.0, 3.0, 8.0)
check("and_the_transient_constant",
      abs(transient_measured - 1.5) < 1e-3,
      f"at three against one the measured ratio is {transient_measured:.6f} "
      f"against the predicted {float(late.subs({lam_a: 1, lam_b: 3})):.6f}")

near = integrate(3.0, 1.0, 4.0)
far = integrate(3.0, 1.0, 8.0)
check("falsifier_while_the_slow_daughter_ratio_keeps_climbing",
      far > 10 * near and far > 100,
      f"the ratio reads {near:.2f} at four lifetimes and {far:.2f} at eight, "
      "still rising, so nothing is being approached")

predicted_growth = math.exp(2 * (8.0 - 4.0))
check("and_it_climbs_at_the_rate_the_exponents_predict",
      abs(far / near / predicted_growth - 1) < 0.05,
      f"the ratio grows by {far / near:.1f} over those four lifetimes against "
      f"the {predicted_growth:.1f} that the difference of the two constants "
      "asks for, so the divergence is the one the algebra describes")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
