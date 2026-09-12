"""A small residual certifies nothing, and the condition number says how little.

CLAIM: for A x = b with a computed x_hat, the error is exactly A^{-1} r where
r = b - A x_hat; the relative error is therefore bounded by the condition number
times the relative residual; that bound is attained, so it cannot be improved;
on the Hilbert matrix a residual at the rounding floor coexists with an error
many orders larger; and the same system solved in higher precision returns the
right answer, which places the fault in the conditioning of the problem rather
than in the algorithm.

This is the numerical form of the failure the whole corpus is about. "The
residual is tiny" reads like a certificate and is not one.

Legs:
  1. identity  -- the error is A^{-1} r exactly, shown on a symbolic system;
  2. bound     -- across a sweep the relative error never exceeds the condition
                  number times the relative residual;
  3. attained  -- a construction from the singular vectors meets the bound to
                  machine precision, so it is sharp and not merely valid;
  4. hilbert   -- the exact rational solution is computed, the float solution is
                  compared against it, and the residual and the error are
                  reported side by side;
  5. falsifier -- the residual is at the rounding floor while the error is not,
                  and on a well conditioned matrix the same residual does bound
                  the error;
  6. precision -- higher precision recovers the exact answer, so the algorithm is
                  sound and the conditioning is what fails.
"""
import math

import mpmath as mp
import numpy as np
import sympy as sp

FAILURES = []


# Note on the comparisons below: a numpy comparison returns numpy's own
# boolean, which prints as True and even reports its type name as "bool", yet
# fails "is True". Every numeric verdict taken from an array is therefore
# passed through bool() before it reaches check.
def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# The identity that makes the condition number appear at all. Everything below
# is a consequence of it, so it is derived symbolically rather than assumed.
a11, a12, a21, a22 = sp.symbols("a_11 a_12 a_21 a_22", real=True)
x1, x2, e1, e2 = sp.symbols("x_1 x_2 e_1 e_2", real=True)
matrix = sp.Matrix([[a11, a12], [a21, a22]])
exact = sp.Matrix([x1, x2])
computed = exact + sp.Matrix([e1, e2])

residual = sp.simplify(matrix * exact - matrix * computed)
recovered = sp.simplify(matrix.inv() * residual)
check("the_error_is_the_inverse_matrix_applied_to_the_residual",
      sp.simplify(recovered - (exact - computed)) == sp.zeros(2, 1),
      f"A^-1 (b - A x_hat) = {list(recovered)}, which is x - x_hat")

check("a_zero_residual_means_a_zero_error_only_because_A_is_invertible",
      sp.simplify(recovered.subs({e1: 0, e2: 0})) == sp.zeros(2, 1),
      "with no error the residual vanishes, and the inverse carries it back")


# ---------------------------------------------------------------- leg 2
rng = np.random.default_rng(20260911)


def relative_quantities(operator, truth, approximation):
    """Relative error and relative residual for one solve, both in the 2-norm."""
    right_hand_side = operator @ truth
    leftover = right_hand_side - operator @ approximation
    return (np.linalg.norm(truth - approximation) / np.linalg.norm(truth),
            np.linalg.norm(leftover) / np.linalg.norm(right_hand_side))


ratios = []
for _ in range(400):
    size = int(rng.integers(2, 7))
    operator = rng.normal(size=(size, size))
    truth = rng.normal(size=size)
    approximation = truth + 1e-6 * rng.normal(size=size)
    error, leftover = relative_quantities(operator, truth, approximation)
    ratios.append(error / (leftover * np.linalg.cond(operator)))

check("the_bound_holds_on_every_system_in_the_sweep",
      bool(max(ratios) <= 1 + 1e-9),
      f"the largest ratio of the relative error to kappa times the relative "
      f"residual is {max(ratios):.9f} over {len(ratios)} random systems")

check("the_bound_is_not_vacuous_on_that_sweep",
      bool(max(ratios) > 1e-3),
      f"the ratio reaches {max(ratios):.6f}, so the inequality is doing work "
      "rather than being satisfied by many orders of slack everywhere")


# ---------------------------------------------------------------- leg 3
# Attainment, built rather than searched for. Put the true solution along the
# right singular vector of the largest singular value and the residual along the
# left singular vector of the smallest: the two ratios then multiply to kappa.
target = np.array([[1.0, 1.0], [1.0, 1.0 + 1e-8]])
left, singular, right_transposed = np.linalg.svd(target)
worst_truth = right_transposed[0]
worst_residual = 1e-9 * left[:, -1]
worst_approximation = worst_truth - np.linalg.solve(target, worst_residual)

worst_error, worst_leftover = relative_quantities(target, worst_truth, worst_approximation)
attained = worst_error / (worst_leftover * np.linalg.cond(target))

# Recomputing a residual this small from vectors of order one is a subtraction
# of nearly equal numbers, so the recomputed residual carries a relative
# uncertainty of about the machine epsilon divided by its own relative size.
# That is the floor the agreement below can reach, and it is computed rather
# than guessed at.
recompute_floor = 2.3e-16 / worst_leftover
check("the_worst_case_construction_meets_the_bound",
      bool(abs(attained - 1.0) < 10 * recompute_floor),
      f"the ratio is {attained:.12f}, off by {abs(attained - 1.0):.3e} against "
      f"a recomputation floor of {recompute_floor:.3e}, so the condition "
      f"number {np.linalg.cond(target):.3e} is the exact amplification and "
      "not a loose envelope")

