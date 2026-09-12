"""The master theorem has three cases and a gap between them.

CLAIM: for T(n) = a T(n/b) + f(n) the critical exponent is log_b a, and each of
the three cases is verified here by unrolling the recurrence on exact powers of
b and summing in closed form rather than by quoting the result; the regularity
condition of the third case is checked rather than assumed; and a recurrence
whose driving function sits between the cases, f(n) = n / log n against a
critical exponent of one, is covered by none of them, which is shown by taking
the two limits that would have to hold and finding both fail. Its true order is
then obtained by unrolling, and comes out as n log log n.

The gap is the point. "Apply the master theorem" is taught as a procedure and it
is a theorem with hypotheses, and the recurrence that escapes it is neither
exotic nor contrived.

Legs:
  1. exponent  -- the critical exponent is computed, not recalled;
  2. first     -- a leaf-dominated recurrence is summed exactly and its order
                  read off the closed form;
  3. second    -- the balanced case likewise, giving the logarithmic factor;
  4. third     -- the root-dominated case, with the regularity condition tested;
  5. falsifier -- a recurrence in the gap, shown to fail both comparisons for
                  every positive epsilon;
  6. unrolled  -- its exact solution, which is a harmonic number, and hence an
                  order no case of the theorem could have produced.
"""
import math

import sympy as sp

