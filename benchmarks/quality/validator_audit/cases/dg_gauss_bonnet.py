"""Total curvature is topological, and forgetting the boundary term breaks it.

CLAIM: for a closed surface the integral of the Gaussian curvature is 2 pi times
the Euler characteristic. On a sphere the integral is 4 pi and the radius cancels
entirely; on a triaxial ellipsoid, where the curvature varies by more than an
order of magnitude, the integral is still 4 pi; on a torus the integrand reduces
to cos(v) du dv and the positive outer half cancels the negative inner half
exactly; and on a surface WITH boundary the same integral is not 2 pi chi at all
until the geodesic curvature of the edge is added, at which point it is.

The last leg is the reason for the case. The closed-surface form of the theorem
is the one everyone remembers, and applying it to a cap gives a wrong answer that
looks perfectly reasonable.

Legs:
  1. sphere    -- the curvature and the area element are computed from the
                  fundamental forms, and the radius cancels out of the total;
  2. ellipsoid -- the curvature is shown to vary, and the integral is still 4 pi,
                  with the quadrature shown to converge rather than assumed to;
  3. torus     -- the integrand collapses to cos(v) du dv, so the total is zero
                  by an exact integration rather than a numerical near-miss;
  4. halves    -- the outer and inner halves contribute plus and minus 4 pi, so
                  the zero is a cancellation and not an absence of curvature;
  5. falsifier -- a spherical cap gives 2 pi (1 - cos a), which is not 2 pi chi;
  6. boundary  -- the geodesic curvature term, derived through Meusnier, supplies
                  exactly the missing 2 pi cos a.
"""
import math

import numpy as np
import sympy as sp

