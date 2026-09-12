"""Arrhenius rates are linear in 1/T, and the rule of thumb has a narrow domain.

CLAIM: for k(T) = A exp(-Ea/(R T)), the plot of ln k against 1/T is exactly a
straight line of slope -Ea/R; a least-squares fit recovers Ea from data; the
familiar claim that a ten-degree rise doubles the rate holds only for a narrow
band of activation energies near room temperature, and the band is computed
rather than repeated.

Legs:
  1. linearisation -- the slope is obtained by differentiating with respect to
                      1/T, and the second derivative is required to vanish, so
                      the line is exact rather than approximate;
  2. recovery      -- an independent least-squares fit, written here, recovers
                      the activation energy from generated data; this tests the
                      fit, and the next leg is what tests the law;
  3. rule of thumb -- the doubling claim is solved for the activation energy it
                      requires, and the answer is a single value, not a range,
                      so the rule is shown to be an approximation with a stated
                      validity window;
  4. van t Hoff    -- the same structure applied to an equilibrium constant
                      gives d(ln K)/d(1/T) = -dH/R, derived not quoted;
  5. falsifier     -- a power-law rate is not linear in 1/T, and the same fit
                      detects it through curvature the residuals expose.
"""
import math

import sympy as sp

T, R, Ea, A, dH = sp.symbols("T R E_a A Delta_H", positive=True)
inverse = sp.Symbol("u", positive=True)          # u = 1/T

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def least_squares(xs, ys):
    """Ordinary least squares for a straight line, written out rather than imported."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    return slope, intercept


# ---------------------------------------------------------------- leg 1
rate = A * sp.exp(-Ea / (R * T))
log_rate_in_u = sp.simplify(sp.log(rate).subs(T, 1 / inverse))
slope = sp.simplify(sp.diff(log_rate_in_u, inverse))
check("slope_against_inverse_temperature_is_minus_Ea_over_R",
      sp.simplify(slope + Ea / R) == 0,
      f"d(ln k)/d(1/T) = {slope}")

curvature = sp.simplify(sp.diff(log_rate_in_u, inverse, 2))
check("the_relation_is_exactly_linear_not_approximately",
      curvature == 0,
      f"second derivative with respect to 1/T = {curvature}")


# ---------------------------------------------------------------- leg 2
# Generate data from the law and recover the parameter with the fit above. This
# is a round trip through the fitting code, so it tests the fit rather than the
# law; leg 5 is what puts the law itself at risk.
R_SI = 8.314462618
EA_TRUE = 75000.0          # J/mol, a typical activation energy
A_TRUE = 2.5e11
temperatures = [280.0 + 10.0 * i for i in range(12)]
xs = [1.0 / temp for temp in temperatures]
ys = [math.log(A_TRUE * math.exp(-EA_TRUE / (R_SI * temp))) for temp in temperatures]

fitted_slope, fitted_intercept = least_squares(xs, ys)
recovered_ea = -fitted_slope * R_SI
recovered_a = math.exp(fitted_intercept)
check("fit_recovers_the_activation_energy",
      abs(recovered_ea - EA_TRUE) / EA_TRUE < 1e-12,
      f"recovered {recovered_ea:.6f} J/mol against {EA_TRUE}")
check("fit_recovers_the_prefactor",
      abs(recovered_a - A_TRUE) / A_TRUE < 1e-9,
      f"recovered A = {recovered_a:.6e} against {A_TRUE:.6e}")

residuals = [
    y - (fitted_slope * x + fitted_intercept) for x, y in zip(xs, ys)
]
check("arrhenius_data_leaves_no_curvature_in_the_residuals",
      max(abs(value) for value in residuals) < 1e-9,
      f"largest residual {max(abs(v) for v in residuals):.3e}, consistent with an exact line")


# ---------------------------------------------------------------- leg 3
# The doubling rule, solved rather than repeated. Requiring k(T+10)/k(T) = 2
# fixes the activation energy, so the rule is exact only for that one value.
T0 = sp.Rational(298)
ratio = sp.simplify(
    sp.exp(-Ea / (R * (T0 + 10))) / sp.exp(-Ea / (R * T0))
)
required = sp.solve(sp.Eq(ratio, 2), Ea)
check("doubling_requires_one_specific_activation_energy",
      len(required) == 1,
      f"k(T+10)/k(T) = 2 forces Ea = {sp.simplify(required[0])}")

required_value = float(required[0].subs(R, R_SI))
check("that_energy_is_about_fifty_three_kilojoules",
      abs(required_value - 52900) < 200,
      f"Ea = {required_value:.0f} J/mol, not a range")

# At the activation energy used above the rule is simply wrong, which is the
# content of saying the window is narrow.
actual_ratio = math.exp(-EA_TRUE / (R_SI * 308)) / math.exp(-EA_TRUE / (R_SI * 298))
check("rule_of_thumb_fails_away_from_that_value",
      abs(actual_ratio - 2) > 0.5,
      f"at Ea = {EA_TRUE:.0f} J/mol a ten-degree rise multiplies the rate by "
      f"{actual_ratio:.3f}, not 2")


# ---------------------------------------------------------------- leg 4
equilibrium = sp.exp(-dH / (R * T))
log_k_in_u = sp.simplify(sp.log(equilibrium).subs(T, 1 / inverse))
vant_hoff = sp.simplify(sp.diff(log_k_in_u, inverse))
check("vant_hoff_slope_is_minus_delta_H_over_R",
      sp.simplify(vant_hoff + dH / R) == 0,
      f"d(ln K)/d(1/T) = {vant_hoff}")


# ---------------------------------------------------------------- leg 5
# A power-law rate must NOT be linear in 1/T, and the same fit must see it.
power_ys = [math.log(A_TRUE * temp**2.5) for temp in temperatures]
power_slope, power_intercept = least_squares(xs, power_ys)
power_residuals = [
    y - (power_slope * x + power_intercept) for x, y in zip(xs, power_ys)
]
largest = max(abs(value) for value in power_residuals)
check("falsifier_power_law_leaves_curvature_the_fit_detects",
      largest > 1e-3,
      f"largest residual {largest:.3e}, four orders above the Arrhenius case")

# And the curvature has a sign pattern, not just scatter: the residuals change
# sign, which is what distinguishes systematic curvature from noise.
signs = [1 if value > 0 else -1 for value in power_residuals]
changes = sum(1 for i in range(len(signs) - 1) if signs[i] != signs[i + 1])
check("the_curvature_is_systematic_not_scatter",
      1 <= changes <= 3,
      f"{changes} sign changes across the residual sequence, the signature of a bend")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
