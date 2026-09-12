"""A band from hopping, and an effective mass that changes sign at the edge.

CLAIM: on a chain with nearest-neighbour hopping the Bloch state is an
eigenvector and the energy is e0 - 2 t cos(k a), which a finite ring reproduces
eigenvalue by eigenvalue; the band is 4 t wide, with the extremes located by
solving rather than read off, and periodic with the zone as its period; near the
bottom the dispersion is quadratic with an effective mass hbar^2 / (2 t a^2);
near the top the same expansion returns MINUS that, so a carrier there responds
to a force the wrong way; and the density of states diverges at both edges while
still integrating to the number of states.

The sign change is the point. The parabolic approximation degrades smoothly
across the zone, which is easy to bound and easy to forget, and then at the far
edge it stops being an approximation at all.

Legs:
  1. bloch     -- the Bloch state satisfies the hopping equation, and a finite
                  ring gives the same spectrum numerically;
  2. width     -- the extremes are solved for and the width is four t;
  3. zone      -- the energy repeats with the zone, and a ring of N sites carries
                  exactly N distinct states inside one;
  4. mass      -- the curvature at the bottom gives the effective mass, and the
                  same construction at the top gives its negative;
  5. falsifier -- the parabolic error is computed across the zone, passing ten
                  per cent well before the boundary and reversing sign there;
  6. vanhove   -- the density of states diverges at the edges as an inverse
                  square root and its integral over the band is still finite.
"""
import math

import numpy as np
import sympy as sp

