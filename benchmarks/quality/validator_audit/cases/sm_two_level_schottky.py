"""The two-level system has a Schottky peak, and its heat capacity vanishes at both ends.

CLAIM: for a system with energies 0 and eps in contact with a bath at inverse
temperature beta, the partition function is Z = 1 + exp(-beta*eps), the mean
energy is eps/(exp(beta*eps) + 1), and the heat capacity vanishes as T tends to
zero and as T tends to infinity, so it must pass through a maximum in between.
That maximum is the Schottky anomaly and sits at beta*eps = 2.399357...

Legs:
  1. ensemble   -- Z is summed over the states and the mean energy is obtained
                   BOTH by the derivative of ln Z and by the direct weighted sum,
                   two routes that must agree symbolically;
  2. capacity   -- C is differentiated from the mean energy with respect to
                   temperature, not quoted;
  3. limits     -- both limits are taken symbolically and both are zero, which is
                   what forces an interior maximum;
  4. peak       -- the stationary point is located by solving dC/dbeta = 0 and
                   confirmed to be a maximum by the sign of the second
                   derivative, not by scanning a grid and taking the largest;
  5. falsifier  -- a partition function missing the ground state gives a mean
                   energy that the same comparison rejects.
"""
import mpmath as mp
import sympy as sp

beta, eps, T, kB = sp.symbols("beta epsilon T k_B", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
LEVELS = (sp.Integer(0), eps)
Z = sp.simplify(sum(sp.exp(-beta * level) for level in LEVELS))
check("partition_function_is_the_state_sum",
      sp.simplify(Z - (1 + sp.exp(-beta * eps))) == 0,
      f"Z = {Z}")

# Route one: the thermodynamic derivative.
energy_from_logz = sp.simplify(-sp.diff(sp.log(Z), beta))
# Route two: the weighted average over the same levels, built independently.
energy_direct = sp.simplify(
    sum(level * sp.exp(-beta * level) for level in LEVELS) / Z
)
check("two_routes_to_the_mean_energy_agree",
      sp.simplify(energy_from_logz - energy_direct) == 0,
      f"<E> = {sp.simplify(sp.together(energy_direct))}")

check("mean_energy_has_the_fermi_form",
      sp.simplify(energy_direct - eps / (sp.exp(beta * eps) + 1)) == 0,
      "eps / (exp(beta eps) + 1)")


# ---------------------------------------------------------------- leg 2
# C = dU/dT with beta = 1/(kB T). Differentiate rather than quote.
energy_of_T = sp.simplify(energy_direct.subs(beta, 1 / (kB * T)))
capacity = sp.simplify(sp.diff(energy_of_T, T))
expected_capacity = (
    kB * (eps / (kB * T)) ** 2 * sp.exp(eps / (kB * T))
    / (sp.exp(eps / (kB * T)) + 1) ** 2
)
# The two forms are equal, but sympy will not see it while the hyperbolic
# argument is the compound expression eps/(kB T): the half-angle identity
# 2(cosh u + 1) = 4 cosh^2(u/2) is applied only when the argument is an atomic
# symbol. Substituting the dimensionless u = eps/(kB T) makes the comparison
# collapse exactly. This is a representation fix, not a weakening: the check is
# still an exact symbolic equality, now expressed in the natural variable.
u = sp.Symbol("u", positive=True)
capacity_u = sp.simplify(capacity.subs(T, eps / (kB * u)))
expected_u = sp.simplify(expected_capacity.subs(T, eps / (kB * u)))
capacity_gap = sp.simplify(capacity_u - expected_u)
check("heat_capacity_matches_the_schottky_form", capacity_gap == 0,
      f"C(u) = {capacity_u}, equal to kB u^2 e^u / (e^u + 1)^2")


# ---------------------------------------------------------------- leg 3
low = sp.limit(capacity, T, 0, "+")
high = sp.limit(capacity, T, sp.oo)
check("capacity_vanishes_at_zero_temperature", sp.simplify(low) == 0,
      f"lim C = {low} as T -> 0+")
check("capacity_vanishes_at_infinite_temperature", sp.simplify(high) == 0,
      f"lim C = {high} as T -> oo")

# A continuous positive function vanishing at both ends must have an interior
# maximum. Positivity somewhere in between is what makes that argument bite.
midpoint = sp.simplify(capacity.subs({eps: 1, kB: 1, T: sp.Rational(1, 2)}))
check("capacity_is_positive_in_between",
      bool(sp.N(midpoint) > 0),
      f"C(T = 1/2) = {sp.N(midpoint, 8)} > 0, so the maximum is interior")


# ---------------------------------------------------------------- leg 4
# Locate the peak by solving the stationarity condition in the dimensionless
# variable x = beta*eps, then confirm the sign of the second derivative. Taking
# the largest value on a grid would not distinguish a maximum from a sampling
# artefact.
x = sp.Symbol("x", positive=True)
shape = x**2 * sp.exp(x) / (sp.exp(x) + 1) ** 2
stationary = sp.simplify(sp.diff(shape, x))
# The residual at the root is limited by the working precision, so the precision
# is raised first and the threshold is then set from it rather than picked. At
# 40 digits the residual reaches 1e-40; 1e-30 leaves ten digits of margin.
mp.mp.dps = 40
stationary_fn = sp.lambdify(x, stationary, "mpmath")
root = mp.findroot(stationary_fn, mp.mpf("2.4"))
second = sp.lambdify(x, sp.diff(shape, x, 2), "mpmath")(root)

check("stationary_point_located",
      abs(mp.mpf(stationary_fn(root))) < mp.mpf("1e-30"),
      f"dC/dx = {mp.nstr(abs(stationary_fn(root)), 4)} at x = {mp.nstr(root, 12)}")
check("stationary_point_is_a_maximum", bool(second < 0),
      f"second derivative there = {mp.nstr(second, 6)} < 0")
check("peak_is_at_the_known_schottky_value",
      abs(root - mp.mpf("2.399357280074")) < mp.mpf("1e-9"),
      f"x_peak = {mp.nstr(root, 12)}")


# ---------------------------------------------------------------- leg 5
# Dropping the ground state from Z changes the physics: the mean energy becomes
# constant and the heat capacity vanishes identically, which the same
# comparisons must reject.
Z_wrong = sp.exp(-beta * eps)
energy_wrong = sp.simplify(
    eps * sp.exp(-beta * eps) / Z_wrong
)
check("falsifier_missing_ground_state_changes_the_energy",
      sp.simplify(energy_wrong - energy_direct) != 0,
      f"<E> would be {energy_wrong}, independent of temperature")

capacity_wrong = sp.simplify(sp.diff(energy_wrong.subs(beta, 1 / (kB * T)), T))
check("falsifier_missing_ground_state_kills_the_peak",
      sp.simplify(capacity_wrong) == 0 and sp.simplify(capacity) != 0,
      f"C would be {capacity_wrong} everywhere, so the anomaly disappears")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
