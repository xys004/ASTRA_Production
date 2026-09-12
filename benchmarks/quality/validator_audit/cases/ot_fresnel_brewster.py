"""Fresnel coefficients come from the boundary conditions, and R + T = 1 needs
the obliquity factor.

CLAIM: continuity of the tangential fields across a dielectric interface fixes
the reflection and transmission amplitudes; the p-amplitude vanishes at
tan(theta) = n2/n1; the reflectance and transmittance sum to one only when the
transmitted power carries the factor n2 cos(theta_t) / (n1 cos(theta_i)); and the
same formulas, continued past the critical angle, return unit modulus, which is
total internal reflection.

The obliquity factor is the reason for the case. Squaring the amplitudes and
adding them is the usual mistake, it looks like energy conservation, and here the
deficit it produces is computed rather than described.

Legs:
  1. boundaries -- the two polarisations are each solved as a linear system in
                   the amplitudes, so the Fresnel formulas are an output;
  2. brewster   -- the vanishing of the p-amplitude is SOLVED for the angle and
                   comes out as tan(theta) = n2/n1;
  3. energy     -- R + T = 1 holds identically with the obliquity factor, and the
                   deficit without it is exhibited as a number;
  4. normal     -- at normal incidence both polarisations give the same modulus,
                   and the familiar four percent falls out for glass;
  5. numeric    -- across a sweep of angles the sum stays one to machine
                   precision, and a bisection finds the Brewster angle without
                   using the formula;
  6. falsifier  -- past the critical angle the same expressions have unit
                   modulus and zero transmitted power, so the regime change is a
                   prediction of the formulas rather than a separate rule.
"""
import cmath
import math

import sympy as sp

