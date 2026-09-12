"""Linear stability, Routh-Hurwitz and the Lyapunov equation agree, and the
Lyapunov construction fails quietly.

CLAIM: for x' = A x with A a real two by two matrix, the characteristic
polynomial is lambda^2 - tr(A) lambda + det(A); both roots have negative real
part exactly when the trace is negative and the determinant positive; for such an
A the equation A^T P + P A = -Q has a unique solution and it is positive
definite, so V = x^T P x decreases along every trajectory at the rate -x^T Q x;
for an unstable A the same equation still has a unique solution but that solution
is indefinite; and when two eigenvalues sum to zero it has none at all.

The quiet failure is the point. An unstable system does not make the solver
raise; it returns a matrix that is simply not a Lyapunov function, and only the
positive definiteness test tells the difference.

Legs:
  1. characteristic -- the polynomial and Vieta's relations are read off A;
  2. routh          -- both directions of the sign criterion, argued by cases;
  3. lyapunov       -- the equation solved, the solution tested for definiteness,
                       and dV/dt along the flow computed rather than asserted;
  4. numeric        -- V falls at every step and decays at the rate the slowest
                       eigenvalue sets, with the residual itself predicted;
  5. falsifier      -- an unstable A gives a unique but indefinite P;
  6. singular       -- eigenvalues at plus and minus i leave no solution at all.
"""
import math

import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
a, b, c, d = sp.symbols("a b c d", real=True)
lam = sp.Symbol("lambda")
general = sp.Matrix([[a, b], [c, d]])

characteristic = sp.expand(sp.factor(general.charpoly(lam).as_expr()))
check("the_characteristic_polynomial_is_lambda_squared_minus_trace_plus_determinant",
      sp.simplify(characteristic
                  - (lam ** 2 - general.trace() * lam + general.det())) == 0,
      f"det(A - lambda I) = {characteristic}")

coefficients = sp.Poly(characteristic, lam).all_coeffs()
check("its_coefficients_are_one_minus_trace_and_determinant",
      len(coefficients) == 3
      and sp.simplify(coefficients[0] - 1) == 0
      and sp.simplify(coefficients[1] + general.trace()) == 0
      and sp.simplify(coefficients[2] - general.det()) == 0,
      f"coefficients {coefficients}")

roots = sp.solve(sp.Eq(characteristic, 0), lam)
check("the_two_roots_sum_to_the_trace_and_multiply_to_the_determinant",
      len(roots) == 2
      and sp.simplify(sum(roots) - general.trace()) == 0
      and sp.simplify(sp.expand(roots[0] * roots[1]) - general.det()) == 0,
      "Vieta's relations hold for the roots obtained from the polynomial")


# ---------------------------------------------------------------- leg 2
# Necessity, by cases on whether the roots are real. Both cases are decided by
# sympy from the declared signs, not by inspection.
first, second = sp.symbols("mu_1 mu_2", negative=True)
check("two_negative_real_roots_force_a_negative_trace_and_positive_determinant",
      (first + second).is_negative is True and (first * second).is_positive is True,
      f"sum {first + second} is negative, product {first * second} is positive")

real_part = sp.Symbol("xi", negative=True)
imaginary = sp.Symbol("eta", real=True, nonzero=True)
pair_sum = sp.simplify((real_part + sp.I * imaginary) + (real_part - sp.I * imaginary))
pair_product = sp.simplify((real_part + sp.I * imaginary) * (real_part - sp.I * imaginary))
check("a_conjugate_pair_with_negative_real_part_forces_the_same",
      pair_sum.is_negative is True and pair_product.is_positive is True,
      f"sum {pair_sum}, product {pair_product}")

# Sufficiency. Write the polynomial as lambda^2 + p lambda + q with p and q
# positive. When the discriminant is non-negative the larger root is
# (-p + sqrt(p^2 - 4q))/2, and it is negative exactly because the square root
# stays under p. That step is the content, so it is the step that is checked.
p_coeff, q_coeff = sp.symbols("p q", positive=True)
gap = sp.simplify(p_coeff ** 2 - (p_coeff ** 2 - 4 * q_coeff))
check("a_positive_determinant_keeps_the_square_root_under_the_trace",
      sp.simplify(gap - 4 * q_coeff) == 0 and gap.is_positive is True,
      f"p^2 - (p^2 - 4q) = {gap}, positive, so sqrt(p^2 - 4q) < p and the larger "
      "root is negative")

complex_real_part = sp.simplify(-p_coeff / 2)
check("a_negative_discriminant_leaves_the_real_part_at_minus_half_the_trace",
      complex_real_part.is_negative is True,
      f"Re(lambda) = {complex_real_part}, negative for every positive p")


# ---------------------------------------------------------------- leg 3
IDENTITY = sp.eye(2)


