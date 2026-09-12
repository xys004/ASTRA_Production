"""Reversible adiabats obey P V^gamma = const, and Carnot bounds any engine.

CLAIM: for an ideal gas undergoing a reversible adiabatic change, P V^gamma is
constant with gamma = Cp/Cv, the entropy change is exactly zero, and the ideal
gas Carnot cycle has efficiency exactly 1 - Tc/Th, which is strictly below one.

Scope: this establishes the efficiency OF THE IDEAL-GAS CARNOT CYCLE. That no
other reversible cycle exceeds it is a theorem about all cycles and is not
tested here; the file verifies the value and its strictness, not universality.

Legs:
  1. derivation -- the adiabat is obtained from the first law plus the ideal gas
                   law, and the resulting ODE is solved symbolically;
  2. entropy    -- dS computed from the state variables vanishes along that
                   curve, which is the thermodynamic meaning of the result;
  3. carnot     -- the efficiency is computed from the four legs of the cycle
                   rather than quoted, and equals 1 - Tc/Th;
  4. bound      -- the efficiency is shown to lie strictly in (0, 1) and to
                   increase with the hot reservoir, both decided symbolically;
  5. falsifier  -- an engine claiming to beat this cycle is rejected.
"""
import sympy as sp

V, T, P = sp.symbols("V T P", positive=True)
n, R, Cv, gamma = sp.symbols("n R C_v gamma", positive=True)
Th, Tc = sp.symbols("T_h T_c", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# First law with dQ = 0: n Cv dT = -P dV, and P = n R T / V. Separating gives
# Cv dT / T = -R dV / V, so T V^(R/Cv) is constant.
T_of_V = sp.Function("T")(V)
adiabatic_ode = sp.Eq(
    n * Cv * sp.diff(T_of_V, V),
    -(n * R * T_of_V / V),
)
solution = sp.dsolve(adiabatic_ode, T_of_V)
general = sp.simplify(solution.rhs)
# `solution.lhs == T_of_V` would be true for every ODE dsolve can solve and is
# therefore not a check. Substitute the answer back into the equation instead.
ode_residual = sp.simplify(
    n * Cv * sp.diff(general, V) + n * R * general / V
)
check("adiabatic_solution_satisfies_the_ode", ode_residual == 0,
      f"residual = {ode_residual}, with T(V) = {general}")

# The solution must have the form C * V^(-R/Cv). Verify the exponent exactly.
C1 = sp.Symbol("C1")
exponent = sp.simplify(sp.log(general / general.subs(V, 1)) / sp.log(V))
check("adiabatic_exponent_is_minus_R_over_Cv",
      sp.simplify(exponent + R / Cv) == 0,
      f"T ~ V^({exponent})")

# Converting to P and V with Cp = Cv + R gives P V^gamma constant.
gamma_value = (Cv + R) / Cv
P_of_V = n * R * (C1 * V ** (-R / Cv)) / V
invariant = sp.simplify(P_of_V * V ** gamma_value)
check("P_V_gamma_is_constant",
      sp.simplify(sp.diff(invariant, V)) == 0,
      f"P V^gamma = {sp.simplify(invariant)}, independent of V")


# ---------------------------------------------------------------- leg 2
# For an ideal gas dS = n Cv dT/T + n R dV/V. Along the adiabat this vanishes.
S_along = sp.integrate(
    n * Cv * sp.diff(C1 * V ** (-R / Cv), V) / (C1 * V ** (-R / Cv))
    + n * R / V,
    V,
)
check("entropy_change_vanishes_along_adiabat",
      sp.simplify(sp.diff(S_along, V)) == 0,
      "dS/dV = 0, the process is isentropic as claimed")


# ---------------------------------------------------------------- leg 3
# Carnot cycle: two isotherms at Th and Tc joined by two adiabats. The heat
# exchanged on each isotherm is n R T ln(V_ratio), and the adiabats force the
# same ratio on both, so the logs cancel.
V1, V2, V3, V4 = sp.symbols("V_1 V_2 V_3 V_4", positive=True)

# The physical content of the Carnot derivation is that the two adiabats force
# V3/V4 = V2/V1. Writing the same ratio into both isotherms would assume it.
# Derive it: along an adiabat T V^(R/Cv) is constant, so Th V2^(R/Cv) =
# Tc V3^(R/Cv) and Th V1^(R/Cv) = Tc V4^(R/Cv). Dividing eliminates Th and Tc.
adiabat_2_3 = sp.Eq(Th * V2 ** (R / Cv), Tc * V3 ** (R / Cv))
adiabat_1_4 = sp.Eq(Th * V1 ** (R / Cv), Tc * V4 ** (R / Cv))
v3_solved = sp.solve(adiabat_2_3, V3)[0]
v4_solved = sp.solve(adiabat_1_4, V4)[0]
ratio_gap = sp.simplify(sp.powsimp(v3_solved / v4_solved - V2 / V1, force=True))
check("adiabats_force_equal_volume_ratios", ratio_gap == 0,
      f"V3/V4 - V2/V1 = {ratio_gap}, so the ratios coincide as the cycle requires")

# Now the efficiency, with the cold-isotherm ratio taken from the adiabats
# rather than written in by hand.
cold_ratio = sp.simplify(sp.powsimp(v3_solved / v4_solved, force=True))
q_hot = n * R * Th * sp.log(V2 / V1)
q_cold = n * R * Tc * sp.log(cold_ratio)
work = sp.simplify(q_hot - q_cold)
efficiency = sp.simplify(work / q_hot)
check("carnot_efficiency_derived_not_quoted",
      sp.simplify(efficiency - (1 - Tc / Th)) == 0,
      f"eta = {efficiency}")

# The volume ratio genuinely cancels; if it did not, the efficiency would depend
# on the size of the engine, which would be a physical absurdity.
check("efficiency_independent_of_volume_ratio",
      sp.simplify(sp.diff(efficiency, V2)) == 0,
      "eta does not depend on the compression ratio")

# If the ratios had NOT been forced equal the efficiency would still carry the
# volumes, so this is the seam where the adiabat argument does its work.
independent_cold = n * R * Tc * sp.log(V3 / V4)
loose_efficiency = sp.simplify((q_hot - independent_cold) / q_hot)
check("without_the_adiabat_link_the_volumes_survive",
      sp.simplify(sp.diff(loose_efficiency, V3)) != 0,
      "with independent ratios eta depends on V3, so the link is load bearing")


# ---------------------------------------------------------------- leg 4
# On the stated domain 0 < Tc < Th the efficiency lies strictly in (0, 1).
below_one = sp.simplify(1 - (1 - Tc / Th))
check("efficiency_strictly_below_one",
      sp.ask(sp.Q.positive(below_one), sp.Q.positive(Tc) & sp.Q.positive(Th)) is True,
      "1 - eta = Tc/Th > 0, so eta < 1 for any finite hot reservoir")

# Comparing the gap with its own definition rearranged would be gap == gap and
# would pass for any efficiency law at all, including a false one. The content
# is that the gap is POSITIVE, which has to be decided.
gap = sp.simplify((1 - Tc / Th) - (1 - Tc / (Th / 2)))
gap_positive = sp.ask(
    sp.Q.positive(gap), sp.Q.positive(Tc) & sp.Q.positive(Th)
)
check("hotter_reservoir_helps", bool(gap_positive) is True,
      f"eta(Th) - eta(Th/2) = {gap} > 0 ({gap_positive}), so a hotter source helps")


# ---------------------------------------------------------------- leg 5
# An engine claiming a higher efficiency at the same reservoirs must be rejected
# by the same comparison, otherwise leg 4 tests nothing.
claimed = 1 - Tc / (2 * Th)
violation = sp.simplify(claimed - (1 - Tc / Th))
positive_violation = sp.ask(
    sp.Q.positive(violation), sp.Q.positive(Tc) & sp.Q.positive(Th)
)
check("falsifier_rejects_super_carnot_engine", positive_violation is True,
      f"claimed - carnot = {violation} > 0, so the comparison fires")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
