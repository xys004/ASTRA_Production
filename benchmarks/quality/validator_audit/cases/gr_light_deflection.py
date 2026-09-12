"""General relativity deflects starlight by twice the Newtonian amount.

CLAIM: for a light ray with impact parameter b grazing a mass M, the Schwarzschild
null geodesic gives a deflection of 4 G M / (c^2 b) to first order in the field,
exactly twice the value obtained by treating light as a Newtonian particle. For
the Sun at grazing incidence this is 1.75 arcseconds.

Legs:
  1. orbit      -- the null-geodesic orbit equation d2u/dphi2 + u = 3 G M u^2/c^2
                   is solved perturbatively, and both the zeroth-order and the
                   first-order pieces are substituted back and required to
                   cancel at their own order;
  2. deflection -- the deflection is read off the asymptotes of that solution,
                   not quoted, by solving u = 0 for the incoming and outgoing
                   directions and taking the excess over pi;
  3. newtonian  -- the same impact parameter through the Newtonian hyperbola
                   gives exactly half, computed independently in the same units;
  4. numeric    -- the solar value comes out at 1.75 arcseconds using CODATA
                   constants, with the conversion done rather than asserted;
  5. falsifier  -- the Newtonian prediction and the relativistic one differ by a
                   factor the same comparison separates.
"""
import mpmath as mp
import sympy as sp

phi = sp.Symbol("phi", real=True)
b, G, M, c = sp.symbols("b G M c", positive=True)
eps = sp.Symbol("varepsilon", positive=True)      # bookkeeping order parameter

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# u = 1/r. The exact null orbit equation in Schwarzschild is
#     u'' + u = 3 G M u^2 / c^2.
# Write u = u0 + (GM/c^2) u1 and match order by order.
u0 = sp.sin(phi) / b
u1 = (1 + sp.cos(phi) ** 2) / b**2

homogeneous = sp.simplify(sp.diff(u0, phi, 2) + u0)
check("zeroth_order_is_a_straight_line", homogeneous == 0,
      f"u0'' + u0 = {homogeneous}, so u0 = sin(phi)/b is the undeflected ray")

# First order: matching the coefficient of GM/c^2 in u'' + u = 3 GM u^2/c^2
# leaves u1'' + u1 = 3 u0^2, with the field factor carried outside. That is what
# makes u1 the correct particular solution, and it is checked rather than
# assumed by substituting u1 back into its own equation.
first_order_lhs = sp.simplify(sp.diff(u1, phi, 2) + u1)
first_order_rhs = sp.simplify(3 * u0**2)
check("first_order_particular_solution_is_correct",
      sp.simplify(sp.expand_trig(first_order_lhs - first_order_rhs)) == 0,
      f"u1'' + u1 = {sp.simplify(first_order_lhs)} = 3 u0^2")

# And the combination solves the full equation up to terms of second order.
u_full = u0 + eps * u1
residual = sp.expand(
    sp.diff(u_full, phi, 2) + u_full - 3 * eps * u_full**2
)
first_order_residual = sp.simplify(sp.expand_trig(residual.coeff(eps, 1)))
check("residual_vanishes_at_first_order", first_order_residual == 0,
      f"coefficient of the order parameter = {first_order_residual}")


# ---------------------------------------------------------------- leg 2
# The ray comes from infinity (u = 0) and returns to infinity. Solve u = 0 for
# small phi: sin(phi) + (GM/c^2 b)(1 + cos^2 phi) = 0 gives phi = -2GM/(c^2 b)
# to first order, and by symmetry the same excess at the far end.
small = sp.Symbol("delta", real=True)
field = G * M / (c**2 * b)
asymptote = sp.series(
    sp.sin(small) + field * (1 + sp.cos(small) ** 2), small, 0, 2
).removeO()
delta_solution = sp.solve(sp.Eq(asymptote, 0), small)
check("asymptote_equation_has_one_small_root",
      len(delta_solution) == 1,
      f"u = 0 near phi = 0 gives delta = {delta_solution[0] if delta_solution else 'none'}")

delta = sp.simplify(delta_solution[0])
deflection = sp.simplify(-2 * delta)          # one excess at each end
check("deflection_is_four_GM_over_c2b",
      sp.simplify(deflection - 4 * G * M / (c**2 * b)) == 0,
      f"alpha = {deflection}")


# ---------------------------------------------------------------- leg 3
# Newtonian: a particle at speed c on a hyperbola with impact parameter b is
# deflected by 2GM/(c^2 b). Derived here from the standard scattering formula
# tan(alpha/2) = GM/(b v^2), expanded to first order, not quoted.
newtonian_exact = 2 * sp.atan(G * M / (b * c**2))
newtonian_first_order = sp.simplify(
    sp.series(newtonian_exact, G, 0, 2).removeO()
)
check("newtonian_deflection_is_two_GM_over_c2b",
      sp.simplify(newtonian_first_order - 2 * G * M / (c**2 * b)) == 0,
      f"alpha_N = {newtonian_first_order}")

ratio = sp.simplify(deflection / newtonian_first_order)
check("relativity_gives_exactly_twice_the_newtonian_value",
      sp.simplify(ratio - 2) == 0,
      f"alpha / alpha_N = {ratio}")


# ---------------------------------------------------------------- leg 4
mp.mp.dps = 30
G_SI = mp.mpf("6.67430e-11")          # m^3 kg^-1 s^-2, CODATA 2018
M_SUN = mp.mpf("1.98892e30")          # kg
R_SUN = mp.mpf("6.957e8")             # m, nominal solar radius
C_SI = mp.mpf("299792458")            # m/s, exact

alpha_rad = 4 * G_SI * M_SUN / (C_SI**2 * R_SUN)
# Convert to arcseconds rather than asserting the number: one radian is
# 180/pi degrees and one degree is 3600 arcseconds.
alpha_arcsec = alpha_rad * (180 / mp.pi) * 3600
check("solar_deflection_is_about_1_75_arcseconds",
      abs(alpha_arcsec - mp.mpf("1.75")) < mp.mpf("0.01"),
      f"alpha = {mp.nstr(alpha_arcsec, 6)} arcsec at grazing incidence")

# The conversion itself must be right, checked against the definition.
check("arcsecond_conversion_is_exact",
      abs(mp.mpf(1) * (180 / mp.pi) * 3600 - mp.mpf("206264.806247096355")) < mp.mpf("1e-9"),
      "one radian = 206264.8062 arcsec")


# ---------------------------------------------------------------- leg 5
# The two predictions must be separable by the same numerical comparison, or
# the 1911 and 1915 values could not have been distinguished by observation.
newtonian_arcsec = alpha_arcsec / 2
check("falsifier_separates_the_two_predictions",
      abs(alpha_arcsec - newtonian_arcsec) > mp.mpf("0.5"),
      f"relativistic {mp.nstr(alpha_arcsec, 4)} against Newtonian "
      f"{mp.nstr(newtonian_arcsec, 4)} arcsec, a gap far above the 0.01 tolerance")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