def lyapunov_solution(matrix, source):
    """Solve A^T P + P A = -Q over symmetric P, or return None when unsolvable.

    None here means the linear system is inconsistent, which is a fact about the
    spectrum rather than a failure of the solver, and leg 6 is where it is used.
    """
    p11, p12, p22 = sp.symbols("P_11 P_12 P_22", real=True)
    candidate = sp.Matrix([[p11, p12], [p12, p22]])
    residual = matrix.T * candidate + candidate * matrix + source
    answers = sp.solve(
        [residual[0, 0], residual[0, 1], residual[1, 1]], [p11, p12, p22], dict=True
    )
    if len(answers) != 1:
        return None
    filled = candidate.subs(answers[0])
    return filled if not filled.free_symbols else None


def definiteness(matrix):
    """Sylvester's criterion: both leading minors, as exact numbers.

    A missing solution has no minors, so the pair comes back as nan and the
    definiteness check fails on its own terms instead of raising two lines on.
    """
    if not isinstance(matrix, sp.Matrix):
        return sp.nan, sp.nan
    return sp.simplify(matrix[0, 0]), sp.simplify(matrix.det())


STABLE = sp.Matrix([[0, 1], [-2, -3]])
stable_eigenvalues = sorted(STABLE.eigenvals(), key=lambda value: sp.re(value))
check("the_chosen_matrix_is_stable",
      all(sp.re(value).is_negative is True for value in stable_eigenvalues),
      f"eigenvalues {stable_eigenvalues}, trace {STABLE.trace()}, "
      f"determinant {STABLE.det()}")

solution = lyapunov_solution(STABLE, IDENTITY)
check("the_lyapunov_equation_has_a_solution_for_a_stable_matrix",
      isinstance(solution, sp.Matrix),
      f"P = {solution.tolist() if isinstance(solution, sp.Matrix) else solution}")

leading, determinant = definiteness(solution)
check("that_solution_is_positive_definite",
      leading.is_positive is True and determinant.is_positive is True,
      f"leading minor {leading}, determinant {determinant}, both positive")

# The derivative of V along the flow, computed from the equation rather than
# quoted: substituting x' = A x into d(x^T P x)/dt must reproduce -x^T Q x.
x1, x2 = sp.symbols("x_1 x_2", real=True)
state = sp.Matrix([x1, x2])
# A missing P has no rate along the flow. Saying so as nan keeps the finding
# in the check below instead of turning it into a sympify error.
lyapunov_rate = (
    sp.simplify((state.T * (STABLE.T * solution + solution * STABLE) * state)[0])
    if isinstance(solution, sp.Matrix) else sp.nan
)
expected_rate = sp.simplify(-(state.T * IDENTITY * state)[0])
check("the_lyapunov_function_decreases_at_exactly_minus_the_quadratic_form",
      sp.simplify(lyapunov_rate - expected_rate) == 0,
      f"dV/dt = {lyapunov_rate}, which is -(x_1^2 + x_2^2)")


# ---------------------------------------------------------------- leg 4
def integrate(matrix, start, steps, step_size):
    """Runge-Kutta on x' = A x, returning the sampled trajectory."""
    entries = [[float(value) for value in row] for row in matrix.tolist()]

    def rate(vector):
        return [entries[0][0] * vector[0] + entries[0][1] * vector[1],
                entries[1][0] * vector[0] + entries[1][1] * vector[1]]

    current = list(start)
    trail = [(0.0, tuple(current))]
    for index in range(steps):
        k1 = rate(current)
        k2 = rate([v + 0.5 * step_size * k for v, k in zip(current, k1)])
        k3 = rate([v + 0.5 * step_size * k for v, k in zip(current, k2)])
        k4 = rate([v + step_size * k for v, k in zip(current, k3)])
        current = [v + step_size * (a1 + 2 * a2 + 2 * a3 + a4) / 6
                   for v, a1, a2, a3, a4 in zip(current, k1, k2, k3, k4)]
        trail.append(((index + 1) * step_size, tuple(current)))
    return trail


def quadratic_form(matrix, vector):
    if not isinstance(matrix, sp.Matrix):
        return math.nan
    entries = [[float(value) for value in row] for row in matrix.tolist()]
    return (entries[0][0] * vector[0] ** 2
            + 2 * entries[0][1] * vector[0] * vector[1]
            + entries[1][1] * vector[1] ** 2)


STEP = 1e-3
trajectory = integrate(STABLE, (1.0, 0.0), 10000, STEP)
values = [quadratic_form(solution, point) for _, point in trajectory]
descents = [later - earlier for earlier, later in zip(values, values[1:])]
check("the_lyapunov_function_falls_at_every_step_of_the_trajectory",
      max(descents) < 0,
      f"largest single-step change is {max(descents):.3e}, negative over all "
      f"{len(descents)} steps")

def decay_rate(first, second):
    """The apparent exponential rate of V between two sampled times."""
    t1, v1 = trajectory[first][0], values[first]
    t2, v2 = trajectory[second][0], values[second]
    if v1 <= 0.0 or v2 <= 0.0:
        # A logarithmic rate exists only for a positive quantity, and V being
        # positive is precisely what the definiteness leg established. If it
        # is not, that is the finding, not a domain error.
        return math.nan
    return -(math.log(v2) - math.log(v1)) / (t2 - t1)