n, k, i, eps = sp.symbols("n k i epsilon", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def critical_exponent(branches, division):
    """log_b a, the exponent the driving function is measured against."""
    return sp.simplify(sp.log(branches) / sp.log(division))


def unrolled(branches, division, driving, depth):
    """T(b^k) with T(1) = 0, summed in closed form over the levels.

    Each level contributes a^i copies of the driving function at b^(k-i), which
    is the recurrence written out rather than a result recalled about it.
    """
    term = branches ** i * driving(division ** (depth - i))
    return sp.simplify(sp.summation(term, (i, 0, depth - 1)))


# ---------------------------------------------------------------- leg 1
check("the_critical_exponent_of_eight_branches_halving_is_three",
      sp.simplify(critical_exponent(8, 2) - 3) == 0,
      f"log_2 8 = {critical_exponent(8, 2)}")

check("and_two_branches_halving_gives_one",
      sp.simplify(critical_exponent(2, 2) - 1) == 0,
      f"log_2 2 = {critical_exponent(2, 2)}")

check("and_it_moves_with_the_branching_rather_than_being_a_constant",
      sp.simplify(critical_exponent(3, 2) - sp.log(3) / sp.log(2)) == 0
      and bool(critical_exponent(3, 2) > critical_exponent(2, 2)),
      f"log_2 3 = {sp.nsimplify(critical_exponent(3, 2))}, about "
      f"{float(critical_exponent(3, 2)):.4f}, between the two above")


# ---------------------------------------------------------------- leg 2
leaf_heavy = unrolled(8, 2, lambda size: size ** 2, k)
check("the_leaf_dominated_recurrence_sums_to_a_difference_of_powers",
      sp.simplify(leaf_heavy - (8 ** k - 4 ** k)) == 0,
      f"summing eight to the i times four to the k minus i gives {leaf_heavy}")

check("whose_leading_term_is_the_critical_power",
      sp.limit(leaf_heavy / 8 ** k, k, sp.oo) == 1,
      "the ratio to eight to the k tends to one, so the total is of that order "
      "and the driving function contributes only a lower-order correction")


# ---------------------------------------------------------------- leg 3
balanced = unrolled(2, 2, lambda size: size, k)
check("the_balanced_recurrence_sums_to_the_size_times_the_depth",
      sp.simplify(balanced - k * 2 ** k) == 0,
      f"every level contributes the same total, giving {balanced}")

check("which_is_the_logarithmic_factor_the_second_case_predicts",
      sp.simplify(balanced.subs(k, sp.log(n) / sp.log(2))
                  - n * sp.log(n) / sp.log(2)) == 0,
      "writing the depth as the logarithm of the size gives n log n, the factor "
      "that separates this case from the other two")


# ---------------------------------------------------------------- leg 4
root_heavy = unrolled(2, 2, lambda size: size ** 2, k)
check("the_root_dominated_recurrence_sums_to_twice_the_top_level",
      sp.simplify(root_heavy - (2 * 4 ** k - 2 ** (k + 1))) == 0,
      f"the levels shrink geometrically, leaving {root_heavy}")

check("so_the_first_level_already_carries_the_order",
      sp.limit(root_heavy / 4 ** k, k, sp.oo) == 2,
      "the ratio to the top level tends to two, a constant, which is what "
      "root domination means")

# The third case needs the regularity condition, without which the geometric
# decay above is not guaranteed. Solved for the constant rather than asserted.
constant = sp.Symbol("c", positive=True)
regularity = sp.solve(sp.Eq(2 * (n / 2) ** 2, constant * n ** 2), constant)
check("and_the_regularity_condition_holds_with_a_constant_below_one",
      len(regularity) == 1 and sp.simplify(regularity[0] - sp.Rational(1, 2)) == 0,
      f"a f(n/b) = c f(n) forces c = {regularity[0] if regularity else 'none'}, "
      "which is under one, so the levels really do decay")


# ---------------------------------------------------------------- leg 5
# f(n) = n / log n against a critical exponent of one. Neither comparison the
# theorem offers can be made, and both failures are limits rather than opinions.
gap_driving = n / (sp.log(n) / sp.log(2))
smaller = sp.limit(gap_driving / n ** (1 - eps), n, sp.oo)
check("falsifier_the_driving_function_is_not_polynomially_smaller",
      smaller == sp.oo,
      f"f(n) over n to the one minus epsilon tends to {smaller} for every "
      "positive epsilon, so the first case cannot apply however small the "
      "epsilon is chosen")

larger = sp.limit(gap_driving / n ** (1 + eps), n, sp.oo)
check("and_it_is_not_polynomially_larger_either",
      larger == 0,
      f"f(n) over n to the one plus epsilon tends to {larger}, so the third "
      "case cannot apply either")

ratio = sp.limit(gap_driving / n, n, sp.oo)
check("while_it_is_not_of_the_critical_order_either",
      ratio == 0,
      f"f(n) over n itself tends to {ratio}, so it is not the balanced case; "
      "all three are excluded and the theorem simply says nothing here")


# ---------------------------------------------------------------- leg 6
# Unrolled, the levels give a harmonic sum, which is where the second logarithm
# comes from. Computed exactly, with the harmonic number left as itself.
level = sp.simplify(2 ** i * (2 ** (k - i) / (k - i)))
check("every_level_contributes_the_size_over_its_remaining_depth",
      sp.simplify(level - 2 ** k / (k - i)) == 0,
      f"level i contributes {level}, the same size each time divided by how "
      "much depth is left")

# Reindexed by j = k - i, which is what turns the level sum into the harmonic
# series. Left in the original index sympy returns it unevaluated, so the
# reindexing is a step and not a formality; the level by level evaluation
# below is what checks it was done correctly.
j = sp.Symbol("j", positive=True, integer=True)
gap_total = sp.simplify(2 ** k * sp.summation(1 / j, (j, 1, k)))
check("the_gap_recurrence_unrolls_to_a_harmonic_number_times_the_size",
      sp.simplify(gap_total / 2 ** k - sp.harmonic(k)) == 0,
      f"T(2^k) divided by the size is {sp.simplify(gap_total / 2 ** k)}, the "
      "k-th harmonic number, which no case of the theorem produces")


def exact_total(depth):
    """T(2^k) with T(1) = 0, evaluated level by level in exact arithmetic."""
    return sum(sp.Integer(2) ** step * sp.Rational(2 ** (depth - step), depth - step)
               for step in range(depth))


checked = [depth for depth in (4, 8, 16)
           if exact_total(depth) != 2 ** depth * sp.harmonic(depth)]
check("and_the_closed_form_matches_a_direct_evaluation",
      checked == [],
      "at depths four, eight and sixteen the summed form and the level by level "
      "evaluation agree exactly, so the closed form is not a misreading of the "
      "summation")

sizes = [2 ** depth for depth in (10, 20, 40)]
orders = [float(exact_total(int(math.log2(size)))
                / (size * math.log(math.log2(size))))
          for size in sizes]
check("its_order_is_the_size_times_the_logarithm_of_the_logarithm",
      all(0.5 < value < 2.0 for value in orders)
      and abs(orders[-1] - orders[-2]) < abs(orders[1] - orders[0]),
      f"T(n) over n log log n is {', '.join(f'{v:.4f}' for v in orders)} at "
      "sizes two to the ten, twenty and forty, settling rather than drifting")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
