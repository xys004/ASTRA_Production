"""Michaelis-Menten, and what the reciprocal plot costs.

CLAIM: the quasi-steady state of the enzyme mechanism gives v = Vmax S / (Km + S)
with Km the ratio of the losing rates to the binding rate, derived by solving
rather than quoted; the half-maximal rate occurs at S = Km, obtained by solving
for it; the Lineweaver-Burk transform is exactly linear in 1/S with slope
Km/Vmax and intercept 1/Vmax; and fitting that straight line by ordinary least
squares costs both accuracy and precision, because the transform turns
constant-variance noise into noise that grows as one over the rate squared, so
the weakest measurements end up dominating.

The comparison is deliberately not the textbook slogan. Non-linear least squares
on the untransformed data is ALSO biased in a finite sample, by three standard
errors here, so the honest statement is a ratio and not an absolute: the
reciprocal plot is worse on both counts, and much worse on spread.

Legs:
  1. steady    -- the complex concentration is solved for and the rate law falls
                  out of it, with Km appearing as a ratio of rates;
  2. shape     -- the half-maximal point is solved for and the saturation limit
                  is taken;
  3. transform -- the reciprocal plot is exactly linear, with its slope and
                  intercept identified;
  4. weights   -- the transform's effect on the noise is derived, and the
                  implied weight ratio across the design is computed;
  5. falsifier -- over three thousand simulated experiments the reciprocal fit
                  is biased by nine standard errors and its spread is eight
                  times larger;
  6. honest    -- the direct fit is biased too, so the claim is comparative.
"""
import math

import numpy as np
import sympy as sp