def mode_contamination(first, second):
    """How much the faster mode shifts that apparent rate.

    V carries e^{-2t}, e^{-3t} and e^{-4t}. The middle term tilts the measured
    slope by the window average of e^{-t}, which is what this returns. The
    residual below is therefore predictable, and a residual one can predict is
    not a tolerance one has to choose.
    """
    t1, t2 = trajectory[first][0], trajectory[second][0]
    return (math.exp(-t1) - math.exp(-t2)) / (t2 - t1)


slowest = float(-max(sp.re(value) for value in stable_eigenvalues))
late_rate = decay_rate(7000, 9000)
late_gap = 2 * slowest - late_rate
check("the_decay_rate_approaches_twice_the_slowest_eigenvalue",
      abs(late_gap) < 1e-3,
      f"measured {late_rate:.9f} over t in [7, 9] against 2 x {slowest:.1f}")

check("the_residual_is_the_faster_mode_rather_than_numerical_noise",
      abs(late_gap / mode_contamination(7000, 9000) - 1) < 1e-3,
      f"gap {late_gap:.6e} against the predicted contamination "
      f"{mode_contamination(7000, 9000):.6e}, agreeing to "
      f"{abs(late_gap / mode_contamination(7000, 9000) - 1):.2e}")

early_gap = 2 * slowest - decay_rate(2000, 4000)
shrinkage = early_gap / late_gap
predicted_shrinkage = mode_contamination(2000, 4000) / mode_contamination(7000, 9000)
check("moving_the_window_later_shrinks_the_residual_as_predicted",
      abs(shrinkage / predicted_shrinkage - 1) < 0.05,
      f"the gap falls by a factor {shrinkage:.1f} between the windows and the "
      f"model asks for {predicted_shrinkage:.1f}")


# ---------------------------------------------------------------- leg 5
# An unstable matrix. No two eigenvalues sum to zero, so the equation is still
# uniquely solvable and the solver says nothing at all about stability.
UNSTABLE = sp.Matrix([[0, 1], [2, -1]])
unstable_eigenvalues = sorted(UNSTABLE.eigenvals(), key=lambda value: sp.re(value))
check("the_second_matrix_is_unstable",
      any(sp.re(value).is_positive is True for value in unstable_eigenvalues),
      f"eigenvalues {unstable_eigenvalues}")

unstable_solution = lyapunov_solution(UNSTABLE, IDENTITY)
check("the_lyapunov_equation_still_has_a_unique_solution_there",
      isinstance(unstable_solution, sp.Matrix),
      f"P = {unstable_solution.tolist() if isinstance(unstable_solution, sp.Matrix) else unstable_solution}, "
      "returned without complaint")

bad_leading, bad_determinant = definiteness(unstable_solution)
check("falsifier_but_that_solution_is_not_positive_definite",
      bad_leading.is_negative is True and bad_determinant.is_negative is True,
      f"leading minor {bad_leading} and determinant {bad_determinant}, so P is "
      "indefinite and V is not a Lyapunov function")

unstable_trajectory = integrate(UNSTABLE, (1.0, 0.0), 3000, STEP)
unstable_values = [quadratic_form(unstable_solution, point)
                   for _, point in unstable_trajectory]
final_norm = math.hypot(*unstable_trajectory[-1][1])
check("the_trajectory_grows_instead_of_decaying",
      final_norm > 10 * math.hypot(*unstable_trajectory[0][1]),
      f"the state norm goes from {math.hypot(*unstable_trajectory[0][1]):.3f} to "
      f"{final_norm:.3f} over {len(unstable_trajectory) - 1} steps")

check("and_the_candidate_function_is_negative_along_it",
      min(unstable_values) < 0,
      f"V reaches {min(unstable_values):.3f} on the trajectory, which a positive "
      "definite form could never do")


# ---------------------------------------------------------------- leg 6
ROTATION = sp.Matrix([[0, 1], [-1, 0]])
rotation_eigenvalues = list(ROTATION.eigenvals())
check("the_third_matrix_has_eigenvalues_on_the_imaginary_axis",
      all(sp.simplify(sp.re(value)) == 0 for value in rotation_eigenvalues)
      and sp.simplify(sum(rotation_eigenvalues)) == 0,
      f"eigenvalues {rotation_eigenvalues}, summing to zero in pairs")

check("the_lyapunov_equation_has_no_solution_at_all_there",
      lyapunov_solution(ROTATION, IDENTITY) is None,
      "the linear system is inconsistent, which is the Sylvester condition that "
      "no two eigenvalues may sum to zero")

# And the obstruction is real rather than an artefact of asking for a symmetric
# P: the two diagonal equations demand opposite values of the same entry.
p11, p12, p22 = sp.symbols("P_11 P_12 P_22", real=True)
trial = sp.Matrix([[p11, p12], [p12, p22]])
obstruction = ROTATION.T * trial + trial * ROTATION + IDENTITY
check("the_obstruction_is_two_incompatible_demands_on_one_entry",
      sp.simplify(obstruction[0, 0] + obstruction[1, 1]) == 2,
      f"the diagonal residuals add to {sp.simplify(obstruction[0, 0] + obstruction[1, 1])}, "
      "which cannot vanish for any P")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
