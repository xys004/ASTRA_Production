"""Second-derivative identities of vector calculus, and the divergence theorem.

CLAIM: for any twice continuously differentiable field, div(curl F) = 0 and
curl(grad phi) = 0 identically, and for F = (x, y, z) the divergence theorem
gives a flux of 4*pi*a^3 through the sphere of radius a.

Legs:
  1. symbolic  -- both identities on generic undefined functions, so nothing is
                  special about a chosen example;
  2. numeric   -- the same identity is confirmed by finite differences on a
                  concrete field, which can fail and does when the curl is wrong;
  3. integral  -- the divergence theorem on a sphere, with the volume and the
                  surface side each integrated separately and compared exactly;
  4. falsifier -- a field whose curl is not divergence free would break leg 1,
                  and a deliberately corrupted curl is shown to be detected.
"""
import math

import sympy as sp

x, y, z, a = sp.symbols("x y z a", real=True)
a_pos = sp.Symbol("a", positive=True)

f = sp.Function("f")(x, y, z)
g = sp.Function("g")(x, y, z)
h = sp.Function("h")(x, y, z)
phi = sp.Function("phi")(x, y, z)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def curl(vector):
    p, q, r = vector
    return (
        sp.diff(r, y) - sp.diff(q, z),
        sp.diff(p, z) - sp.diff(r, x),
        sp.diff(q, x) - sp.diff(p, y),
    )


def divergence(vector):
    p, q, r = vector
    return sp.diff(p, x) + sp.diff(q, y) + sp.diff(r, z)


def gradient(scalar):
    return (sp.diff(scalar, x), sp.diff(scalar, y), sp.diff(scalar, z))


# ---------------------------------------------------------------- leg 1
F = (f, g, h)
div_curl = sp.simplify(divergence(curl(F)))
check("div_curl_vanishes_for_generic_field", div_curl == 0,
      f"div(curl F) = {div_curl}")

curl_grad = tuple(sp.simplify(component) for component in curl(gradient(phi)))
check("curl_grad_vanishes_for_generic_scalar",
      all(component == 0 for component in curl_grad),
      f"curl(grad phi) = {curl_grad}")


# ---------------------------------------------------------------- leg 2
# NOT checked here: that mixed partials commute. SymPy sorts the variables of a
# Derivative canonically, so diff(phi, x, y) and diff(phi, y, x) are the same
# object and their difference is zero before any simplification. Such a test
# cannot fail for any input, including fields where the mixed partials genuinely
# differ, so it would be decoration rather than evidence.
#
# Instead the identity is re-derived numerically by finite differences on a
# concrete field. This leg is independent of the symbolic engine and does fail
# when the curl is wrong, which is what leg 1 needs as corroboration.
def numeric_field(px, py, pz):
    return (
        math.sin(px) * math.exp(py) + pz**3,
        px**2 * pz - math.cos(py),
        px * py * math.sin(pz),
    )


def numeric_div_curl(px, py, pz, h=1e-4):
    """div(curl F) by central differences, using only numeric_field."""
    def component(index, qx, qy, qz):
        return numeric_field(qx, qy, qz)[index]

    def d(index, axis, qx, qy, qz):
        step = [0.0, 0.0, 0.0]
        step[axis] = h
        plus = component(index, qx + step[0], qy + step[1], qz + step[2])
        minus = component(index, qx - step[0], qy - step[1], qz - step[2])
        return (plus - minus) / (2 * h)

    def curl_component(axis, qx, qy, qz):
        i, j = [(1, 2), (2, 0), (0, 1)][axis]
        return d(j, i, qx, qy, qz) - d(i, j, qx, qy, qz)

    total = 0.0
    for axis in range(3):
        step = [0.0, 0.0, 0.0]
        step[axis] = h
        plus = curl_component(axis, px + step[0], py + step[1], pz + step[2])
        minus = curl_component(axis, px - step[0], py - step[1], pz - step[2])
        total += (plus - minus) / (2 * h)
    return total


samples = [(0.3, -0.7, 1.1), (-1.2, 0.4, -0.9), (2.0, 1.5, 0.2)]
worst = max(abs(numeric_div_curl(*point)) for point in samples)
# Second-order central differences applied twice leave an error of order h^2
# times the fourth derivative, which for this field is below 1e-3 at h = 1e-4.
check("numeric_div_curl_vanishes", worst < 1e-3,
      f"max |div curl F| over {len(samples)} points = {worst:.3e}")


# ---------------------------------------------------------------- leg 3
# Divergence theorem for F = (x, y, z) on the ball of radius a.
radial = (x, y, z)
div_radial = sp.simplify(divergence(radial))
check("radial_field_divergence_is_three", div_radial == 3,
      f"div(x,y,z) = {div_radial}")

# Integrate the divergence over the ball rather than quoting its volume, so
# both sides of the theorem are independently computed as the docstring claims.
r_sph, theta, varphi = sp.symbols("r_sph theta varphi", nonnegative=True)
volume_integral = sp.simplify(
    sp.integrate(
        sp.integrate(
            sp.integrate(div_radial * r_sph**2 * sp.sin(theta), (r_sph, 0, a_pos)),
            (theta, 0, sp.pi),
        ),
        (varphi, 0, 2 * sp.pi),
    )
)

# Surface side, computed independently in spherical coordinates. On the sphere
# F . n = a, and the area element is a^2 sin(theta) dtheta dphi.
flux_integrand = a_pos * a_pos**2 * sp.sin(theta)
surface_integral = sp.simplify(
    sp.integrate(
        sp.integrate(flux_integrand, (theta, 0, sp.pi)),
        (varphi, 0, 2 * sp.pi),
    )
)
check("divergence_theorem_two_sides_agree",
      sp.simplify(volume_integral - surface_integral) == 0,
      f"volume {volume_integral} vs surface {surface_integral}")

check("flux_has_expected_closed_form",
      sp.simplify(surface_integral - 4 * sp.pi * a_pos**3) == 0,
      f"flux = {surface_integral}")


# ---------------------------------------------------------------- leg 4
# The identity test must be able to fail. Corrupt one component of the curl and
# confirm the divergence no longer vanishes, so leg 1 has real discriminating
# power rather than being true by construction.
corrupted = list(curl(F))
corrupted[0] = corrupted[0] + sp.diff(f, x)
corrupted_divergence = sp.simplify(divergence(tuple(corrupted)))
check("falsifier_detects_corrupted_curl", corrupted_divergence != 0,
      f"corrupted div = {corrupted_divergence}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