check("that_construction_used_the_extreme_singular_directions",
      bool(abs(singular[0] / singular[-1] - np.linalg.cond(target))
           / np.linalg.cond(target) < 1e-12),
      f"singular values {singular[0]:.6e} and {singular[-1]:.6e}, whose ratio is "
      "the condition number by definition")


# ---------------------------------------------------------------- leg 4
SIZE = 8
hilbert_exact = sp.Matrix(SIZE, SIZE, lambda i, j: sp.Rational(1, i + j + 1))
truth_exact = sp.Matrix([1] * SIZE)
rhs_exact = hilbert_exact * truth_exact

# Solved exactly over the rationals, so the target is not itself a float result.
solved_exact = hilbert_exact.solve(rhs_exact)
check("the_exact_rational_solution_is_the_vector_of_ones",
      solved_exact == truth_exact,
      f"solving over the rationals returns {list(solved_exact)}")

hilbert = np.array([[1.0 / (i + j + 1) for j in range(SIZE)] for i in range(SIZE)])
rhs = np.array([float(value) for value in rhs_exact])
solved_float = np.linalg.solve(hilbert, rhs)
float_error, float_leftover = relative_quantities(
    hilbert, np.ones(SIZE), solved_float
)
condition = np.linalg.cond(hilbert)
check("the_hilbert_matrix_of_this_size_is_severely_ill_conditioned",
      bool(condition > 1e9),
      f"kappa(H_{SIZE}) = {condition:.3e}")


# ---------------------------------------------------------------- leg 5
check("the_residual_sits_at_the_rounding_floor",
      bool(float_leftover < 1e-14),
      f"relative residual {float_leftover:.3e}, which is where double precision "
      "arithmetic leaves it")

check("falsifier_the_error_is_many_orders_larger_than_the_residual",
      bool(float_error > 1e6 * float_leftover),
      f"relative error {float_error:.3e} against residual {float_leftover:.3e}, "
      f"a factor of {float_error / float_leftover:.3e}; the residual certifies "
      "nothing on its own")

check("the_gap_is_still_inside_the_bound",
      bool(float_error <= condition * float_leftover * (1 + 1e-9)),
      f"error {float_error:.3e} against kappa times residual "
      f"{condition * float_leftover:.3e}")

# The same tiny residual on a well conditioned matrix does bound the error, and
# that contrast is what shows the conditioning is responsible.
tame = np.array([[4.0, 1.0], [1.0, 3.0]])
tame_truth = np.array([1.0, 1.0])
# The residual goes along the worst direction for THIS matrix. A residual in an
# arbitrary direction would leave the error small on an ill-conditioned matrix
# too, purely by missing the bad direction, and the check would then be about
# the choice of perturbation rather than about the conditioning.
tame_left, _, _ = np.linalg.svd(tame)
tame_approximation = tame_truth - np.linalg.solve(tame, 1e-14 * tame_left[:, -1])
tame_error, tame_leftover = relative_quantities(tame, tame_truth, tame_approximation)
check("on_a_well_conditioned_matrix_the_same_residual_does_bound_the_error",
      bool(tame_error < 5 * tame_leftover),
      f"kappa = {np.linalg.cond(tame):.3f}, and with the residual on the worst "
      f"direction the relative error {tame_error:.3e} sits against a residual of "
      f"{tame_leftover:.3e}, an amplification of "
      f"{tame_error / tame_leftover:.3f}")


# ---------------------------------------------------------------- leg 6
mp.mp.dps = 60
hilbert_high = mp.matrix(SIZE, SIZE)
for i in range(SIZE):
    for j in range(SIZE):
        hilbert_high[i, j] = mp.mpf(1) / (i + j + 1)
rhs_high = hilbert_high * mp.matrix([mp.mpf(1)] * SIZE)
solved_high = mp.lu_solve(hilbert_high, rhs_high)
high_error = max(abs(solved_high[i] - 1) for i in range(SIZE))

# The precision is chosen from the conditioning, not tried until it worked: the
# solve loses about log10(kappa) digits, so sixty digits must leave roughly
# fifty, and the threshold below is set from that count rather than from taste.
lost_digits = math.log10(condition)
expected_floor = mp.mpf(10) ** -(mp.mp.dps - lost_digits - 5)
check("higher_precision_recovers_the_exact_solution",
      high_error < expected_floor,
      f"largest deviation {mp.nstr(high_error, 6)} at {mp.mp.dps} digits, against "
      f"a floor of {mp.nstr(expected_floor, 6)} from losing "
      f"{lost_digits:.1f} digits to the conditioning")

check("so_the_algorithm_was_sound_and_the_problem_was_not",
      high_error < float_error * 1e-20,
      f"the same elimination gives {mp.nstr(high_error, 6)} in wide arithmetic "
      f"against {float_error:.3e} in double, on the identical matrix")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