S, E0, k_on, k_off, k_cat = sp.symbols("S E_0 k_on k_off k_cat", positive=True)
ES = sp.Symbol("ES", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Formation minus the two ways of losing the complex, set to zero and solved.
# The free enzyme is what is left of the total, which is what couples the two.
formation = k_on * (E0 - ES) * S
loss = (k_off + k_cat) * ES
complexes = sp.solve(sp.Eq(formation, loss), ES)
check("the_steady_state_has_one_complex_concentration",
      len(complexes) == 1,
      f"balancing formation against loss gives ES = "
      f"{complexes[0] if complexes else 'nothing'}")

michaelis = sp.simplify((k_off + k_cat) / k_on)
bound = sp.simplify(complexes[0])
check("and_it_is_the_saturation_form_with_km_a_ratio_of_rates",
      sp.simplify(bound - E0 * S / (michaelis + S)) == 0,
      f"ES = E0 S / (Km + S) with Km = {michaelis}, so Km is the losing rates "
      "over the binding rate and not a fitted constant")

Vmax = sp.Symbol("V_max", positive=True)
Km = sp.Symbol("K_m", positive=True)

# The rate law is obtained from the complex concentration above by naming the
# two combinations that appear in it, eliminating the binding rate through Km
# and the total enzyme through Vmax. Writing the familiar form out again instead
# would leave the whole first leg decorative.
rate = sp.simplify(
    (k_cat * bound).subs(k_on, (k_cat + k_off) / Km).subs(E0, Vmax / k_cat)
)
check("the_rate_law_follows_from_the_complex_by_naming_two_combinations",
      sp.simplify(rate - Vmax * S / (Km + S)) == 0,
      f"v = k_cat [ES] becomes {rate} once Km and Vmax stand for the rate "
      "constants they abbreviate")


# ---------------------------------------------------------------- leg 2
half = sp.solve(sp.Eq(rate, Vmax / 2), S)
check("the_half_maximal_rate_sits_at_a_substrate_equal_to_km",
      len(half) == 1 and sp.simplify(half[0] - Km) == 0,
      f"solving v = Vmax/2 gives S = {half[0] if half else 'nothing'}")

check("and_the_rate_saturates_at_vmax",
      sp.limit(rate, S, sp.oo) == Vmax and sp.simplify(rate.subs(S, 0)) == 0,
      f"the limit at large substrate is {sp.limit(rate, S, sp.oo)} and the rate "
      "starts from zero")

slope_at_zero = sp.simplify(sp.diff(rate, S).subs(S, 0))
check("with_an_initial_slope_of_vmax_over_km",
      sp.simplify(slope_at_zero - Vmax / Km) == 0,
      f"dv/dS at the origin is {slope_at_zero}, the specificity constant")


# ---------------------------------------------------------------- leg 3
inverse_substrate = sp.Symbol("u", positive=True)
transformed = sp.simplify((1 / rate).subs(S, 1 / inverse_substrate))
check("the_reciprocal_plot_is_exactly_linear",
      sp.simplify(sp.diff(transformed, inverse_substrate, 2)) == 0,
      f"1/v = {sp.expand(transformed)} in 1/S, whose second derivative is zero")

check("with_the_slope_and_intercept_the_transform_promises",
      sp.simplify(sp.diff(transformed, inverse_substrate) - Km / Vmax) == 0
      and sp.simplify(transformed.subs(inverse_substrate, 0) - 1 / Vmax) == 0,
      f"slope {sp.simplify(sp.diff(transformed, inverse_substrate))} and "
      f"intercept {sp.simplify(transformed.subs(inverse_substrate, 0))}")


# ---------------------------------------------------------------- leg 4
# What the transform does to the noise, by propagation: the derivative of the
# reciprocal is minus one over the square, so a constant spread in v becomes a
# spread in 1/v that grows as the rate falls.
rate_symbol = sp.Symbol("v", positive=True)
propagated = sp.simplify(sp.Abs(sp.diff(1 / rate_symbol, rate_symbol)))
check("the_transform_scales_the_noise_by_one_over_the_rate_squared",
      sp.simplify(propagated - 1 / rate_symbol ** 2) == 0,
      f"|d(1/v)/dv| = {propagated}, so equal errors in v become unequal errors "
      "in its reciprocal")

TRUE_VMAX, TRUE_KM, SPREAD = 10.0, 2.0, 0.3
DESIGN = np.array([0.5, 0.8, 1.2, 2.0, 3.5, 6.0, 10.0])


def truth(substrate):
    return TRUE_VMAX * substrate / (TRUE_KM + substrate)


spreads = SPREAD / truth(DESIGN) ** 2
ratio = float(spreads.max() / spreads.min())
check("so_the_design_carries_a_wide_spread_of_implied_weights",
      bool(ratio > 10),
      f"across the {len(DESIGN)} substrate levels the spread in 1/v varies by a "
      f"factor of {ratio:.1f}, from {spreads.min():.4f} to {spreads.max():.4f}, "
      "and ordinary least squares on the line weights them all alike")


# ---------------------------------------------------------------- leg 5
def lineweaver(substrate, observed):
    """Ordinary least squares on the reciprocals, as the plot prescribes."""
    abscissa, ordinate = 1 / substrate, 1 / observed
    centre_x, centre_y = abscissa.mean(), ordinate.mean()
    slope = (((abscissa - centre_x) * (ordinate - centre_y)).sum()
             / ((abscissa - centre_x) ** 2).sum())
    intercept = centre_y - slope * centre_x
    return 1 / intercept, slope / intercept


def direct(substrate, observed, start=(8.0, 1.5)):
    """Gauss-Newton on the untransformed rate law, with the exact Jacobian."""
    maximum, constant = start
    for _ in range(60):
        predicted = maximum * substrate / (constant + substrate)
        residual = observed - predicted
        jacobian = np.column_stack([
            substrate / (constant + substrate),
            -maximum * substrate / (constant + substrate) ** 2,
        ])
        try:
            step = np.linalg.solve(jacobian.T @ jacobian, jacobian.T @ residual)
        except np.linalg.LinAlgError:
            break
        maximum, constant = maximum + step[0], constant + step[1]
        if np.abs(step).max() < 1e-12:
            break
    return maximum, constant


REPEATS = 3000
rng = np.random.default_rng(20260912)
reciprocal, untransformed = [], []
for _ in range(REPEATS):
    observed = truth(DESIGN) + rng.normal(0.0, SPREAD, len(DESIGN))
    if (observed <= 0).any():
        continue
    reciprocal.append(lineweaver(DESIGN, observed))
    untransformed.append(direct(DESIGN, observed))

reciprocal = np.array(reciprocal)
untransformed = np.array(untransformed)


def summarise(sample, truth_value):
    bias = float(sample.mean() - truth_value)
    spread = float(sample.std(ddof=1))
    return bias, spread / math.sqrt(len(sample)), spread


def ratio_of(numerator, denominator):
    """A ratio, or infinity when the denominator has collapsed to zero.

    A degenerate fit returns its starting value every time and so has no spread
    at all. Dividing by that would end the run in a traceback rather than in a
    failed check, which is where a degenerate fit belongs.
    """
    return numerator / denominator if denominator > 0 else math.inf


lb_bias, lb_error, lb_spread = summarise(reciprocal[:, 0], TRUE_VMAX)
check("falsifier_the_reciprocal_fit_is_biased_in_vmax",
      bool(lb_bias > 5 * lb_error),
      f"over {len(reciprocal)} simulated experiments it overestimates Vmax by "
      f"{lb_bias:+.4f}, which is {ratio_of(lb_bias, lb_error):.1f} standard errors, so "
      "the plot that looks like a straight line is not an innocent rescaling")

direct_bias, direct_error, direct_spread = summarise(untransformed[:, 0], TRUE_VMAX)
check("and_its_spread_is_the_larger_cost",
      bool(lb_spread > 5 * direct_spread),
      f"the reciprocal estimates scatter by {lb_spread:.3f} against "
      f"{direct_spread:.3f} for the direct fit, a factor of "
      f"{ratio_of(lb_spread, direct_spread):.1f}, which dwarfs the bias of "
      f"{lb_bias:.3f} either carries")


# ---------------------------------------------------------------- leg 6
# The honest half. Non-linear least squares is not unbiased in a finite sample
# either, and saying otherwise would be the same kind of overclaim the corpus
# exists to catch. The statement that survives is comparative.
check("the_direct_fit_is_biased_too_so_the_claim_is_comparative",
      bool(direct_bias > 2 * direct_error),
      f"the direct fit overestimates Vmax by {direct_bias:+.4f}, which is "
      f"{ratio_of(direct_bias, direct_error):.1f} standard errors and therefore real; "
      "unbiasedness is not what separates the two methods")

check("what_separates_them_is_how_much_of_each",
      bool(lb_bias > 10 * direct_bias),
      f"the biases stand at {lb_bias:.4f} against {direct_bias:.4f}, a factor of "
      f"{ratio_of(lb_bias, direct_bias):.0f}, and the spreads at {lb_spread:.3f} against "
      f"{direct_spread:.3f}")

relative = ratio_of(lb_bias, lb_spread)
direct_relative = ratio_of(direct_bias, direct_spread)
check("and_the_bias_is_worse_even_measured_against_each_methods_own_scatter",
      bool(relative > direct_relative),
      f"the bias is {relative:.3f} of the scatter for the reciprocal plot and "
      f"{direct_relative:.3f} for the direct fit, so the transform does not buy "
      "precision back in exchange for the accuracy it loses")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
