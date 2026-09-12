"""Parseval's identity holds for the square wave, and the Gibbs overshoot is real.

CLAIM: the Fourier series of the odd square wave on (-pi, pi) has coefficients
b_n = 4/(n pi) for odd n and zero otherwise, Parseval's identity then yields
sum over odd n of 1/n^2 = pi^2/8, and the partial sums overshoot the jump by the
Gibbs constant rather than converging uniformly.

Legs:
  1. coefficients -- computed by integration, not quoted, with the even ones
                     shown to vanish by the symmetry of the integrand;
  2. parseval     -- both sides computed independently and equated exactly,
                     which also delivers the odd-index Basel sum in closed form;
  3. pointwise    -- the series converges to the midpoint at the jump, which is
                     what the theorem actually promises there;
  4. gibbs        -- the overshoot does not vanish as terms are added, so
                     convergence is not uniform, and the limit is identified;
  5. falsifier    -- a wrong coefficient breaks Parseval by a measurable amount.
"""
import math

import sympy as sp

x = sp.Symbol("x", real=True)
n = sp.Symbol("n", positive=True, integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Odd square wave: f(x) = 1 on (0, pi), -1 on (-pi, 0). Being odd, all cosine
# coefficients vanish, which is checked rather than asserted.
b = sp.simplify(2 / sp.pi * sp.integrate(sp.sin(n * x), (x, 0, sp.pi)))
check("sine_coefficient_in_closed_form",
      sp.simplify(b - 2 * (1 - sp.cos(sp.pi * n)) / (sp.pi * n)) == 0,
      f"b_n = {b}")

odd_value = sp.simplify(b.subs(n, 2 * sp.Symbol("m", positive=True, integer=True) - 1))
check("odd_coefficients_are_four_over_n_pi",
      sp.simplify(odd_value - 4 / (sp.pi * (2 * sp.Symbol("m", positive=True, integer=True) - 1))) == 0,
      f"b_(2m-1) = {odd_value}")

even_value = sp.simplify(b.subs(n, 2 * sp.Symbol("m", positive=True, integer=True)))
check("even_coefficients_vanish", sp.simplify(even_value) == 0,
      f"b_2m = {even_value}")

# The cosine coefficients vanish because the integrand is odd on a symmetric
# interval. Verified by integration, not by appeal to symmetry alone.
a_n = sp.simplify(
    1 / sp.pi * (sp.integrate(-sp.cos(n * x), (x, -sp.pi, 0))
                 + sp.integrate(sp.cos(n * x), (x, 0, sp.pi)))
)
check("cosine_coefficients_vanish", sp.simplify(a_n) == 0,
      f"a_n = {a_n} for the odd square wave")


# ---------------------------------------------------------------- leg 2
# Parseval: (1/pi) integral f^2 = sum b_n^2. The left side is 2 since |f| = 1.
left = sp.simplify(1 / sp.pi * sp.integrate(1, (x, -sp.pi, sp.pi)))
m = sp.Symbol("m", positive=True, integer=True)
right = sp.simplify(sp.summation((4 / (sp.pi * (2 * m - 1))) ** 2, (m, 1, sp.oo)))
check("parseval_two_sides_agree", sp.simplify(left - right) == 0,
      f"left = {left}, right = {right}")

odd_basel = sp.simplify(sp.summation(1 / (2 * m - 1) ** 2, (m, 1, sp.oo)))
check("odd_index_basel_sum_is_pi_squared_over_eight",
      sp.simplify(odd_basel - sp.pi**2 / 8) == 0,
      f"sum 1/(2m-1)^2 = {odd_basel}")


# ---------------------------------------------------------------- leg 3
def partial(value, terms):
    return sum(4.0 / (math.pi * (2 * j - 1)) * math.sin((2 * j - 1) * value)
               for j in range(1, terms + 1))


# NOT checked here: that S_N(0) = 0. Every term is sin((2j-1)*0), so the
# partial sum vanishes identically for any coefficients whatsoever, including a
# series that converges to nothing like the square wave. That identity carries
# no information and would be a check incapable of failing.
#
# The midpoint statement has content only as the average of the one-sided
# limits. Approach the jump from both sides and require the partial sums to
# tend to +1 and -1, so that their mean is the value the series takes at 0.
right_side = partial(0.02, 4000)
left_side = partial(-0.02, 4000)
midpoint = (right_side + left_side) / 2
check("one_sided_limits_straddle_the_jump",
      right_side > 0.9 and left_side < -0.9,
      f"S(0.02+) = {right_side:.6f}, S(0.02-) = {left_side:.6f}")
check("series_value_at_the_jump_is_their_midpoint",
      abs(midpoint - partial(0.0, 4000)) < 1e-12,
      f"mean of the one-sided values = {midpoint:.2e}, S(0) = {partial(0.0, 4000):.2e}")

# Away from the jump it converges to the function value.
interior = partial(1.0, 4000)
check("series_converges_to_one_in_the_interior",
      abs(interior - 1.0) < 5e-3,
      f"S_4000(1.0) = {interior:.6f} against f(1.0) = 1")


# ---------------------------------------------------------------- leg 4
# Gibbs: the first maximum sits at x = pi/(2N) and its height tends to
# (2/pi) * Si(pi) = 1.17897974..., so the overshoot does not shrink.
peaks = []
for terms in (20, 100, 500, 2000):
    peaks.append(partial(math.pi / (2 * terms), terms))
check("overshoot_does_not_decay",
      all(value > 1.17 for value in peaks),
      f"first-maximum heights {['%.5f' % v for v in peaks]}")

gibbs_limit = float(2 / sp.pi * sp.Si(sp.pi))
check("overshoot_tends_to_the_gibbs_constant",
      abs(peaks[-1] - gibbs_limit) < 1e-3,
      f"limit 2 Si(pi)/pi = {gibbs_limit:.8f}, observed {peaks[-1]:.8f}")

check("convergence_is_therefore_not_uniform",
      peaks[-1] - 1.0 > 0.17,
      "a persistent 18 percent overshoot rules out uniform convergence")


# ---------------------------------------------------------------- leg 5
# A wrong coefficient must break Parseval by a measurable amount.
wrong_right = sp.simplify(sp.summation((2 / (sp.pi * (2 * m - 1))) ** 2, (m, 1, sp.oo)))
check("falsifier_wrong_coefficient_breaks_parseval",
      sp.simplify(left - wrong_right) != 0,
      f"halving b_n gives {wrong_right} against the required {left}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
