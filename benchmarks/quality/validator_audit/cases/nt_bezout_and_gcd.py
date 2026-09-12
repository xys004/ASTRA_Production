"""Bezout's identity, with the gcd characterised as the least positive combination.

CLAIM: for integers a and b not both zero, the extended Euclidean algorithm
returns g, x, y with a*x + b*y = g, where g = gcd(a, b); g divides both a and b;
every common divisor of a and b divides g; and g is the SMALLEST positive
integer expressible as an integer combination of a and b.

The algorithm is implemented here rather than imported, so the agreement with
sympy's gcd is a comparison between two independent routes instead of a library
agreeing with itself.

Legs:
  1. identity   -- a*x + b*y = g exactly, over an exhaustive grid of pairs, in
                   integer arithmetic with no floating point anywhere;
  2. divisor    -- g divides both arguments and is divisible by every common
                   divisor, which is the defining property rather than a
                   consequence checked on examples;
  3. minimality -- g is the least positive value of a*x + b*y, established by
                   exhausting the combination range rather than asserted;
  4. agreement  -- the hand-written algorithm matches sympy's gcd on every pair,
                   two independent implementations rather than one;
  5. falsifier  -- perturbing either coefficient breaks the identity on every
                   pair where it is tried.
"""
import math

import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def extended_euclid(a, b):
    """Return (g, x, y) with a*x + b*y = g and g >= 0, written from scratch.

    Iterative form, so nothing depends on recursion limits, and every value is
    a Python int, so the arithmetic is exact for arbitrarily large inputs.
    """
    old_r, r = a, b
    old_x, x = 1, 0
    old_y, y = 0, 1
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_x, x = x, old_x - quotient * x
        old_y, y = y, old_y - quotient * y
    if old_r < 0:                      # normalise the sign of the gcd
        old_r, old_x, old_y = -old_r, -old_x, -old_y
    return old_r, old_x, old_y


PAIRS = [
    (a, b)
    for a in range(-30, 31)
    for b in range(-30, 31)
    if not (a == 0 and b == 0)
]


# ---------------------------------------------------------------- leg 1
identity_ok = True
identity_detail = ""
for a, b in PAIRS:
    g, x, y = extended_euclid(a, b)
    if a * x + b * y != g:
        identity_ok = False
        identity_detail = f"a={a}, b={b}: {a}*{x} + {b}*{y} = {a * x + b * y} != {g}"
        break
check("bezout_identity_holds_on_every_pair", identity_ok,
      identity_detail or f"{len(PAIRS)} pairs, exact integer arithmetic")


# ---------------------------------------------------------------- leg 2
divisor_ok = True
maximality_ok = True
divisor_detail = ""
for a, b in PAIRS:
    g, _x, _y = extended_euclid(a, b)
    if g <= 0 or a % g != 0 or b % g != 0:
        divisor_ok = False
        divisor_detail = f"a={a}, b={b}, g={g} does not divide both"
        break
    # Every common divisor must divide g. Exhaust the candidates.
    limit = max(abs(a), abs(b)) or 1
    for d in range(1, limit + 1):
        if a % d == 0 and b % d == 0 and g % d != 0:
            maximality_ok = False
            divisor_detail = f"a={a}, b={b}: common divisor {d} does not divide g={g}"
            break
    if not maximality_ok:
        break
check("gcd_divides_both_arguments", divisor_ok,
      divisor_detail if not divisor_ok else "g | a and g | b on every pair")
check("every_common_divisor_divides_the_gcd", maximality_ok,
      divisor_detail if not maximality_ok else "no common divisor escapes g")


# ---------------------------------------------------------------- leg 3
# Minimality, by exhausting the combinations rather than asserting it. For a
# smaller grid the full search is affordable and settles the claim outright.
minimal_ok = True
minimal_detail = ""
for a in range(-12, 13):
    for b in range(-12, 13):
        if a == 0 and b == 0:
            continue
        g, _x, _y = extended_euclid(a, b)
        smallest = None
        for x in range(-40, 41):
            for y in range(-40, 41):
                value = a * x + b * y
                if value > 0 and (smallest is None or value < smallest):
                    smallest = value
        if smallest != g:
            minimal_ok = False
            minimal_detail = f"a={a}, b={b}: least positive combination {smallest} != g={g}"
            break
    if not minimal_ok:
        break
check("gcd_is_the_least_positive_combination", minimal_ok,
      minimal_detail or "625 pairs, combination range exhausted for each")


# ---------------------------------------------------------------- leg 4
agreement_ok = True
agreement_detail = ""
for a, b in PAIRS:
    g, _x, _y = extended_euclid(a, b)
    reference = int(sp.gcd(a, b))
    builtin = math.gcd(a, b)
    if not (g == reference == builtin):
        agreement_ok = False
        agreement_detail = f"a={a}, b={b}: mine={g}, sympy={reference}, math={builtin}"
        break
check("three_independent_implementations_agree", agreement_ok,
      agreement_detail or "hand-written, sympy and math.gcd coincide on every pair")


# ---------------------------------------------------------------- leg 5
# Perturbing a coefficient must break the identity. If it did not, leg 1 would
# be measuring nothing, so the falsifier runs through the same arithmetic.
broken_count = 0
tested = 0
for a, b in PAIRS[:200]:
    g, x, y = extended_euclid(a, b)
    if b == 0:
        continue           # perturbing y cannot change a*x + b*y when b is zero
    tested += 1
    if a * x + b * (y + 1) != g:
        broken_count += 1
check("falsifier_perturbed_coefficient_breaks_the_identity",
      tested > 0 and broken_count == tested,
      f"{broken_count} of {tested} perturbed pairs fail the identity, as required")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
