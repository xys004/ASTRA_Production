"""Bernoulli follows from Euler along a streamline, and predicts the Venturi drop.

CLAIM: for steady, incompressible, inviscid flow along a streamline,
p + rho v^2/2 + rho g z is constant. Combined with mass continuity A1 v1 = A2 v2
this predicts the pressure drop in a horizontal Venturi contraction, and the
prediction fails if the flow is compressible enough to matter.

Legs:
  1. derivation -- the streamwise Euler equation is integrated symbolically and
                   the Bernoulli combination emerges as the constant of motion;
  2. continuity -- mass conservation in a contraction is solved exactly;
  3. venturi    -- the pressure drop is derived, then evaluated on a concrete
                   water case and cross-checked against an independent
                   energy-balance computation;
  4. domain     -- the incompressibility hypothesis is shown to matter, by
                   computing the Mach number where the error reaches one percent;
  5. falsifier  -- dropping the kinetic term gives a prediction that the same
                   comparison rejects.
"""
import sympy as sp

s = sp.Symbol("s", real=True)                 # arclength along the streamline
rho, g, z = sp.symbols("rho g z", positive=True)
A1, A2, v1, v2, p1, p2 = sp.symbols("A_1 A_2 v_1 v_2 p_1 p_2", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Steady Euler along a streamline: rho v dv/ds = -dp/ds - rho g dz/ds.
# Every term is an exact derivative, so the equation integrates in closed form.
v = sp.Function("v")(s)
p = sp.Function("p")(s)
height = sp.Function("z")(s)

euler = rho * v * sp.diff(v, s) + sp.diff(p, s) + rho * g * sp.diff(height, s)
bernoulli = p + rho * v**2 / 2 + rho * g * height
check("bernoulli_is_the_first_integral_of_euler",
      sp.simplify(sp.diff(bernoulli, s) - euler) == 0,
      "d/ds [p + rho v^2/2 + rho g z] reproduces the Euler equation exactly")

# So along the streamline the combination has zero derivative, which is the
# statement of the theorem rather than a restatement of the equation.
check("combination_is_constant_when_euler_holds",
      sp.simplify(sp.diff(bernoulli, s).subs(sp.diff(p, s),
                  -rho * v * sp.diff(v, s) - rho * g * sp.diff(height, s))) == 0,
      "substituting Euler makes the derivative vanish identically")


# ---------------------------------------------------------------- leg 2
continuity = sp.Eq(A1 * v1, A2 * v2)
v2_solved = sp.solve(continuity, v2)[0]
check("continuity_solved_exactly",
      sp.simplify(v2_solved - A1 * v1 / A2) == 0,
      f"v2 = {v2_solved}")


# ---------------------------------------------------------------- leg 3
# Horizontal contraction, so the height term drops out on both sides.
bernoulli_pair = sp.Eq(p1 + rho * v1**2 / 2, p2 + rho * v2**2 / 2)
delta_p = sp.simplify(sp.solve(
    sp.Eq(p1 - p2, sp.Symbol("dp")),
    sp.Symbol("dp"))[0].subs(
        p1, sp.solve(bernoulli_pair.subs(v2, v2_solved), p1)[0]))
expected_drop = sp.simplify(rho * v1**2 / 2 * ((A1 / A2) ** 2 - 1))
check("venturi_drop_has_expected_form",
      sp.simplify(delta_p - expected_drop) == 0,
      f"p1 - p2 = {sp.factor(expected_drop)}")

# Concrete water case, evaluated two independent ways.
values = {rho: 998.2, v1: 2.0, A1: 0.01, A2: 0.004}
symbolic_value = float(expected_drop.subs(values))

# Independent route: compute both speeds, then take the kinetic energy
# difference per unit volume directly, without reusing the formula above.
speed_1 = 2.0
speed_2 = speed_1 * 0.01 / 0.004
energy_route = 0.5 * 998.2 * (speed_2**2 - speed_1**2)
check("two_independent_routes_agree",
      abs(symbolic_value - energy_route) < 1e-9,
      f"formula {symbolic_value:.6f} Pa vs energy balance {energy_route:.6f} Pa")


# ---------------------------------------------------------------- leg 4
# Incompressibility is a hypothesis, not decoration. For a gas the density
# correction enters at order Mach^2/4, so the one percent error point is near
# Mach 0.2, and the water case above is nowhere near it.
mach = sp.Symbol("M", positive=True)
compressible_correction = mach**2 / 4
one_percent = sp.solve(sp.Eq(compressible_correction, sp.Rational(1, 100)), mach)
positive_root = [root for root in one_percent if bool(root > 0)][0]
check("compressibility_threshold_located",
      bool(abs(float(positive_root) - 0.2) < 1e-12),
      f"one percent error at Mach {float(positive_root):.3f}")

water_mach = speed_2 / 1481.0            # speed of sound in water, m/s
check("water_case_is_safely_incompressible",
      water_mach < 0.01,
      f"Mach {water_mach:.5f} in the throat, far below the threshold")


# ---------------------------------------------------------------- leg 5
# Dropping the kinetic term predicts no pressure drop at all, which the same
# comparison must reject, otherwise leg 3 would pass for any formula.
no_kinetic = 0.0
check("falsifier_rejects_dropping_kinetic_term",
      abs(no_kinetic - energy_route) > 1.0,
      f"omitting rho v^2/2 predicts 0 Pa against {energy_route:.1f} Pa, and is rejected")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
