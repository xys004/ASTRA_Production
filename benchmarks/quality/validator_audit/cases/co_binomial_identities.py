"""Four binomial identities, each checked against an independently built triangle.

CLAIM: Pascal's rule, the row sum 2^n, Vandermonde's convolution and the hockey
stick identity all hold for binomial coefficients. Each is verified against a
Pascal triangle built here by addition alone, so agreement is between two
independent constructions rather than a library confirming itself.

Legs:
  1. construction -- the hand-built triangle agrees with sympy's binomial over
                     the whole range, which is what licenses using either below;
  2. pascal       -- the recurrence holds symbolically in n and k, not only on
                     the numeric grid;
  3. sums         -- the row sum is 2^n and the alternating row sum vanishes for
                     every n above zero, both proved symbolically and confirmed
                     on the triangle;
  4. convolutions -- Vandermonde and hockey stick hold over exhaustive ranges,
                     each computed from the triangle and compared with the
                     closed form from sympy, so the two routes must agree;
  5. falsifier    -- a plausible near-miss of Vandermonde is rejected.
"""
import sympy as sp

n, k, m, r = sp.symbols("n k m r", integer=True, nonnegative=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


SIZE = 22


def build_triangle(rows):
    """Pascal's triangle by addition only. No factorials, no library calls."""
    triangle = [[1]]
    for row_index in range(1, rows):
        previous = triangle[-1]
        row = [1]
        for position in range(1, row_index):
            row.append(previous[position - 1] + previous[position])
        row.append(1)
        triangle.append(row)
    return triangle


TRIANGLE = build_triangle(SIZE)


def coefficient(top, bottom):
    """Binomial from the hand-built triangle, zero outside the range."""
    if bottom < 0 or bottom > top or top >= SIZE:
        return 0
    return TRIANGLE[top][bottom]


# ---------------------------------------------------------------- leg 1
agreement_ok = True
agreement_detail = ""
compared = 0
for top in range(SIZE):
    for bottom in range(top + 1):
        compared += 1
        if coefficient(top, bottom) != int(sp.binomial(top, bottom)):
            agreement_ok = False
            agreement_detail = f"C({top},{bottom}): triangle {coefficient(top, bottom)}, sympy {sp.binomial(top, bottom)}"
            break
    if not agreement_ok:
        break
check("triangle_and_library_agree_everywhere", agreement_ok,
      agreement_detail or f"{compared} coefficients, addition against factorials")


# ---------------------------------------------------------------- leg 2
# Pascal's rule symbolically, in the free integers, not only on the grid above.
pascal_gap = sp.simplify(
    sp.binomial(n, k) - sp.binomial(n - 1, k - 1) - sp.binomial(n - 1, k)
)
check("pascal_rule_holds_symbolically", sp.simplify(pascal_gap) == 0,
      f"C(n,k) - C(n-1,k-1) - C(n-1,k) = {pascal_gap}")

# And the same recurrence is what the triangle was built from, so it must hold
# there too. The two legs overlap deliberately: a disagreement between them
# would localise an error without any external reviewer.
recurrence_ok = all(
    coefficient(top, bottom)
    == coefficient(top - 1, bottom - 1) + coefficient(top - 1, bottom)
    for top in range(1, SIZE)
    for bottom in range(1, top)
)
check("triangle_satisfies_the_same_recurrence", recurrence_ok,
      "every interior entry equals the sum of the two above it")


# ---------------------------------------------------------------- leg 3
row_sum_symbolic = sp.simplify(sp.summation(sp.binomial(n, k), (k, 0, n)) - 2**n)
check("row_sum_is_two_to_the_n_symbolically", row_sum_symbolic == 0,
      f"sum_k C(n,k) - 2^n = {row_sum_symbolic}")

row_sum_numeric = all(sum(TRIANGLE[top]) == 2**top for top in range(SIZE))
check("triangle_rows_sum_to_two_to_the_n", row_sum_numeric,
      f"verified on all {SIZE} rows built by addition")

alternating_ok = all(
    sum((-1) ** bottom * TRIANGLE[top][bottom] for bottom in range(top + 1)) == 0
    for top in range(1, SIZE)
)
check("alternating_row_sum_vanishes_above_row_zero", alternating_ok,
      "rows 1 to 21, each alternating sum exactly zero")

# Row zero is the exception and must be stated, not quietly skipped.
check("row_zero_is_the_stated_exception",
      sum((-1) ** bottom * TRIANGLE[0][bottom] for bottom in range(1)) == 1,
      "the alternating sum of row zero is 1, which is why the claim starts at n = 1")


# ---------------------------------------------------------------- leg 4
vandermonde_ok = True
vandermonde_detail = ""
for left in range(12):
    for right in range(12):
        for total in range(left + right + 1):
            convolution = sum(
                coefficient(left, j) * coefficient(right, total - j)
                for j in range(0, total + 1)
            )
            closed_form = int(sp.binomial(left + right, total))
            if convolution != closed_form:
                vandermonde_ok = False
                vandermonde_detail = (
                    f"m={left}, n={right}, r={total}: {convolution} != {closed_form}"
                )
                break
        if not vandermonde_ok:
            break
    if not vandermonde_ok:
        break
check("vandermonde_convolution_holds", vandermonde_ok,
      vandermonde_detail or "144 pairs, every total, triangle against closed form")

hockey_ok = True
hockey_detail = ""
for base in range(10):
    for top in range(base, SIZE - 1):
        partial = sum(coefficient(i, base) for i in range(base, top + 1))
        closed_form = int(sp.binomial(top + 1, base + 1))
        if partial != closed_form:
            hockey_ok = False
            hockey_detail = f"r={base}, n={top}: {partial} != {closed_form}"
            break
    if not hockey_ok:
        break
check("hockey_stick_identity_holds", hockey_ok,
      hockey_detail or "all starting positions and lengths in range")


# ---------------------------------------------------------------- leg 5
# A near-miss of Vandermonde, with the second index not complemented, must be
# rejected. If it were not, leg 4 would pass for the wrong convolution too.
near_miss_matches = 0
near_miss_tested = 0
for left in range(2, 8):
    for right in range(2, 8):
        for total in range(1, left + right):
            near_miss_tested += 1
            wrong = sum(
                coefficient(left, j) * coefficient(right, total)
                for j in range(0, total + 1)
            )
            if wrong == int(sp.binomial(left + right, total)):
                near_miss_matches += 1
check("falsifier_rejects_the_uncomplemented_convolution",
      near_miss_tested > 0 and near_miss_matches < near_miss_tested,
      f"the wrong convolution matches on only {near_miss_matches} of "
      f"{near_miss_tested} cases, so the test discriminates")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
