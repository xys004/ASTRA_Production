"""The Schwarzschild metric is a vacuum solution, and the 2-sphere is not flat.

CLAIM: outside r = 2M the Schwarzschild metric has identically vanishing Ricci
tensor, while its Riemann tensor does not vanish, so the spacetime is curved but
source free. As a control on the same machinery, the round 2-sphere of radius a
has Ricci scalar exactly 2/a^2.

Legs:
  1. vacuum    -- every component of the Ricci tensor simplifies to exactly zero
                  on the Schwarzschild metric;
  2. curved    -- the Kretschmann scalar is 48 M^2 / r^6, nonzero, so leg 1 is
                  not the trivial statement that the geometry is flat;
  3. control   -- the identical pipeline returns R = 2/a^2 on the 2-sphere, which
                  is a known nonzero answer and checks the code, not the metric;
  4. falsifier -- perturbing one metric coefficient makes the Ricci tensor
                  nonzero, so leg 1 can fail.
"""
import itertools

import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def christoffel(metric, coords):
    """Levi-Civita connection, Gamma^a_{bc}, from the metric and its inverse."""
    inverse = metric.inv()
    n = len(coords)
    gamma = [[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)]
    for a, b, c in itertools.product(range(n), repeat=3):
        total = sp.S.Zero
        for d in range(n):
            total += inverse[a, d] * (
                sp.diff(metric[d, b], coords[c])
                + sp.diff(metric[d, c], coords[b])
                - sp.diff(metric[b, c], coords[d])
            )
        gamma[a][b][c] = sp.simplify(total / 2)
    return gamma


def ricci_tensor(gamma, coords):
    """R_{bc} = d_a G^a_bc - d_c G^a_ba + G^a_ad G^d_bc - G^a_cd G^d_ba."""
    n = len(coords)
    ricci = sp.zeros(n, n)
    for b, c in itertools.product(range(n), repeat=2):
        total = sp.S.Zero
        for a in range(n):
            total += sp.diff(gamma[a][b][c], coords[a])
            total -= sp.diff(gamma[a][b][a], coords[c])
            for d in range(n):
                total += gamma[a][a][d] * gamma[d][b][c]
                total -= gamma[a][c][d] * gamma[d][b][a]
        ricci[b, c] = sp.simplify(total)
    return ricci


def riemann_tensor(gamma, coords):
    """R^a_{bcd}, used only for the curvature invariant below."""
    n = len(coords)
    riemann = [[[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)]
               for _ in range(n)]
    for a, b, c, d in itertools.product(range(n), repeat=4):
        total = sp.diff(gamma[a][b][d], coords[c]) - sp.diff(gamma[a][b][c], coords[d])
        for e in range(n):
            total += gamma[a][c][e] * gamma[e][b][d]
            total -= gamma[a][d][e] * gamma[e][b][c]
        riemann[a][b][c][d] = sp.simplify(total)
    return riemann


# ---------------------------------------------------------------- leg 1
t, r, theta, phi = sp.symbols("t r theta phi", real=True)
M = sp.Symbol("M", positive=True)
coords = (t, r, theta, phi)

f = 1 - 2 * M / r
schwarzschild = sp.diag(-f, 1 / f, r**2, r**2 * sp.sin(theta) ** 2)

gamma = christoffel(schwarzschild, coords)
ricci = ricci_tensor(gamma, coords)
vacuum = all(sp.simplify(ricci[i, j]) == 0
             for i, j in itertools.product(range(4), repeat=2))
# The detail string must not itself raise when the leg fails: max() over
# symbolic components asks for an ordering sympy cannot decide, which would kill
# the process before any VERDICT line is printed and leave a harness with
# nothing to parse.
nonzero_components = [
    f"R_{i}{j}={sp.simplify(ricci[i, j])}"
    for i, j in itertools.product(range(4), repeat=2)
    if sp.simplify(ricci[i, j]) != 0
]
check("schwarzschild_is_ricci_flat", vacuum,
      "every component vanishes" if vacuum
      else f"nonzero: {'; '.join(nonzero_components[:3])}")


# ---------------------------------------------------------------- leg 2
# Ricci flat is not the same as flat. The Kretschmann scalar distinguishes them
# and must come out nonzero, otherwise leg 1 would be vacuous.
riemann = riemann_tensor(gamma, coords)
inverse = schwarzschild.inv()
lowered = [[[[sp.S.Zero] * 4 for _ in range(4)] for _ in range(4)] for _ in range(4)]
for a, b, c, d in itertools.product(range(4), repeat=4):
    lowered[a][b][c][d] = sp.simplify(
        sum(schwarzschild[a, e] * riemann[e][b][c][d] for e in range(4))
    )

# Both metrics here are diagonal, so g^{ae} is nonzero only for a == e and the
# index raising collapses to one factor per slot with no sum. That is what makes
# the contraction tractable: the full four-index raise inside a four-index loop
# would be 65536 symbolic operations.
#
# It is justified by construction, not by a check. The metric is built with
# sp.diag, whose off-diagonal entries are literal zeros, so a check asking
# whether they vanish could never fail and would be decoration. The 2-sphere
# control below runs the full double sum and would expose a contraction bug.

kretschmann = sp.S.Zero
for a, b, c, d in itertools.product(range(4), repeat=4):
    component = lowered[a][b][c][d]
    if component == 0:
        continue
    raised = (inverse[a, a] * inverse[b, b] * inverse[c, c] * inverse[d, d]
              * component)
    kretschmann += component * raised
kretschmann = sp.simplify(kretschmann)

check("kretschmann_is_48_M2_over_r6",
      sp.simplify(kretschmann - 48 * M**2 / r**6) == 0,
      f"K = {kretschmann}")
check("geometry_is_genuinely_curved", sp.simplify(kretschmann) != 0,
      "Ricci flat but not flat, so leg 1 is not vacuous")


# ---------------------------------------------------------------- leg 3
# Same pipeline, known nonzero answer. This checks the code rather than the
# metric: a bug that forces Ricci to zero would be caught right here.
a_sym = sp.Symbol("a", positive=True)
sphere_coords = (theta, phi)
sphere = sp.diag(a_sym**2, a_sym**2 * sp.sin(theta) ** 2)
sphere_gamma = christoffel(sphere, sphere_coords)
sphere_ricci = ricci_tensor(sphere_gamma, sphere_coords)
sphere_inverse = sphere.inv()
sphere_scalar = sp.simplify(
    sum(sphere_inverse[i, j] * sphere_ricci[i, j]
        for i, j in itertools.product(range(2), repeat=2))
)
check("two_sphere_scalar_curvature_is_two_over_a_squared",
      sp.simplify(sphere_scalar - 2 / a_sym**2) == 0,
      f"R = {sphere_scalar}")


# ---------------------------------------------------------------- leg 4
# Perturb g_tt and the vacuum condition must break.
perturbed = sp.diag(-(f + M**2 / r**2), 1 / f, r**2, r**2 * sp.sin(theta) ** 2)
perturbed_ricci = ricci_tensor(christoffel(perturbed, coords), coords)
broke = any(sp.simplify(perturbed_ricci[i, j]) != 0
            for i, j in itertools.product(range(4), repeat=2))
check("falsifier_perturbation_breaks_vacuum", broke,
      "a perturbed g_tt produces a nonzero Ricci tensor as it must")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
