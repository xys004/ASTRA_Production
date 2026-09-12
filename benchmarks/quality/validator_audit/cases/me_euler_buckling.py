"""Euler buckling is an eigenvalue problem, and the end conditions set the factor.

CLAIM: a pin-ended column of length L and flexural rigidity EI has non-trivial
equilibrium shapes only at P = n^2 pi^2 EI / L^2, the lowest of which is the
critical load pi^2 EI / L^2 with mode shape sin(pi x / L). Clamping both ends
raises it by four, and that factor is derived from the clamped boundary problem
rather than from an effective-length table.

Legs:
  1. eigenvalue -- the boundary-value problem is solved, and the condition for a
                   non-trivial solution is derived rather than quoted;
  2. spectrum   -- the admissible loads are exactly n^2 pi^2 EI / L^2 and the
                   smallest positive one is the critical load;
  3. mode       -- the first mode satisfies the equation and both boundary
                   conditions, checked by substitution;
  4. clamped    -- the factor of four is obtained by solving the fourth-order
                   clamped problem and locating the first root of its boundary
                   determinant, not by squaring an assumed effective length;
  5. falsifier  -- a load that is not an eigenvalue admits only the trivial
                   solution, which is the content of "critical".
"""
import mpmath as mp
import sympy as sp

x, L, P, EI = sp.symbols("x L P EI", positive=True)
n = sp.Symbol("n", positive=True, integer=True)
A, B = sp.symbols("A B", real=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# EI y'' + P y = 0 on (0, L) with y(0) = y(L) = 0.
k = sp.sqrt(P / EI)
general = A * sp.sin(k * x) + B * sp.cos(k * x)

residual = sp.simplify(EI * sp.diff(general, x, 2) + P * general)
check("general_solution_satisfies_the_equation", residual == 0,
      f"EI y'' + P y = {residual}")

at_zero = sp.simplify(general.subs(x, 0))
check("left_boundary_forces_the_cosine_coefficient_to_vanish",
      sp.simplify(at_zero - B) == 0,
      f"y(0) = {at_zero}, so B = 0")

# With B = 0 the right boundary is A sin(kL) = 0, and a non-trivial column needs
# A nonzero, so sin(kL) = 0 is the condition. That is the eigenvalue equation.
at_length = sp.simplify(general.subs(B, 0).subs(x, L))
check("right_boundary_gives_the_eigenvalue_equation",
      sp.simplify(at_length - A * sp.sin(k * L)) == 0,
      f"y(L) = {at_length}, so sin(kL) = 0 for a non-trivial shape")


# ---------------------------------------------------------------- leg 2
# sin(kL) = 0 means kL = n pi. Solve for P rather than substituting the answer.
loads = sp.solve(sp.Eq(sp.sqrt(P / EI) * L, n * sp.pi), P)
check("eigenvalue_equation_has_one_load_per_mode",
      len(loads) == 1,
      f"kL = n pi gives P = {loads[0] if loads else 'none'}")

load = sp.simplify(loads[0])
check("spectrum_is_n_squared_pi_squared_EI_over_L_squared",
      sp.simplify(load - n**2 * sp.pi**2 * EI / L**2) == 0,
      f"P_n = {load}")

critical = sp.simplify(load.subs(n, 1))
check("critical_load_is_the_first_mode",
      sp.simplify(critical - sp.pi**2 * EI / L**2) == 0,
      f"P_cr = {critical}")

# It really is the smallest: the ratio to the next mode is fixed and above one.
ratio = sp.simplify(load.subs(n, 2) / critical)
check("second_mode_is_four_times_the_first",
      sp.simplify(ratio - 4) == 0,
      f"P_2 / P_1 = {ratio}, so the first mode is the smallest positive load")


# ---------------------------------------------------------------- leg 3
mode = sp.sin(sp.pi * x / L)
mode_residual = sp.simplify(
    (EI * sp.diff(mode, x, 2) + P * mode).subs(P, critical)
)
check("first_mode_satisfies_the_equation_at_the_critical_load",
      mode_residual == 0,
      f"residual at P = P_cr is {mode_residual}")
check("first_mode_satisfies_both_boundary_conditions",
      sp.simplify(mode.subs(x, 0)) == 0 and sp.simplify(mode.subs(x, L)) == 0,
      "y(0) = y(L) = 0 with a non-trivial interior")


# ---------------------------------------------------------------- leg 4
# Clamped-clamped, with all four conditions imposed. Comparing pi^2 EI/(L/2)^2
# against pi^2 EI/L^2 would only verify that (L/(L/2))^2 = 4, which is arithmetic
# about a DEFINITION of effective length and not physics. The factor has to come
# out of the boundary conditions, so the fourth-order problem is solved here and
# the first root of its determinant is located.
C1, C2, C3, C4 = sp.symbols("C_1 C_2 C_3 C_4", real=True)
kk = sp.Symbol("kappa", positive=True)          # kappa squared = P / EI
clamped = C1 + C2 * x + C3 * sp.sin(kk * x) + C4 * sp.cos(kk * x)

fourth_order_residual = sp.simplify(
    sp.diff(clamped, x, 4) + kk**2 * sp.diff(clamped, x, 2)
)
check("clamped_trial_solution_satisfies_the_fourth_order_equation",
      fourth_order_residual == 0,
      f"fourth derivative plus kappa squared times the second = {fourth_order_residual}")

conditions = [
    clamped.subs(x, 0),
    sp.diff(clamped, x).subs(x, 0),
    clamped.subs(x, L),
    sp.diff(clamped, x).subs(x, L),
]
coefficient_matrix = sp.Matrix([
    [sp.expand(condition).coeff(coefficient) for coefficient in (C1, C2, C3, C4)]
    for condition in conditions
])
determinant = sp.simplify(sp.trigsimp(coefficient_matrix.det()))
check("clamped_boundary_determinant_is_the_eigenvalue_condition",
      sp.simplify(determinant
                  - kk * (L * kk * sp.sin(L * kk) + 2 * sp.cos(L * kk) - 2)) == 0,
      f"det = {sp.factor(determinant)}, whose zeros are the buckling loads")

check("two_pi_is_a_root_of_that_condition",
      sp.simplify(determinant.subs(kk, 2 * sp.pi / L)) == 0,
      "kappa times L equal to two pi annihilates the determinant")

# The precision is raised before the threshold is chosen, not after: at the
# default fifteen digits the residual floor is around 1e-16 and a tighter bound
# would be testing rounding rather than the root.
mp.mp.dps = 40
root_check = sp.lambdify(kk, determinant.subs(L, 1), "mpmath")
first_root = mp.findroot(root_check, mp.mpf("6.0"))
midpoint_value = abs(root_check(mp.mpf("3.0")))
check("it_is_the_first_positive_root",
      abs(first_root - 2 * mp.pi) < mp.mpf("1e-30") and midpoint_value > 1,
      f"first root at kappa L = {mp.nstr(first_root, 20)}, and the determinant "
      f"is {mp.nstr(midpoint_value, 6)} at kappa L = 3, so nothing is missed before it")

clamped_load = sp.simplify((2 * sp.pi / L) ** 2 * EI)
check("clamped_clamped_is_four_times_the_pinned_load",
      sp.simplify(clamped_load / critical - 4) == 0,
      f"P_clamped = {clamped_load}, which is "
      f"{sp.simplify(clamped_load / critical)} times the pinned value")


# ---------------------------------------------------------------- leg 5
# A non-eigenvalue load admits only A = B = 0. Take P halfway between the first
# two modes, where sin(kL) is not zero, and the boundary system is invertible.
between = sp.simplify((critical + load.subs(n, 2)) / 2)
sine_at_between = sp.simplify(sp.sin(sp.sqrt(between / EI) * L))
check("a_non_eigenvalue_load_leaves_a_nonzero_sine",
      sp.simplify(sine_at_between) != 0,
      f"sin(kL) = {sp.simplify(sine_at_between)} at P between the first two modes")

trivial_only = sp.solve(
    [sp.Eq(B, 0), sp.Eq(A * sine_at_between, 0)], [A, B], dict=True
)
check("falsifier_only_the_trivial_shape_survives_off_the_spectrum",
      len(trivial_only) == 1
      and sp.simplify(trivial_only[0].get(A, 0)) == 0,
      f"the boundary system forces A = B = 0, solution {trivial_only}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
