"""Lagrange multipliers reproduce the substitution answer, and the multiplier is a rate.

CLAIM: maximising f(x, y) = x*y subject to x + y = s has the unique interior
solution x = y = s/2 with value s^2/4; the multiplier equals dF*/ds, the rate at
which the optimum improves as the constraint is relaxed; and the same statement
is the arithmetic-geometric mean inequality with its equality case.

Two routes are computed independently, the multiplier method and direct
substitution, and required to agree. The envelope identity then gives the
multiplier a meaning that can be checked rather than merely reported.

Legs:
  1. stationarity -- the multiplier system is solved, not guessed, and the
                     solution set is required to be exactly one point;
  2. substitution -- eliminating the constraint and maximising in one variable
                     reaches the same point, by a route sharing no algebra;
  3. envelope     -- dF*/ds equals the multiplier exactly, which is what makes
                     the multiplier a shadow price rather than bookkeeping;
  4. second order -- the bordered Hessian confirms a maximum, so the stationary
                     point is not merely stationary;
  5. falsifier    -- an off-constraint point and a non-stationary point are both
                     rejected by the same conditions.
"""
import sympy as sp

x, y, s, lam = sp.symbols("x y s lambda", real=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


objective = x * y
constraint = x + y - s


# ---------------------------------------------------------------- leg 1
lagrangian = objective - lam * constraint
system = [
    sp.Eq(sp.diff(lagrangian, x), 0),
    sp.Eq(sp.diff(lagrangian, y), 0),
    sp.Eq(constraint, 0),
]
solutions = sp.solve(system, [x, y, lam], dict=True)
check("multiplier_system_has_a_unique_solution",
      len(solutions) == 1,
      f"{len(solutions)} solution(s): {solutions}")

solution = solutions[0]
check("stationary_point_is_the_midpoint",
      sp.simplify(solution[x] - s / 2) == 0
      and sp.simplify(solution[y] - s / 2) == 0,
      f"x = {solution[x]}, y = {solution[y]}")
check("multiplier_is_half_the_constraint_level",
      sp.simplify(solution[lam] - s / 2) == 0,
      f"lambda = {solution[lam]}")

optimum = sp.simplify(objective.subs(solution))
check("optimal_value_is_s_squared_over_four",
      sp.simplify(optimum - s**2 / 4) == 0,
      f"F* = {optimum}")


# ---------------------------------------------------------------- leg 2
# Eliminate the constraint instead. This route never forms a Lagrangian, so
# agreement between the two is evidence rather than restatement.
reduced = sp.simplify(objective.subs(y, s - x))
critical = sp.solve(sp.Eq(sp.diff(reduced, x), 0), x)
check("substitution_route_has_one_critical_point",
      len(critical) == 1,
      f"critical points in x: {critical}")
check("substitution_route_agrees_with_the_multiplier_route",
      sp.simplify(critical[0] - solution[x]) == 0,
      f"substitution gives x = {critical[0]}, multipliers give x = {solution[x]}")

reduced_optimum = sp.simplify(reduced.subs(x, critical[0]))
check("both_routes_give_the_same_optimal_value",
      sp.simplify(reduced_optimum - optimum) == 0,
      f"{reduced_optimum} from substitution, {optimum} from multipliers")


# ---------------------------------------------------------------- leg 3
# Envelope: the multiplier is the derivative of the optimal value with respect
# to the constraint level. Both sides are computed, neither is quoted.
value_function = sp.simplify(optimum)
envelope_gap = sp.simplify(sp.diff(value_function, s) - solution[lam])
check("multiplier_equals_the_derivative_of_the_optimum",
      envelope_gap == 0,
      f"dF*/ds - lambda = {envelope_gap}, with dF*/ds = {sp.diff(value_function, s)}")


# ---------------------------------------------------------------- leg 4
# Second order along the constraint. The reduced problem is one dimensional, so
# the sign of its second derivative settles maximum against minimum.
second_derivative = sp.simplify(sp.diff(reduced, x, 2))
check("reduced_problem_is_strictly_concave",
      sp.simplify(second_derivative + 2) == 0,
      f"d2/dx2 of the reduced objective = {second_derivative}, negative")

# And the bordered Hessian, the multivariable statement of the same fact.
bordered = sp.Matrix([
    [0, sp.diff(constraint, x), sp.diff(constraint, y)],
    [sp.diff(constraint, x), sp.diff(lagrangian, x, 2), sp.diff(sp.diff(lagrangian, x), y)],
    [sp.diff(constraint, y), sp.diff(sp.diff(lagrangian, y), x), sp.diff(lagrangian, y, 2)],
])
determinant = sp.simplify(bordered.det())
check("bordered_hessian_has_the_sign_of_a_maximum",
      sp.simplify(determinant - 2) == 0,
      f"det = {determinant}, positive, which for one constraint in two "
      "variables is the maximum condition")


# ---------------------------------------------------------------- leg 5
# The arithmetic-geometric mean statement, with its equality case, is the same
# claim. A point off the diagonal must do strictly worse.
off_diagonal = sp.simplify(
    (objective.subs({x: s / 2 + sp.Symbol("d", positive=True),
                     y: s / 2 - sp.Symbol("d", positive=True)}) - optimum)
)
check("any_displacement_along_the_constraint_loses_value",
      sp.simplify(off_diagonal + sp.Symbol("d", positive=True) ** 2) == 0,
      f"value at the displaced point minus the optimum = {off_diagonal}")

# A point violating the constraint is rejected by the constraint equation
# itself, not by the objective, which is the other way the conditions bind.
violating = {x: s / 3, y: s / 3}
check("falsifier_off_constraint_point_is_rejected",
      sp.simplify(constraint.subs(violating)) != 0,
      f"constraint residual at x = y = s/3 is {sp.simplify(constraint.subs(violating))}")

non_stationary = {x: s / 3, y: 2 * s / 3}
gradient_gap = sp.simplify(
    sp.diff(objective, x).subs(non_stationary)
    - sp.diff(objective, y).subs(non_stationary)
)
check("falsifier_non_stationary_point_is_rejected",
      sp.simplify(constraint.subs(non_stationary)) == 0 and gradient_gap != 0,
      f"the point satisfies the constraint but the gradients differ by {gradient_gap}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
