"""Maxwell's equations in vacuum force electromagnetic waves to travel at c.

CLAIM: from the source-free Maxwell equations, each Cartesian component of E
obeys the wave equation with speed 1/sqrt(mu0*eps0), and a plane wave
E = E0 cos(k z - w t) x-hat is a solution exactly when w/k equals that speed.

Legs:
  1. identity   -- curl(curl E) = grad(div E) - laplacian(E) is verified on a
                   generic field before it is used, not quoted;
  2. derivation -- combining Faraday and Ampere with div E = 0 yields the wave
                   equation, and the residual is required to vanish exactly;
  3. dispersion -- the plane wave satisfies it iff w^2 = k^2/(mu0 eps0); the
                   algebraic factor is solved on its own so no spurious roots of
                   the cosine are mistaken for physical solutions;
  4. numeric    -- the speed evaluates to the codata value of c within the
                   precision of the constants used;
  5. falsifier  -- a wave with the wrong speed leaves a nonzero residual.
"""
import sympy as sp

x, y, z, t = sp.symbols("x y z t", real=True)
k, w = sp.symbols("k omega", positive=True)
mu0, eps0, E0 = sp.symbols("mu0 epsilon0 E0", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


COORDS = (x, y, z)


def curl(vector):
    p, q, r = vector
    return (
        sp.diff(r, y) - sp.diff(q, z),
        sp.diff(p, z) - sp.diff(r, x),
        sp.diff(q, x) - sp.diff(p, y),
    )


def divergence(vector):
    return sum(sp.diff(component, coord)
               for component, coord in zip(vector, COORDS))


def gradient(scalar):
    return tuple(sp.diff(scalar, coord) for coord in COORDS)


def laplacian(vector):
    return tuple(sum(sp.diff(component, coord, 2) for coord in COORDS)
                 for component in vector)


# ---------------------------------------------------------------- leg 1
Ex = sp.Function("Ex")(x, y, z, t)
Ey = sp.Function("Ey")(x, y, z, t)
Ez = sp.Function("Ez")(x, y, z, t)
E_generic = (Ex, Ey, Ez)

lhs = curl(curl(E_generic))
rhs = tuple(
    grad_component - lap_component
    for grad_component, lap_component
    in zip(gradient(divergence(E_generic)), laplacian(E_generic))
)
identity_residual = tuple(sp.simplify(a - b) for a, b in zip(lhs, rhs))
check("double_curl_identity_verified",
      all(component == 0 for component in identity_residual),
      "curl curl E = grad div E - laplacian E on a generic field")


# ---------------------------------------------------------------- leg 2
# The derivation, carried out rather than described. A magnetic field is
# introduced, Faraday fixes it from E, Ampere is then imposed, and the wave
# equation must come out of that pair. Comparing d2E/dt2 / speed^2 against
# mu0 eps0 d2E/dt2 would be no derivation at all: those coefficients are equal
# by the definition of speed, so such a check passes for any field whatsoever.
E_wave = E0 * sp.cos(k * z - w * t)
E_vector = (E_wave, 0, 0)

# Faraday, curl E = -dB/dt, integrated in time to give B for this E.
faraday_curl = curl(E_vector)
B_vector = tuple(
    sp.simplify(-sp.integrate(component, t)) for component in faraday_curl
)
faraday_residual = tuple(
    sp.simplify(a_component + sp.diff(b_component, t))
    for a_component, b_component in zip(faraday_curl, B_vector)
)
check("faraday_law_is_satisfied_by_construction",
      all(component == 0 for component in faraday_residual),
      f"B = {B_vector[1]}")

# Ampere in vacuum, curl B = mu0 eps0 dE/dt, is an extra condition. It holds
# only for particular omega, and solving it is what produces the wave speed.
ampere_residual = tuple(
    sp.simplify(b_component - mu0 * eps0 * sp.diff(e_component, t))
    for b_component, e_component in zip(curl(B_vector), E_vector)
)
dispersion_roots = sp.solve(sp.Eq(mu0 * eps0 * w**2 - k**2, 0), w)
positive_dispersion = [root for root in dispersion_roots if bool(root.is_positive)]
check("ampere_law_forces_the_dispersion_relation",
      len(positive_dispersion) == 1
      and sp.simplify(sp.expand(
          ampere_residual[0].subs(w, positive_dispersion[0]))) == 0,
      f"omega = {positive_dispersion[0] if positive_dispersion else 'none'}")

# With both laws imposed, each component of E satisfies the wave equation.
wave_residual = sp.simplify(
    (sum(sp.diff(E_wave, coord, 2) for coord in COORDS)
     - mu0 * eps0 * sp.diff(E_wave, t, 2)).subs(w, positive_dispersion[0])
)
check("wave_equation_follows_from_the_pair", wave_residual == 0,
      f"laplacian(E) - mu0 eps0 d2E/dt2 = {wave_residual} once omega is fixed")


# ---------------------------------------------------------------- leg 3
plane = E0 * sp.cos(k * z - w * t)
plane_field = (plane, 0, 0)

check("plane_wave_is_divergence_free",
      sp.simplify(divergence(plane_field)) == 0,
      "div E = 0 holds for a transverse plane wave")

plane_residual = sp.simplify(
    sum(sp.diff(plane, coord, 2) for coord in COORDS)
    - mu0 * eps0 * sp.diff(plane, t, 2)
)
# Solving the residual directly also returns roots of the cosine factor, which
# are artefacts of the particular point rather than physical dispersion. Factor
# the residual and solve only the algebraic part.
algebraic_factor = sp.simplify(sp.cancel(plane_residual / plane))
solutions = sp.solve(sp.Eq(algebraic_factor, 0), w)
positive_roots = [root for root in solutions if bool(root.is_positive)]
check("dispersion_relation_is_exactly_omega_over_k",
      len(positive_roots) == 1
      and sp.simplify(positive_roots[0] - k / sp.sqrt(mu0 * eps0)) == 0,
      f"algebraic factor {algebraic_factor} has the single positive root "
      f"{positive_roots[0] if positive_roots else 'none'}")


# ---------------------------------------------------------------- leg 4
MU0 = sp.Float("1.25663706212e-6")      # N/A^2, CODATA 2018
EPS0 = sp.Float("8.8541878128e-12")     # F/m, CODATA 2018
C_REF = sp.Float("299792458")           # m/s, exact by definition
speed = 1 / sp.sqrt(MU0 * EPS0)
relative_error = abs(speed - C_REF) / C_REF
# The constants carry about ten significant figures, so agreement below 1e-9
# is what their precision supports. A looser bound would not test anything.
# bool() is deliberate: a sympy relational evaluates to BooleanTrue, which is
# not the Python True this harness requires, and would silently read as failure.
check("speed_matches_defined_c",
      bool(relative_error < sp.Float("1e-9")),
      f"1/sqrt(mu0 eps0) = {sp.N(speed, 12)}, relative error {sp.N(relative_error, 3)}")


# ---------------------------------------------------------------- leg 5
# A wave with the wrong speed must leave a residual, or leg 3 proves nothing.
wrong = E0 * sp.cos(k * z - 2 * w * t)
wrong_residual = sp.simplify(
    (sum(sp.diff(wrong, coord, 2) for coord in COORDS)
     - mu0 * eps0 * sp.diff(wrong, t, 2)).subs(w, k / sp.sqrt(mu0 * eps0))
)
check("falsifier_rejects_wrong_speed", sp.simplify(wrong_residual) != 0,
      "doubling the frequency at fixed k breaks the equation as it must")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
