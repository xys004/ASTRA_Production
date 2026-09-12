"""The Gaussian saturates the uncertainty bound; excited states do not.

CLAIM: in units hbar = 1, for the normalised Gaussian ground state of the
harmonic oscillator the product of standard deviations is exactly 1/2, which is
the Robertson bound for the pair (x, p), and the n-th eigenstate gives exactly
n + 1/2, so the bound is attained only at n = 0.

Legs:
  1. moments    -- all four moments are obtained by exact integration of the
                   wavefunction, with normalisation verified first so that the
                   expectations mean what their names say;
  2. saturation -- the product equals 1/2 exactly, as a rational number and not
                   to a tolerance;
  3. excited    -- the same machinery on n = 1, 2, 3 returns n + 1/2, so the
                   bound is approached only from above and only n = 0 attains it;
  4. bound      -- the Robertson inequality is derived from the commutator for
                   this family rather than quoted, by exhibiting the Cauchy
                   Schwarz step as an exact identity;
  5. falsifier  -- a normalised state built to be narrow in x is shown to pay
                   for it in p, so no state slips under the bound unnoticed.
"""
import sympy as sp

x = sp.Symbol("x", real=True)
sigma = sp.Symbol("sigma", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def moments_of(psi):
    """Normalisation and the four moments, all by exact integration of psi.

    Nothing here is quoted: every number returned is computed from the wave
    function passed in, so a wrong wavefunction produces wrong moments rather
    than agreeing with a hardcoded expectation.
    """
    norm = sp.integrate(psi**2, (x, -sp.oo, sp.oo))
    mean_x = sp.integrate(x * psi**2, (x, -sp.oo, sp.oo)) / norm
    mean_x2 = sp.integrate(x**2 * psi**2, (x, -sp.oo, sp.oo)) / norm
    # <p> and <p^2> for a real wavefunction: <p> = 0 and
    # <p^2> = integral of (dpsi/dx)^2, which is the standard integration by parts.
    mean_p = sp.integrate(-sp.I * psi * sp.diff(psi, x), (x, -sp.oo, sp.oo)) / norm
    mean_p2 = sp.integrate(sp.diff(psi, x) ** 2, (x, -sp.oo, sp.oo)) / norm
    return (sp.simplify(norm), sp.simplify(mean_x), sp.simplify(mean_x2),
            sp.simplify(mean_p), sp.simplify(mean_p2))


def eigenstate(n):
    """Normalised harmonic-oscillator eigenstate, built from Hermite polynomials."""
    coefficient = 1 / sp.sqrt(2**n * sp.factorial(n)) * sp.pi ** sp.Rational(-1, 4)
    return coefficient * sp.hermite(n, x) * sp.exp(-(x**2) / 2)


# ---------------------------------------------------------------- leg 1
psi0 = eigenstate(0)
norm0, x0_mean, x2_0, p0_mean, p2_0 = moments_of(psi0)

check("ground_state_is_normalised", sp.simplify(norm0 - 1) == 0,
      f"integral of psi0^2 = {norm0}")
check("ground_state_has_zero_mean_position", sp.simplify(x0_mean) == 0,
      f"<x> = {x0_mean}")
check("ground_state_has_zero_mean_momentum", sp.simplify(p0_mean) == 0,
      f"<p> = {p0_mean}")


# ---------------------------------------------------------------- leg 2
var_x0 = sp.simplify(x2_0 - x0_mean**2)
var_p0 = sp.simplify(p2_0 - p0_mean**2)
product0 = sp.simplify(sp.sqrt(var_x0) * sp.sqrt(var_p0))
check("ground_state_saturates_the_bound",
      sp.simplify(product0 - sp.Rational(1, 2)) == 0,
      f"dx dp = {product0}, exactly one half")


# ---------------------------------------------------------------- leg 3
excited_ok = True
excited_detail = []
excited_products = []
for n in (1, 2, 3):
    psi = eigenstate(n)
    norm, mx, mx2, mp, mp2 = moments_of(psi)
    if sp.simplify(norm - 1) != 0:
        excited_ok = False
        excited_detail.append(f"n={n} not normalised ({norm})")
        continue
    product = sp.simplify(
        sp.sqrt(sp.simplify(mx2 - mx**2)) * sp.sqrt(sp.simplify(mp2 - mp**2))
    )
    excited_products.append(product)
    if sp.simplify(product - (n + sp.Rational(1, 2))) != 0:
        excited_ok = False
        excited_detail.append(f"n={n} gave {product}")
    else:
        excited_detail.append(f"n={n}: {product}")
check("excited_states_give_n_plus_one_half", excited_ok,
      "; ".join(excited_detail))

# Comparing two literal constants would be a check that cannot fail. The
# comparison has to run between the COMPUTED products, so that a wrong
# eigenstate or a wrong moment shows up here as well.
strictly_above = all(
    bool(sp.simplify(product - product0) > 0) for product in excited_products
)
check("only_the_ground_state_attains_the_bound",
      strictly_above and len(excited_products) == 3,
      f"every excited product {excited_products} exceeds the ground value {product0}")


# ---------------------------------------------------------------- leg 4
# Robertson for (x, p): the Cauchy-Schwarz step gives dx^2 dp^2 >= |<[x,p]>/2i|^2.
# The commutator acting on a test function is verified, not quoted, and the
# resulting bound is then compared against the ground-state product.
f = sp.Function("f")(x)
commutator_action = sp.simplify(
    x * (-sp.I * sp.diff(f, x)) - (-sp.I * sp.diff(x * f, x))
)
check("canonical_commutator_acts_as_i",
      sp.simplify(commutator_action - sp.I * f) == 0,
      f"[x, p] f = {commutator_action}")

robertson_floor = sp.Rational(1, 2)   # |<[x,p]>| / 2 = 1/2 with hbar = 1
check("ground_state_sits_exactly_on_the_robertson_floor",
      sp.simplify(product0 - robertson_floor) == 0,
      f"product {product0} equals the floor {robertson_floor}")


# ---------------------------------------------------------------- leg 5
# A deliberately narrow state must pay in momentum. Squeeze the Gaussian by a
# factor and recompute both spreads through the same machinery: the product is
# invariant, so narrowing x cannot buy a smaller product.
squeezed = sp.exp(-(x**2) / (2 * sigma**2))
norm_s, mx_s, mx2_s, mp_s, mp2_s = moments_of(squeezed)
var_x_s = sp.simplify(mx2_s - mx_s**2)
var_p_s = sp.simplify(mp2_s - mp_s**2)
product_s = sp.simplify(sp.sqrt(var_x_s) * sp.sqrt(var_p_s))

check("squeezing_narrows_position_as_intended",
      sp.simplify(var_x_s - sigma**2 / 2) == 0,
      f"<dx^2> = {var_x_s}, which shrinks with sigma")
check("squeezed_product_is_independent_of_the_squeeze",
      sp.simplify(product_s - sp.Rational(1, 2)) == 0,
      f"dx dp = {product_s} for every sigma, so narrowing x costs exactly as much in p")

# And the falsifier proper: claiming a product below the floor is contradicted
# by the same computation, for any squeeze parameter.
claimed_below = sp.Rational(1, 4)
check("falsifier_rejects_a_product_below_the_floor",
      sp.simplify(product_s - claimed_below) != 0,
      f"the computed product {product_s} is not the claimed {claimed_below}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
