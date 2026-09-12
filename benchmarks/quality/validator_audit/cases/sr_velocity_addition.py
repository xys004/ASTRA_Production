"""Relativistic velocity composition never produces a superluminal result.

CLAIM: for |u| < c and |v| < c, w = (u + v) / (1 + u*v/c^2) satisfies |w| < c,
and the composition reduces to u + v in the non-relativistic limit.

Four independent legs:
  1. symbolic   -- c^2 - w^2 factors into manifestly positive pieces on the open
                   domain, and the rapidity substitution turns the bound into
                   |tanh| < 1, which holds for every finite real argument;
  2. numerical  -- fixed-seed draws inside the domain, plus corners evaluated in
                   extended precision where float64 would round to exactly c;
  3. limiting   -- the expansion in 1/c^2 recovers Galilean addition and the
                   first correction carries the sign that slows composition;
  4. falsifier  -- the same test applied to Galilean addition must reject it,
                   which shows the bound check can fail when the law is wrong.
"""
import random

import mpmath as mp
import sympy as sp

# positive=False would ASSERT non-positivity, not leave the question open,
# and would make sqrt(c**2) simplify to -c. The speed of light is positive.
u, v = sp.symbols("u v", real=True)
c = sp.Symbol("c", positive=True)
alpha, beta = sp.symbols("alpha beta", real=True)

W = (u + v) / (1 + u * v / c**2)

FAILURES = []


def check(name, ok, detail=""):
    """Record one leg. A leg that is not decidably true counts as a failure."""
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1a
# c^2 - w^2 = (c^2 - u^2)(c^2 - v^2) c^2 / (c^2 + u v)^2. Each factor on the
# right is strictly positive when |u| < c and |v| < c, so |w| < c follows
# exactly rather than by sampling.
difference = sp.simplify(c**2 - W**2)
expected_form = (c**2 - u**2) * (c**2 - v**2) * c**2 / (c**2 + u * v) ** 2
residual = sp.simplify(sp.together(difference - expected_form))
check("symbolic_factorization", residual == 0, f"residual={residual}")

# ---------------------------------------------------------------- leg 1b
# The factorization is only decisive if the denominator cannot vanish. Writing
# u = c*tanh(alpha), v = c*tanh(beta) parametrizes exactly the open domain, and
# the composition collapses to c*tanh(alpha + beta). |tanh| < 1 for every finite
# real argument, so the bound holds on the whole domain with no case analysis.
rapidity = W.subs({u: c * sp.tanh(alpha), v: c * sp.tanh(beta)})
collapsed = sp.simplify(sp.expand_trig(sp.simplify(rapidity)) - c * sp.tanh(alpha + beta))
check(
    "rapidity_collapse",
    sp.simplify(collapsed) == 0,
    "w = c*tanh(alpha+beta) on the open domain",
)

# tanh maps the whole real line strictly inside (-1, 1). Two decisive forms:
# the Pythagorean identity rewrites the gap as 1/cosh^2, which is positive
# because cosh is, and the violation set is solved directly and comes back
# empty. Neither is a sample.
identity_gap = sp.simplify(1 - sp.tanh(alpha) ** 2 - 1 / sp.cosh(alpha) ** 2)
cosh_positive = sp.ask(sp.Q.positive(sp.cosh(alpha)))
check(
    "tanh_gap_is_sech_squared",
    identity_gap == 0 and cosh_positive is True,
    f"1 - tanh^2 = 1/cosh^2 with cosh > 0 ({cosh_positive})",
)

violations = sp.solveset(sp.tanh(alpha) ** 2 >= 1, alpha, sp.S.Reals)
check(
    "tanh_violation_set_empty",
    violations == sp.S.EmptySet,
    f"solveset(tanh^2 >= 1) = {violations}",
)


# ---------------------------------------------------------------- leg 2
def compose(a, b, speed=1.0):
    return (a + b) / (1 + a * b / speed**2)


random.seed(20260911)
worst = 0.0
numeric_ok = True
for _ in range(4000):
    a = random.uniform(-0.999999, 0.999999)
    b = random.uniform(-0.999999, 0.999999)
    w = compose(a, b)
    worst = max(worst, abs(w))
    if not abs(w) < 1.0:
        numeric_ok = False
        break
check("numeric_subluminal", numeric_ok and worst < 1.0,
      f"max|w|={worst:.12f} over 4000 draws")

# Near the boundary float64 rounds 2a/(1+a^2) to exactly 1.0, which would be a
# precision artefact rather than a physical violation. Extended precision keeps
# the strict inequality visible where it is tightest.
mp.mp.dps = 60
corner_ok = True
corner_detail = ""
for exponent in (3, 6, 9, 12, 15):
    a = mp.mpf(1) - mp.mpf(10) ** (-exponent)
    w = (a + a) / (1 + a * a)
    if not (w < 1 and w > a):
        corner_ok = False
        corner_detail = f"failed at 1-1e-{exponent}"
        break
    corner_detail = f"tightest gap 1-w = {mp.nstr(1 - w, 8)}"
check("numeric_corners_extended_precision", corner_ok, corner_detail)


# ---------------------------------------------------------------- leg 3
series = sp.series(W, c, sp.oo, 3).removeO()
galilean = sp.simplify(series.subs(1 / c, 0))
check("galilean_limit", sp.simplify(galilean - (u + v)) == 0,
      f"leading term={galilean}")

correction = sp.simplify(sp.expand(series) - (u + v))
leading = sp.simplify(correction * c**2)
check("first_correction_sign", sp.simplify(leading + u * v * (u + v)) == 0,
      f"c^2 * correction={leading}")


# ---------------------------------------------------------------- leg 4
# The bound check must be capable of rejecting a wrong composition law. The
# Galilean rule is evaluated through a helper with the same signature as
# compose, so the falsifier exercises the comparison rather than arithmetic
# written out by hand.
def compose_galilean(a, b, speed=1.0):
    return a + b


galilean_worst = max(abs(compose_galilean(0.9, 0.9)),
                     abs(compose_galilean(0.99, 0.99)))
check("falsifier_rejects_galilean", galilean_worst > 1.0,
      f"Galilean composition reaches {galilean_worst:.2f}c and is rejected")

# And the relativistic law applied to the same inputs stays inside.
relativistic_same = compose(0.9, 0.9)
check("relativistic_same_inputs_inside", abs(relativistic_same) < 1.0,
      f"w(0.9,0.9)={relativistic_same:.9f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