n1, n2 = sp.symbols("n_1 n_2", positive=True)
cos_i, cos_t = sp.symbols("cos_i cos_t", positive=True)
amplitude_r, amplitude_t = sp.symbols("r t", real=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def solved_pair(system):
    """Solve a two-by-two boundary system, or return nan for both amplitudes."""
    answers = sp.solve(system, [amplitude_r, amplitude_t], dict=True)
    if len(answers) != 1:
        return sp.nan, sp.nan
    return (sp.simplify(answers[0][amplitude_r]),
            sp.simplify(answers[0][amplitude_t]))


# ---------------------------------------------------------------- leg 1
# s polarisation: the electric field is tangential, so its amplitudes add; the
# magnetic field contributes n cos(theta) times the amplitude to the tangential
# component, with the reflected wave travelling the other way.
s_system = [
    sp.Eq(1 + amplitude_r, amplitude_t),
    sp.Eq(n1 * cos_i * (1 - amplitude_r), n2 * cos_t * amplitude_t),
]
r_s, t_s = solved_pair(s_system)
check("the_s_reflection_amplitude_follows_from_the_boundary_conditions",
      sp.simplify(r_s - (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)) == 0,
      f"r_s = {r_s}")
check("the_s_transmission_amplitude_follows_with_it",
      sp.simplify(t_s - 2 * n1 * cos_i / (n1 * cos_i + n2 * cos_t)) == 0,
      f"t_s = {t_s}")

# p polarisation: now the magnetic field is tangential and the electric field
# contributes only its cos(theta) projection.
p_system = [
    sp.Eq(cos_i * (1 - amplitude_r), cos_t * amplitude_t),
    sp.Eq(n1 * (1 + amplitude_r), n2 * amplitude_t),
]
r_p, t_p = solved_pair(p_system)
check("the_p_reflection_amplitude_follows_from_the_boundary_conditions",
      sp.simplify(r_p - (n2 * cos_i - n1 * cos_t) / (n2 * cos_i + n1 * cos_t)) == 0,
      f"r_p = {r_p}")
check("the_p_transmission_amplitude_follows_with_it",
      sp.simplify(t_p - 2 * n1 * cos_i / (n2 * cos_i + n1 * cos_t)) == 0,
      f"t_p = {t_p}")


# ---------------------------------------------------------------- leg 2
# Brewster: ask where r_p vanishes, in terms of the tangent of the angle, with
# Snell used to express the transmitted cosine. Nothing is substituted in.
tangent = sp.Symbol("tan_i", positive=True)
cosine_i = 1 / sp.sqrt(1 + tangent ** 2)
sine_i = tangent / sp.sqrt(1 + tangent ** 2)
cosine_t = sp.sqrt(1 - (n1 * sine_i / n2) ** 2)

p_numerator = sp.simplify(
    sp.numer(sp.together(r_p)).subs({cos_i: cosine_i, cos_t: cosine_t})
)
roots = sp.solve(sp.Eq(p_numerator, 0), tangent)
check("the_p_amplitude_vanishes_at_one_angle",
      len(roots) == 1,
      f"r_p = 0 at tan(theta) = {roots or 'nothing'}")

brewster_tangent = sp.simplify(sum(roots)) if roots else sp.nan
check("that_angle_is_the_brewster_angle",
      sp.simplify(brewster_tangent - n2 / n1) == 0,
      f"tan(theta_B) = {brewster_tangent}")

# The s amplitude has no such zero, which is why the effect polarises light.
s_numerator = sp.simplify(
    sp.numer(sp.together(r_s)).subs({cos_i: cosine_i, cos_t: cosine_t})
)
s_roots = sp.solve(sp.Eq(s_numerator.subs({n1: 1, n2: sp.Rational(3, 2)}), 0), tangent)
check("the_s_amplitude_has_no_such_zero",
      len(s_roots) == 0,
      f"r_s = 0 has solutions {s_roots} for n_1 = 1, n_2 = 3/2")


# ---------------------------------------------------------------- leg 3
obliquity = n2 * cos_t / (n1 * cos_i)
energy_s = sp.simplify(r_s ** 2 + obliquity * t_s ** 2)
check("the_s_polarisation_conserves_energy_with_the_obliquity_factor",
      sp.simplify(energy_s - 1) == 0,
      f"R_s + T_s = {energy_s}")

energy_p = sp.simplify(r_p ** 2 + obliquity * t_p ** 2)
check("the_p_polarisation_conserves_energy_with_the_obliquity_factor",
      sp.simplify(energy_p - 1) == 0,
      f"R_p + T_p = {energy_p}")

# Without the factor the sum is not one, and the gap is not small. Exhibited as
# a number so that the claim is checkable rather than merely stated.
naive = sp.simplify(r_s ** 2 + t_s ** 2)
GLASS = {n1: 1, n2: sp.Rational(3, 2)}
angle_sample = sp.pi / 4
naive_at_forty_five = float(
    naive.subs(GLASS).subs({
        cos_i: sp.cos(angle_sample),
        cos_t: sp.sqrt(1 - (sp.sin(angle_sample) / sp.Rational(3, 2)) ** 2),
    })
)
check("dropping_the_obliquity_factor_breaks_the_sum",
      abs(naive_at_forty_five - 1) > 0.1,
      f"squaring the amplitudes and adding gives {naive_at_forty_five:.6f} at "
      "forty-five degrees into glass, not 1")


# ---------------------------------------------------------------- leg 4
straight = {cos_i: 1, cos_t: 1}
r_s_normal = sp.simplify(r_s.subs(straight))
r_p_normal = sp.simplify(r_p.subs(straight))
check("at_normal_incidence_the_two_polarisations_have_the_same_modulus",
      sp.simplify(r_s_normal ** 2 - r_p_normal ** 2) == 0,
      f"r_s = {r_s_normal} and r_p = {r_p_normal}, differing only in the sign "
      "convention for the p direction")

glass_reflectance = float((r_s_normal ** 2).subs(GLASS))
check("glass_reflects_four_percent_at_normal_incidence",
      abs(glass_reflectance - 0.04) < 5e-4,
      f"R = {glass_reflectance:.6f} for n_2/n_1 = 1.5")


# ---------------------------------------------------------------- leg 5
def amplitudes(index_in, index_out, angle):
    """Fresnel amplitudes, written so they survive past the critical angle."""
    sine_out = index_in * math.sin(angle) / index_out
    cosine_out = cmath.sqrt(1 - sine_out ** 2)
    cosine_in = math.cos(angle)
    return {
        "r_s": ((index_in * cosine_in - index_out * cosine_out)
                / (index_in * cosine_in + index_out * cosine_out)),
        "r_p": ((index_out * cosine_in - index_in * cosine_out)
                / (index_out * cosine_in + index_in * cosine_out)),
        "t_s": (2 * index_in * cosine_in
                / (index_in * cosine_in + index_out * cosine_out)),
        "t_p": (2 * index_in * cosine_in
                / (index_out * cosine_in + index_in * cosine_out)),
        "cos_in": cosine_in,
        "cos_out": cosine_out,
    }


def powers(index_in, index_out, angle, polarisation):
    values = amplitudes(index_in, index_out, angle)
    reflected = abs(values[f"r_{polarisation}"]) ** 2
    carried = (index_out * values["cos_out"]).real / (index_in * values["cos_in"])
    transmitted = carried * abs(values[f"t_{polarisation}"]) ** 2
    return reflected, transmitted


IN, OUT = 1.0, 1.5
sweep = [math.radians(degrees) for degrees in range(1, 90)]
worst = max(
    abs(sum(powers(IN, OUT, angle, polarisation)) - 1.0)
    for angle in sweep for polarisation in ("s", "p")
)
check("energy_balances_at_every_angle_in_the_sweep",
      worst < 1e-14,
      f"largest departure of R + T from one over {len(sweep)} angles and both "
      f"polarisations is {worst:.3e}")

# Locate the Brewster angle by bisection on the sign of r_p, which never
# consults the formula derived above.
low, high = math.radians(30.0), math.radians(80.0)
for _ in range(200):
    middle = (low + high) / 2
    if (amplitudes(IN, OUT, low)["r_p"].real
            * amplitudes(IN, OUT, middle)["r_p"].real) <= 0:
        high = middle
    else:
        low = middle
located = (low + high) / 2
predicted = math.atan(OUT / IN)
check("a_bisection_finds_the_brewster_angle_without_the_formula",
      abs(located - predicted) < 1e-12,
      f"bisection gave {math.degrees(located):.9f} degrees, the formula "
      f"arctan(n_2/n_1) gives {math.degrees(predicted):.9f}")

separations = [
    powers(IN, OUT, angle, "s")[0] - powers(IN, OUT, angle, "p")[0]
    for angle in sweep
]
check("the_s_polarisation_always_reflects_at_least_as_much",
      min(separations) >= 0,
      f"smallest R_s - R_p over the sweep is {min(separations):.6e}, reached "
      "near normal incidence where the two coincide")


# ---------------------------------------------------------------- leg 6
# Going the other way, from glass into air, the transmitted cosine turns
# imaginary above a critical angle. The formulas are not patched for it.
DENSE, RARE = 1.5, 1.0


def transmitted_sine(index_in, index_out, angle):
    """Snell's sine on the far side, which is what exceeds one past critical."""
    return index_in * math.sin(angle) / index_out


# Located by bisection on Snell rather than by taking the arcsine of n_2/n_1:
# solving for the sine and then inverting it would compare a formula with
# itself, and the comparison against the closed form below would mean nothing.
low, high = 0.0, math.pi / 2
for _ in range(200):
    middle = (low + high) / 2
    if transmitted_sine(DENSE, RARE, middle) < 1.0:
        low = middle
    else:
        high = middle
critical = (low + high) / 2
check("the_critical_angle_is_where_the_transmitted_sine_reaches_one",
      abs(transmitted_sine(DENSE, RARE, critical) - 1.0) < 1e-12,
      f"at {math.degrees(critical):.6f} degrees Snell gives sin(theta_t) = "
      f"{transmitted_sine(DENSE, RARE, critical):.12f}")
check("the_located_angle_agrees_with_the_closed_form",
      abs(critical - math.asin(RARE / DENSE)) < 1e-12,
      f"bisection gave {math.degrees(critical):.9f} degrees, arcsin(n_2/n_1) "
      f"gives {math.degrees(math.asin(RARE / DENSE)):.9f}")

above = amplitudes(DENSE, RARE, critical + math.radians(8.0))
modulus_above = abs(above["r_s"]) ** 2
check("falsifier_above_the_critical_angle_the_modulus_is_exactly_one",
      abs(modulus_above - 1.0) < 1e-15,
      f"|r_s|^2 = {modulus_above:.15f} eight degrees past the critical angle, "
      f"with cos(theta_t) = {above['cos_out']:.6f}, purely imaginary")

reflected_above, transmitted_above = powers(DENSE, RARE, critical + math.radians(8.0), "s")
check("and_no_power_crosses_the_interface_there",
      abs(transmitted_above) < 1e-15 and abs(reflected_above - 1.0) < 1e-15,
      f"T = {transmitted_above:.3e} and R = {reflected_above:.15f}")

below = abs(amplitudes(DENSE, RARE, critical - math.radians(8.0))["r_s"]) ** 2
check("below_it_the_modulus_is_strictly_less_than_one",
      below < 1 - 1e-6,
      f"|r_s|^2 = {below:.9f} eight degrees short of the critical angle, so the "
      "unit modulus above is a regime and not an artefact of the algebra")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
