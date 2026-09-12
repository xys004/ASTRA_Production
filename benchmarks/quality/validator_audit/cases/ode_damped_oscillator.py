"""The standard damped-oscillator solution satisfies its equation in all regimes.

CLAIM: x'' + 2*g*x' + w0^2*x = 0 is solved by the textbook forms in the three
regimes g < w0, g = w0 and g > w0, each matching the initial data x(0)=x0,
x'(0)=v0, and the energy of the undamped case is conserved exactly.

Legs:
  1. symbolic   -- each closed form is substituted back and the residual must
                   simplify to exactly zero, per regime;
  2. initial    -- each form reproduces x(0) and x'(0) symbolically;
  3. limit      -- the underdamped form tends to the critical form as g -> w0,
                   which is the regime boundary where a wrong branch shows up;
  4. numerical  -- an independent RK4 integration agrees with the closed form
                   to a tolerance justified by the integrator's own order;
  5. energy     -- in the undamped limit the mechanical energy of the closed
                   form is constant, which is the physical content of g = 0;
  6. falsifier  -- a deliberately wrong damping coefficient is rejected.
"""
import math

import sympy as sp

t = sp.symbols("t", real=True, nonnegative=True)
g, w0, x0, v0 = sp.symbols("gamma omega0 x0 v0", real=True, positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def residual_of(expr, gamma_value, omega_value):
    """Substitute a candidate solution into the ODE and simplify."""
    first = sp.diff(expr, t)
    second = sp.diff(expr, t, 2)
    ode = second + 2 * gamma_value * first + omega_value**2 * expr
    return sp.simplify(sp.expand(sp.simplify(ode)))


# ---------------------------------------------------------------- leg 1
wd = sp.sqrt(w0**2 - g**2)
underdamped = sp.exp(-g * t) * (x0 * sp.cos(wd * t) + (v0 + g * x0) / wd * sp.sin(wd * t))
critical = sp.exp(-g * t) * (x0 + (v0 + g * x0) * t)
r = sp.sqrt(g**2 - w0**2)
overdamped = sp.exp(-g * t) * (
    x0 * sp.cosh(r * t) + (v0 + g * x0) / r * sp.sinh(r * t)
)

under_res = residual_of(underdamped, g, w0)
check("underdamped_residual_zero", under_res == 0, f"residual={under_res}")

crit_res = residual_of(critical, g, g)      # critical means w0 = g
check("critical_residual_zero", crit_res == 0, f"residual={crit_res}")

over_res = residual_of(overdamped, g, w0)
check("overdamped_residual_zero", over_res == 0, f"residual={over_res}")


# ---------------------------------------------------------------- leg 2
initial_ok = True
initial_detail = []
for label, expr, omega in (
    ("underdamped", underdamped, w0),
    ("critical", critical, g),
    ("overdamped", overdamped, w0),
):
    position = sp.simplify(expr.subs(t, 0))
    velocity = sp.simplify(sp.diff(expr, t).subs(t, 0))
    if sp.simplify(position - x0) != 0 or sp.simplify(velocity - v0) != 0:
        initial_ok = False
        initial_detail.append(f"{label}: x(0)={position}, x'(0)={velocity}")
check("initial_conditions_reproduced", initial_ok,
      "; ".join(initial_detail) or "x(0)=x0 and x'(0)=v0 in all three regimes")


# ---------------------------------------------------------------- leg 3
# The underdamped form is singular in appearance at g = w0 because wd -> 0, but
# the limit exists and must equal the critical form. A wrong branch shows up
# exactly here.
limit_expr = sp.limit(underdamped.subs(w0, g + sp.Symbol("d", positive=True)),
                      sp.Symbol("d", positive=True), 0, "+")
limit_gap = sp.simplify(sp.expand(limit_expr - critical))
check("underdamped_tends_to_critical", limit_gap == 0,
      f"limit gap={limit_gap}")


# ---------------------------------------------------------------- leg 4
def rk4(gamma_value, omega_value, x_init, v_init, total, steps):
    """Independent integration. Deliberately not reusing the closed form."""
    h = total / steps
    x, v = x_init, v_init
    for _ in range(steps):
        def accel(xx, vv):
            return -2 * gamma_value * vv - omega_value**2 * xx

        k1x, k1v = v, accel(x, v)
        k2x, k2v = v + 0.5 * h * k1v, accel(x + 0.5 * h * k1x, v + 0.5 * h * k1v)
        k3x, k3v = v + 0.5 * h * k2v, accel(x + 0.5 * h * k2x, v + 0.5 * h * k2v)
        k4x, k4v = v + h * k3v, accel(x + h * k3x, v + h * k3v)
        x += h * (k1x + 2 * k2x + 2 * k3x + k4x) / 6
        v += h * (k1v + 2 * k2v + 2 * k3v + k4v) / 6
    return x


G, W, X0, V0, T_END, STEPS = 0.3, 1.7, 1.25, -0.4, 6.0, 60000
closed = sp.lambdify(t, underdamped.subs({g: G, w0: W, x0: X0, v0: V0}), "math")
analytic_value = closed(T_END)
numeric_value = rk4(G, W, X0, V0, T_END, STEPS)
gap = abs(analytic_value - numeric_value)
# RK4 is fourth order; with this step the truncation floor is far below 1e-9,
# so the tolerance is set by the method rather than chosen to fit.
tolerance = 1e-9
check("rk4_matches_closed_form", gap < tolerance,
      f"|analytic - rk4| = {gap:.3e} < {tolerance:.0e} at t={T_END}")


# ---------------------------------------------------------------- leg 5
# Undamped limit. The symbol g is declared positive, so g = 0 is outside its
# domain and the undamped solution is built with its own symbols rather than by
# substituting into the damped one.
w_und = sp.Symbol("omega_und", positive=True)
x0_und, v0_und = sp.symbols("x0_und v0_und", real=True)
undamped = x0_und * sp.cos(w_und * t) + (v0_und / w_und) * sp.sin(w_und * t)

undamped_residual = sp.simplify(sp.diff(undamped, t, 2) + w_und**2 * undamped)
check("undamped_solution_satisfies_its_equation", undamped_residual == 0,
      f"residual = {undamped_residual}")

energy = sp.simplify(
    sp.diff(undamped, t) ** 2 / 2 + w_und**2 * undamped**2 / 2
)
energy_rate = sp.simplify(sp.diff(energy, t))
check("undamped_energy_is_conserved", energy_rate == 0,
      f"dE/dt = {energy_rate}, with E = {sp.simplify(energy)}")

# The same computation on a damped solution must NOT give zero, otherwise the
# leg above would pass for any motion at all.
damped_energy = sp.diff(underdamped, t) ** 2 / 2 + w0**2 * underdamped**2 / 2
damped_rate = sp.simplify(sp.diff(damped_energy, t))
check("damped_energy_is_not_conserved", sp.simplify(damped_rate) != 0,
      "dE/dt is nonzero once damping is present, as it must be")


# ---------------------------------------------------------------- leg 6
# A wrong damping coefficient must break the residual, or the test is vacuous.
wrong = sp.exp(-2 * g * t) * (x0 * sp.cos(wd * t) + (v0 + g * x0) / wd * sp.sin(wd * t))
wrong_res = residual_of(wrong, g, w0)
check("falsifier_rejects_wrong_damping", sp.simplify(wrong_res) != 0,
      "doubling the damping rate leaves a nonzero residual as it must")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
