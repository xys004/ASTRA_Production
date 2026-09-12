"""Newton's method is quadratic at a simple root and only linear at a double one.

CLAIM: for a simple root a of f with f'(a) nonzero, the Newton error obeys
e_{n+1} = (f''(a) / (2 f'(a))) e_n^2 + O(e_n^3), so convergence is quadratic
with that exact asymptotic constant. At a root of multiplicity two the same
iteration converges only linearly, with ratio exactly 1/2.

The asymptotic constant is derived symbolically and then measured by running the
real iteration in extended precision. Both must agree, and the second claim is
what stops the first from being stated more broadly than it holds.

Legs:
  1. recurrence -- the error map is expanded about the root and the linear term
                   is required to cancel, which is what makes it quadratic;
  2. constant   -- the surviving coefficient is f''(a)/(2 f'(a)) exactly;
  3. measured   -- iterating a concrete function reproduces that constant, with
                   the exponent estimated from consecutive errors rather than
                   assumed;
  4. multiple   -- at a double root the measured ratio is 1/2 and the quadratic
                   law fails, so the simple-root hypothesis carries weight;
  5. falsifier  -- dropping the derivative from the update destroys the rate,
                   which the same measurement detects.
"""
import mpmath as mp
import sympy as sp

e = sp.Symbol("e", real=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Write x_n = a + e and expand the Newton update. With f(a) = 0 the constant
# term vanishes; the claim is that the term linear in e vanishes too.
# Work on the Taylor coefficients directly, which avoids differentiating with
# respect to a compound expression.
f0, f1, f2, f3 = sp.symbols("f_0 f_1 f_2 f_3", real=True)
series_f = f0 + f1 * e + f2 * e**2 / 2 + f3 * e**3 / 6
series_df = f1 + f2 * e + f3 * e**2 / 2

# At a simple root f0 = 0 and f1 != 0.
next_error = sp.simplify(
    (e - (series_f / series_df)).subs(f0, 0)
)
expansion = sp.series(next_error, e, 0, 4).removeO()
expansion = sp.expand(expansion)

linear_term = sp.simplify(expansion.coeff(e, 1))
check("linear_term_of_the_error_map_cancels", linear_term == 0,
      f"coefficient of e is {linear_term}, so the error is not merely contracted")

constant_term = sp.simplify(expansion.coeff(e, 0))
check("no_constant_term_survives", constant_term == 0,
      f"coefficient of e^0 is {constant_term}, so the root is a fixed point")


# ---------------------------------------------------------------- leg 2
quadratic_coefficient = sp.simplify(expansion.coeff(e, 2))
check("quadratic_coefficient_is_f2_over_two_f1",
      sp.simplify(quadratic_coefficient - f2 / (2 * f1)) == 0,
      f"e_(n+1) = ({quadratic_coefficient}) e_n^2 + ...")


# ---------------------------------------------------------------- leg 3
mp.mp.dps = 60
# A concrete simple root: cos(x) - x has one root near 0.739, and the
# derivative there is nonzero, so the hypothesis is satisfied.
target = mp.findroot(lambda t: mp.cos(t) - t, mp.mpf("0.7"))
fp = lambda t: -mp.sin(t) - 1
fpp = lambda t: -mp.cos(t)
predicted = fpp(target) / (2 * fp(target))

value = mp.mpf("1.5")
errors = []
for _ in range(8):
    errors.append(value - target)
    value = value - (mp.cos(value) - value) / (-mp.sin(value) - 1)

# The asymptotic constant is approached as the error shrinks, so an early ratio
# is not a fair measurement of it. Take the last index where the NEXT error is
# still comfortably above the precision floor, below which the quotient measures
# rounding rather than the method.
FLOOR = mp.mpf("1e-40")
usable = [i for i in range(len(errors) - 1) if abs(errors[i + 1]) > FLOOR]
last = usable[-1]
measured = errors[last + 1] / errors[last] ** 2
check("measured_constant_matches_the_prediction",
      abs(measured - predicted) < mp.mpf("1e-10"),
      f"e_{last + 1}/e_{last}^2 = {mp.nstr(measured, 14)} against predicted "
      f"{mp.nstr(predicted, 14)}")

# The exponent is estimated from three consecutive errors rather than two. The
# two-point form log|e_(n+1)| / log|e_n| still carries the constant and reads
# 2.19 here; the ratio-of-ratios cancels it and reads 2.0000.
order_index = last - 1
exponent = (
    mp.log(abs(errors[order_index + 1] / errors[order_index]))
    / mp.log(abs(errors[order_index] / errors[order_index - 1]))
)
check("measured_order_is_two",
      abs(exponent - 2) < mp.mpf("1e-3"),
      f"order estimate from e_{order_index - 1}..e_{order_index + 1} = "
      f"{mp.nstr(exponent, 10)}")


# ---------------------------------------------------------------- leg 4
# A double root. (x - 1)^2 has f'(1) = 0, so the hypothesis fails and the
# theorem does not apply; the rate must drop to linear with ratio 1/2.
double_errors = []
value = mp.mpf("2.0")
for _ in range(40):
    double_errors.append(value - 1)
    value = value - (value - 1) ** 2 / (2 * (value - 1))

linear_ratio = double_errors[-1] / double_errors[-2]
check("double_root_converges_linearly_with_ratio_one_half",
      abs(linear_ratio - mp.mpf("0.5")) < mp.mpf("1e-20"),
      f"e_(n+1)/e_n = {mp.nstr(linear_ratio, 12)}")

quadratic_ratio = double_errors[-1] / double_errors[-2] ** 2
check("quadratic_law_fails_at_the_double_root",
      abs(quadratic_ratio) > mp.mpf("1e6"),
      f"e_(n+1)/e_n^2 = {mp.nstr(quadratic_ratio, 6)} and grows without bound")


# ---------------------------------------------------------------- leg 5
# Dropping the derivative gives a fixed-point iteration whose order is one, and
# the same exponent estimate must see that.
plain = []
value = mp.mpf("0.9")
for _ in range(30):
    plain.append(value - target)
    value = mp.cos(value)

# The SAME three-point estimator used above, so the comparison is like for like.
plain_exponent = (
    mp.log(abs(plain[-1] / plain[-2])) / mp.log(abs(plain[-2] / plain[-3]))
)
check("falsifier_derivative_free_iteration_is_only_first_order",
      abs(plain_exponent - 1) < mp.mpf("1e-3"),
      f"the same estimator gives {mp.nstr(plain_exponent, 10)}, not 2")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