u, v = sp.symbols("u v", real=True)
R, r, rho = sp.symbols("R r rho", positive=True)
alpha = sp.Symbol("alpha", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def fundamental_forms(position):
    """Gaussian curvature and area element of a parametrised surface.

    Both come from the first and second fundamental forms, so a wrong
    parametrisation shows up in the curvature rather than being absorbed.
    """
    first = sp.diff(position, u)
    second = sp.diff(position, v)
    normal = first.cross(second)
    scale = sp.sqrt(sp.simplify(normal.dot(normal)))
    unit = normal / scale

    E = sp.simplify(first.dot(first))
    F = sp.simplify(first.dot(second))
    G = sp.simplify(second.dot(second))
    L = sp.simplify(sp.diff(position, u, 2).dot(unit))
    M = sp.simplify(sp.diff(position, u, v).dot(unit))
    N = sp.simplify(sp.diff(position, v, 2).dot(unit))

    curvature = sp.simplify((L * N - M ** 2) / (E * G - F ** 2))
    area_element = sp.simplify(sp.sqrt(E * G - F ** 2))
    return curvature, area_element


# ---------------------------------------------------------------- leg 1
sphere = sp.Matrix([
    rho * sp.sin(u) * sp.cos(v),
    rho * sp.sin(u) * sp.sin(v),
    rho * sp.cos(u),
])
sphere_curvature, sphere_area_raw = fundamental_forms(sphere)
check("the_sphere_has_constant_curvature_one_over_the_radius_squared",
      sp.simplify(sphere_curvature - 1 / rho ** 2) == 0,
      f"K = {sphere_curvature}")

# The area element arrives as rho^2 times the absolute value of sin(u), since a
# square root of a square is what it is. The chart runs over u in (0, pi),
# where the sine is not negative, so the positive branch is the right one.
# Stating the chart domain and checking the branch beats hoping a simplifier
# guesses it, and over a partial range it does not guess: it returns a
# Piecewise that no later step can use.
sphere_area = rho ** 2 * sp.sin(u)
check("the_positive_branch_of_the_sphere_area_element_is_the_right_one",
      sp.simplify(sphere_area ** 2 - sphere_area_raw ** 2) == 0,
      f"the assumed element {sphere_area} squares to the same first fundamental "
      f"form as {sphere_area_raw} on the chart u in (0, pi)")

total_area = sp.simplify(sp.integrate(sphere_area, (u, 0, sp.pi), (v, 0, 2 * sp.pi)))
check("the_area_element_integrates_to_the_surface_area",
      sp.simplify(total_area - 4 * sp.pi * rho ** 2) == 0,
      f"area = {total_area}")

sphere_total = sp.simplify(
    sp.integrate(sphere_curvature * sphere_area, (u, 0, sp.pi), (v, 0, 2 * sp.pi))
)
check("the_total_curvature_of_a_sphere_is_four_pi_whatever_its_radius",
      sp.simplify(sphere_total - 4 * sp.pi) == 0 and rho not in sphere_total.free_symbols,
      f"integral of K dA = {sphere_total}, with the radius gone from the answer")

EULER_SPHERE = 2
check("and_that_is_two_pi_times_the_euler_characteristic",
      sp.simplify(sphere_total - 2 * sp.pi * EULER_SPHERE) == 0,
      f"2 pi chi = {2 * sp.pi * EULER_SPHERE} for chi = {EULER_SPHERE}")


# ---------------------------------------------------------------- leg 2
AXES = (1.0, 1.4, 0.7)
ellipsoid = sp.Matrix([
    AXES[0] * sp.sin(u) * sp.cos(v),
    AXES[1] * sp.sin(u) * sp.sin(v),
    AXES[2] * sp.cos(u),
])
ellipsoid_curvature, ellipsoid_area = fundamental_forms(ellipsoid)
curvature_at = sp.lambdify((u, v), ellipsoid_curvature, "numpy")
integrand_at = sp.lambdify((u, v), ellipsoid_curvature * ellipsoid_area, "numpy")

probe_u, probe_v = np.meshgrid(
    np.linspace(0.05, math.pi - 0.05, 60), np.linspace(0.0, 2 * math.pi, 60)
)
samples = curvature_at(probe_u, probe_v)
spread = float(np.max(samples) / np.min(samples))
check("the_ellipsoid_curvature_really_does_vary",
      bool(spread > 10.0),
      f"K ranges from {np.min(samples):.4f} to {np.max(samples):.4f}, a factor "
      f"of {spread:.1f}, so a constant-curvature argument cannot apply")


def quadrature(nodes):
    """Tensor Gauss-Legendre over the parameter rectangle."""
    points, weights = np.polynomial.legendre.leggauss(nodes)
    us = 0.5 * math.pi * (points + 1.0)
    vs = math.pi * (points + 1.0)
    grid_u, grid_v = np.meshgrid(us, vs, indexing="ij")
    values = integrand_at(grid_u, grid_v)
    return float(0.5 * math.pi * math.pi * (weights @ values @ weights))


coarse, fine = quadrature(40), quadrature(80)
check("the_total_curvature_of_the_ellipsoid_is_also_four_pi",
      bool(abs(fine - 4 * math.pi) < 1e-9),
      f"integral = {fine:.12f} against 4 pi = {4 * math.pi:.12f}, apart by "
      f"{abs(fine - 4 * math.pi):.3e}")

check("and_the_quadrature_is_converged_rather_than_merely_close",
      bool(abs(fine - 4 * math.pi) < abs(coarse - 4 * math.pi) / 10),
      f"the error falls from {abs(coarse - 4 * math.pi):.3e} at 40 nodes to "
      f"{abs(fine - 4 * math.pi):.3e} at 80, so the agreement is the limit and "
      "not a coincidence of the grid")


# ---------------------------------------------------------------- leg 3
torus = sp.Matrix([
    (R + r * sp.cos(v)) * sp.cos(u),
    (R + r * sp.cos(v)) * sp.sin(u),
    r * sp.sin(v),
])
torus_curvature, torus_area_raw = fundamental_forms(torus)
check("the_torus_curvature_is_the_familiar_cosine_over_the_tube",
      sp.simplify(torus_curvature - sp.cos(v) / (r * (R + r * sp.cos(v)))) == 0,
      f"K = {sp.simplify(torus_curvature)}")

# The area element arrives as r times the absolute value of the bracket, and no
# simplifier can drop those bars without knowing that the ring radius exceeds
# the tube radius. That is the embedding condition for a torus, so it is stated
# here as an assumption and the chosen branch is then checked against the form
# it came from. Leaving it to simplify would be leaving the topology to luck.
torus_area = r * (R + r * sp.cos(v))
check("the_positive_branch_of_the_area_element_is_the_right_one",
      sp.simplify(torus_area ** 2 - torus_area_raw ** 2) == 0,
      f"the assumed element {torus_area} squares to the same first fundamental "
      f"form as {torus_area_raw}, and R > r makes it the positive branch")

integrand = sp.simplify(torus_curvature * torus_area)
check("so_the_integrand_collapses_to_the_cosine_alone",
      sp.simplify(integrand - sp.cos(v)) == 0,
      f"K dA = {integrand} du dv, with both radii cancelling")

torus_total = sp.simplify(
    sp.integrate(integrand, (u, 0, 2 * sp.pi), (v, 0, 2 * sp.pi))
)
EULER_TORUS = 0
check("the_total_curvature_of_a_torus_is_exactly_zero",
      torus_total == 0 and sp.simplify(torus_total - 2 * sp.pi * EULER_TORUS) == 0,
      f"integral of K dA = {torus_total}, matching 2 pi chi for chi = {EULER_TORUS}")


# ---------------------------------------------------------------- leg 4
outer = sp.simplify(
    sp.integrate(integrand, (u, 0, 2 * sp.pi), (v, -sp.pi / 2, sp.pi / 2))
)
inner = sp.simplify(
    sp.integrate(integrand, (u, 0, 2 * sp.pi), (v, sp.pi / 2, 3 * sp.pi / 2))
)
check("the_outer_half_carries_positive_four_pi",
      sp.simplify(outer - 4 * sp.pi) == 0,
      f"outer contribution {outer}")
check("the_inner_half_carries_the_opposite",
      sp.simplify(inner + 4 * sp.pi) == 0 and sp.simplify(outer + inner) == 0,
      f"inner contribution {inner}, and the two sum to {sp.simplify(outer + inner)}")


# ---------------------------------------------------------------- leg 5
# A cap of half-angle alpha on the unit sphere. Its Euler characteristic is that
# of a disc, so the closed-surface statement would demand 2 pi.
cap_total = sp.simplify(
    sp.integrate(sphere_curvature * sphere_area, (u, 0, alpha), (v, 0, 2 * sp.pi))
)
check("the_cap_integral_is_two_pi_one_minus_cosine",
      sp.simplify(cap_total - 2 * sp.pi * (1 - sp.cos(alpha))) == 0,
      f"integral over the cap = {cap_total}")

EULER_DISC = 1
shortfall = sp.simplify(2 * sp.pi * EULER_DISC - cap_total)
check("falsifier_which_is_not_two_pi_chi_for_a_disc",
      sp.simplify(shortfall - 2 * sp.pi * sp.cos(alpha)) == 0
      and sp.simplify(shortfall.subs(alpha, sp.pi / 3)) != 0,
      f"the closed-surface form is short by {shortfall}, which is "
      f"{sp.simplify(shortfall.subs(alpha, sp.pi / 3))} at alpha = pi/3")


# ---------------------------------------------------------------- leg 6
# The geodesic curvature of the boundary circle, from Meusnier: the curve's own
# curvature and the surface's normal curvature are the two legs of a right
# triangle whose third side is the geodesic curvature.
curve_curvature = 1 / (rho * sp.sin(alpha))
normal_curvature = 1 / rho
magnitude = sp.simplify(curve_curvature ** 2 - normal_curvature ** 2)

# Meusnier fixes the MAGNITUDE; the sign comes from the orientation of the
# boundary, and a cap inside the upper hemisphere has alpha below pi/2, where
# the cosine is positive. That restriction is part of the claim, so it is
# written down and the branch is checked, exactly as on the torus.
geodesic = sp.cos(alpha) / (rho * sp.sin(alpha))
check("the_geodesic_curvature_of_the_boundary_follows_from_meusnier",
      sp.simplify(geodesic ** 2 - magnitude) == 0,
      f"k^2 - k_n^2 = {magnitude}, whose positive root for alpha below pi/2 "
      f"is k_g = {geodesic}")

boundary_length = sp.simplify(2 * sp.pi * rho * sp.sin(alpha))
boundary_term = sp.simplify(geodesic * boundary_length)
check("the_boundary_term_is_two_pi_cosine_alpha",
      sp.simplify(boundary_term - 2 * sp.pi * sp.cos(alpha)) == 0,
      f"the line integral of k_g is {boundary_term}, with the radius cancelling "
      "again")

restored = sp.simplify(cap_total.subs(rho, 1) + boundary_term.subs(rho, 1))
check("adding_it_restores_the_theorem_for_every_cap_angle",
      sp.simplify(restored - 2 * sp.pi * EULER_DISC) == 0
      and alpha not in restored.free_symbols,
      f"the area term plus the boundary term is {restored}, independent of "
      "alpha, which is 2 pi chi for a disc")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
