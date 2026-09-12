"""The logistic map loses stability at r = 3 and a two-cycle takes over.

CLAIM: the map x -> r x (1 - x) has fixed points 0 and 1 - 1/r; the nonzero one
is stable exactly for 1 < r < 3; at r = 3 its multiplier passes through -1 and a
two-cycle is born, real for r > 3 and given by the roots of
x^2 - (1 + 1/r) x + (1 + 1/r)/r = 0.

Every symbolic statement is paired with a numeric iteration of the actual map,
so the two must agree. A disagreement between the pair localises the error
inside the file, without needing anything outside it.

Legs:
  1. fixed      -- the fixed points are solved for, not quoted, and the solver's
                   output is required to be exactly those two;
  2. stability  -- the multiplier at each fixed point is differentiated and the
                   stability window is obtained by solving |f'| < 1;
  3. numeric    -- iterating the real map converges to the predicted fixed point
                   inside the window and leaves it outside, which is the same
                   claim reached without any algebra;
  4. two-cycle  -- the period-two orbit is obtained by factoring the fixed
                   points out of f(f(x)) - x, and its birth at r = 3 is located
                   by the discriminant rather than observed on a plot;
  5. falsifier  -- a wrong fixed point fails both the algebra and the iteration.
"""
import sympy as sp

x, r = sp.symbols("x r", real=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


logistic = r * x * (1 - x)


def iterate(rate, start, steps):
    """Iterate the real map. Independent of every symbolic result below."""
    value = start
    for _ in range(steps):
        value = rate * value * (1 - value)
    return value


# ---------------------------------------------------------------- leg 1
fixed_points = sp.solve(sp.Eq(logistic, x), x)
check("solver_returns_exactly_two_fixed_points",
      len(fixed_points) == 2,
      f"solutions: {fixed_points}")

as_set = {sp.simplify(point) for point in fixed_points}
check("fixed_points_are_zero_and_one_minus_one_over_r",
      as_set == {sp.Integer(0), sp.simplify(1 - 1 / r)},
      f"{sorted(as_set, key=sp.default_sort_key)}")


# ---------------------------------------------------------------- leg 2
multiplier = sp.diff(logistic, x)
at_zero = sp.simplify(multiplier.subs(x, 0))
at_nonzero = sp.simplify(multiplier.subs(x, 1 - 1 / r))
check("multiplier_at_zero_is_r", sp.simplify(at_zero - r) == 0,
      f"f'(0) = {at_zero}")
check("multiplier_at_the_nonzero_point_is_two_minus_r",
      sp.simplify(at_nonzero - (2 - r)) == 0,
      f"f'(1 - 1/r) = {at_nonzero}")

window = sp.solveset(sp.Abs(at_nonzero) < 1, r, sp.S.Reals)
check("stability_window_is_one_to_three",
      window == sp.Interval.open(1, 3),
      f"|2 - r| < 1 solves to {window}")

# The loss of stability is a multiplier of exactly -1, not merely a bound being
# crossed. Locating it separately is what identifies a period doubling.
doubling = sp.solve(sp.Eq(at_nonzero, -1), r)
check("multiplier_reaches_minus_one_at_r_equals_three",
      doubling == [3],
      f"f'(1 - 1/r) = -1 at r = {doubling}")


# ---------------------------------------------------------------- leg 3
# The same conclusions without algebra: iterate and see where it lands.
inside = iterate(2.5, 0.2, 4000)
predicted_inside = float((1 - 1 / r).subs(r, 2.5))
check("iteration_converges_inside_the_window",
      abs(inside - predicted_inside) < 1e-12,
      f"r = 2.5 converges to {inside:.12f}, predicted {predicted_inside:.12f}")

# Just outside, the orbit must NOT settle on the fixed point. Two iterates one
# step apart differ if the orbit has period two rather than one.
outside_even = iterate(3.2, 0.2, 4000)
outside_odd = iterate(3.2, 0.2, 4001)
predicted_outside = float((1 - 1 / r).subs(r, 3.2))
check("iteration_leaves_the_fixed_point_outside_the_window",
      abs(outside_even - outside_odd) > 1e-3
      and abs(outside_even - predicted_outside) > 1e-3,
      f"r = 3.2 alternates between {outside_even:.6f} and {outside_odd:.6f}, "
      f"neither at the fixed point {predicted_outside:.6f}")


# ---------------------------------------------------------------- leg 4
second = sp.simplify(logistic.subs(x, logistic))
orbit_polynomial = sp.simplify(sp.expand(second - x))
# The fixed points solve this too, so divide them out to isolate the genuine
# two-cycle. Dividing rather than subtracting keeps the remaining factor exact.
quotient = sp.simplify(sp.cancel(orbit_polynomial / (x * (x - (1 - 1 / r)))))

# The claim is about the ROOTS of that factor, so compare monic forms. Fixing an
# overall normalisation by hand would make the check depend on a bookkeeping
# constant rather than on the orbit, and getting that constant wrong would be a
# failure of arithmetic dressed as a failure of physics.
quotient_poly = sp.Poly(sp.expand(quotient), x)
monic = sp.simplify(sp.expand(quotient_poly.as_expr() / quotient_poly.LC()))
expected_monic = sp.expand(x**2 - (1 + 1 / r) * x + (1 + 1 / r) / r)
check("two_cycle_factor_is_the_expected_quadratic",
      sp.simplify(sp.expand(monic - expected_monic)) == 0,
      f"monic factor = {sp.factor(monic)}")

cycle_roots = sp.solve(sp.Eq(quotient, 0), x)
check("two_cycle_has_two_roots", len(cycle_roots) == 2,
      f"{len(cycle_roots)} roots for the period-two orbit")

# They are genuinely period two: applying the map once swaps them.
swapped = sp.simplify(logistic.subs(x, cycle_roots[0]) - cycle_roots[1])
check("the_map_swaps_the_two_cycle_points", sp.simplify(swapped) == 0,
      "f sends each root to the other, so the orbit has period two")

discriminant = sp.simplify(sp.discriminant(
    sp.Poly(x**2 - (1 + 1 / r) * x + (1 + 1 / r) / r, x)
))
birth = sp.solve(sp.Eq(discriminant, 0), r)
check("two_cycle_is_born_exactly_at_r_three",
      3 in [sp.simplify(value) for value in birth],
      f"discriminant {sp.factor(discriminant)} vanishes at r = {birth}")


# ---------------------------------------------------------------- leg 5
# A wrong fixed point must fail both routes, or neither leg 1 nor leg 3 is
# testing anything.
wrong_point = 1 - 2 / r
algebra_residual = sp.simplify(logistic.subs(x, wrong_point) - wrong_point)
check("falsifier_wrong_fixed_point_fails_the_algebra",
      sp.simplify(algebra_residual) != 0,
      f"f(1 - 2/r) - (1 - 2/r) = {sp.factor(algebra_residual)}, nonzero")

wrong_numeric = float(wrong_point.subs(r, 2.5))
check("falsifier_wrong_fixed_point_fails_the_iteration",
      abs(iterate(2.5, wrong_numeric, 1) - wrong_numeric) > 1e-6,
      f"one step moves it from {wrong_numeric:.6f} to "
      f"{iterate(2.5, wrong_numeric, 1):.6f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