k, a, t, e0, hbar = sp.symbols("k a t e_0 hbar", positive=True)
site = sp.Symbol("n", integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# The hopping equation applied to a Bloch amplitude, with the amplitude divided
# out afterwards: what is left is the energy, and it is obtained rather than
# written down.
amplitude = sp.exp(sp.I * k * site * a)
applied = sp.simplify(
    e0 * amplitude
    - t * (amplitude.subs(site, site - 1) + amplitude.subs(site, site + 1))
)
dispersion = sp.simplify(sp.expand(applied / amplitude).rewrite(sp.cos))
check("the_bloch_state_is_an_eigenvector_of_the_hopping_equation",
      sp.simplify(dispersion - (e0 - 2 * t * sp.cos(k * a))) == 0,
      f"dividing out the amplitude leaves E(k) = {dispersion}, independent of "
      "the site index, which is what makes it an eigenvalue")

SITES, HOP, ONSITE, SPACING = 12, 1.3, 0.4, 1.0
ring = np.zeros((SITES, SITES))
for index in range(SITES):
    ring[index, index] = ONSITE
    ring[index, (index + 1) % SITES] = -HOP
    ring[index, (index - 1) % SITES] = -HOP
numeric = np.sort(np.linalg.eigvalsh(ring))
predicted = np.sort([
    ONSITE - 2 * HOP * math.cos(2 * math.pi * m / SITES)
    for m in range(SITES)
])
check("a_finite_ring_reproduces_that_spectrum_eigenvalue_by_eigenvalue",
      bool(np.max(np.abs(numeric - predicted)) < 1e-12),
      f"the {SITES} eigenvalues of the ring match the formula at the allowed "
      f"wavevectors to {np.max(np.abs(numeric - predicted)):.3e}")


# ---------------------------------------------------------------- leg 2
energy = e0 - 2 * t * sp.cos(k * a)
stationary = sp.solve(sp.Eq(sp.diff(energy, k), 0), k)
inside = [value for value in stationary
          if sp.simplify(value) == 0 or sp.simplify(value - sp.pi / a) == 0]
check("the_extremes_sit_at_the_zone_centre_and_its_boundary",
      len(inside) >= 1 and sp.simplify(sp.diff(energy, k).subs(k, 0)) == 0
      and sp.simplify(sp.diff(energy, k).subs(k, sp.pi / a)) == 0,
      f"dE/dk vanishes at {stationary}, and both the centre and the boundary "
      "are among them")

bottom = sp.simplify(energy.subs(k, 0))
top = sp.simplify(energy.subs(k, sp.pi / a))
check("the_band_is_four_hoppings_wide",
      sp.simplify(top - bottom - 4 * t) == 0,
      f"from {bottom} at the centre to {top} at the boundary, a width of "
      f"{sp.simplify(top - bottom)}")


# ---------------------------------------------------------------- leg 3
shifted = sp.simplify(energy.subs(k, k + 2 * sp.pi / a) - energy)
check("the_energy_repeats_with_the_zone",
      shifted == 0,
      f"E(k + 2 pi / a) - E(k) = {shifted}, so states outside one zone are the "
      "same states relabelled")

# Counted in units of pi/a as exact rationals. In floating point the fold is
# not exact: pi modulo pi comes back as two times ten to the minus thirteen
# rather than zero, so distinct-looking values survive a fold that should have
# collapsed them, and the count would be right for the wrong reason.
wavevectors = {sp.Rational(2 * m, SITES) % 2 for m in range(SITES)}
check("and_a_ring_of_that_many_sites_carries_exactly_that_many_states",
      len(wavevectors) == SITES,
      f"the {SITES} allowed wavevectors are distinct inside one zone, so the "
      "count of states is the count of sites and nothing is double counted")


# ---------------------------------------------------------------- leg 4
# The effective mass is read off the curvature, not assumed: the second
# derivative is taken and the standard definition inverted for it.
mass = sp.Symbol("m_star", real=True)
curvature_bottom = sp.simplify(sp.diff(energy, k, 2).subs(k, 0))
solved_bottom = sp.solve(sp.Eq(hbar ** 2 / mass, curvature_bottom), mass)
# A curvature that vanishes leaves no effective mass at all, and the nan
# carries that through the parabola below instead of raising an index error
# three legs later.
mass_bottom = sp.simplify(sum(solved_bottom)) if solved_bottom else sp.nan
check("the_curvature_at_the_bottom_gives_the_usual_effective_mass",
      len(solved_bottom) == 1
      and sp.simplify(mass_bottom - hbar ** 2 / (2 * t * a ** 2)) == 0,
      f"the second derivative is {curvature_bottom}, so m* = {mass_bottom}")

curvature_top = sp.simplify(sp.diff(energy, k, 2).subs(k, sp.pi / a))
solved_top = sp.solve(sp.Eq(hbar ** 2 / mass, curvature_top), mass)
mass_top = sp.simplify(sum(solved_top)) if solved_top else sp.nan
check("falsifier_the_same_construction_at_the_top_returns_a_negative_mass",
      len(solved_top) == 1
      and sp.simplify(mass_top + hbar ** 2 / (2 * t * a ** 2)) == 0
      and mass_top.subs({hbar: 1, t: 1, a: 1}).is_negative is True,
      f"the curvature is {curvature_top} there, giving m* = {mass_top}, so a "
      "carrier at the top accelerates against the force")


# ---------------------------------------------------------------- leg 5
parabolic = sp.simplify(bottom + hbar ** 2 * k ** 2 / (2 * mass_bottom))
# The agreement is stated through the leading term of the difference, not
# through a series compared with itself: the parabola is right to second order
# exactly because the first surviving term is the fourth, and naming that term
# says how fast the approximation fails as well as that it holds.
leading = sp.simplify(sp.series(energy - parabolic, k, 0, 6).removeO())
check("the_parabola_agrees_with_the_band_to_second_order_at_the_centre",
      sp.limit((energy - parabolic) / k ** 2, k, 0) == 0
      and sp.simplify(leading + a ** 4 * k ** 4 * t / 12) == 0,
      f"the difference vanishes faster than k squared, its first surviving term "
      f"being {leading}, so the error grows as the fourth power")


def relative_error(fraction):
    """How far the parabola is from the band, at this fraction of the zone."""
    place = fraction * math.pi
    exact = ONSITE - 2 * HOP * math.cos(place)
    approximate = ONSITE - 2 * HOP + HOP * place ** 2
    return abs(approximate - exact) / abs(exact - (ONSITE - 2 * HOP))


crossings = [fraction for fraction in np.linspace(0.05, 1.0, 200)
             if relative_error(fraction) > 0.10]
first_crossing = crossings[0] if crossings else math.nan
check("the_parabolic_error_passes_ten_per_cent_well_inside_the_zone",
      len(crossings) > 0 and bool(first_crossing < 0.6),
      f"it first exceeds a tenth at {first_crossing:.3f} of the way to the "
      f"boundary, where the band has only risen "
      f"{100 * (1 - math.cos(first_crossing * math.pi)) / 2:.0f} per cent of its width")

check("and_at_the_boundary_it_is_not_an_approximation_at_all",
      bool(np.sign(float(curvature_bottom.subs({t: HOP, a: SPACING})))
           != np.sign(float(curvature_top.subs({t: HOP, a: SPACING})))),
      f"the curvature is {float(curvature_bottom.subs({t: HOP, a: SPACING})):+.3f} "
      f"at the centre and {float(curvature_top.subs({t: HOP, a: SPACING})):+.3f} at "
      "the boundary, so no error bound on a parabola can cover both")


# ---------------------------------------------------------------- leg 6
# The density of states is the inverse of the group velocity. It diverges at the
# edges, and the integral over the band still converges, which is the whole
# content of an inverse square root singularity.
velocity = sp.simplify(sp.diff(energy, k))
band = sp.Symbol("E", real=True)
inverse_velocity = sp.simplify(
    1 / velocity.subs(k, sp.acos((e0 - band) / (2 * t)) / a)
)
check("the_density_of_states_is_an_inverse_square_root_at_the_edges",
      sp.simplify(inverse_velocity ** 2
                  - 1 / (4 * t ** 2 * a ** 2 - (band - e0) ** 2 * a ** 2)) == 0,
      f"one over the group velocity is {inverse_velocity}, which blows up "
      "exactly where the band ends")

# Measured in units of the band: the substitution E = e0 + 2 t u turns the
# measure into 2 t du while the integrand carries one over 2 t, so the offset
# and the hopping cancel. That cancellation is checked rather than assumed,
# and only then is a clean integral evaluated; sympy will not do the symbolic
# one at all, returning a Piecewise nothing downstream can use.
scaled = sp.Symbol("u", real=True)
in_band_units = sp.simplify(
    (1 / sp.sqrt(4 * t ** 2 - (band - e0) ** 2)).subs(band, e0 + 2 * t * scaled)
    * (2 * t)
)
check("the_band_integral_is_free_of_the_offset_and_the_hopping",
      sp.simplify(in_band_units - 1 / sp.sqrt(1 - scaled ** 2)) == 0,
      f"in units of the half width the integrand is {in_band_units}, with both "
      "parameters gone")

total = sp.integrate(1 / sp.sqrt(1 - scaled ** 2), (scaled, -1, 1))
check("and_its_integral_across_the_band_is_finite",
      sp.simplify(total - sp.pi) == 0,
      f"the integral comes to {total}, so a density that diverges at both "
      "edges still counts a finite number of states")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
