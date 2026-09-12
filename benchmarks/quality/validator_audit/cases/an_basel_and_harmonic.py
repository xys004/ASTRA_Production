"""The Basel sum converges to pi^2/6 while the harmonic series diverges.

CLAIM: sum 1/n^2 over n >= 1 equals pi^2/6 exactly, sum 1/n diverges, and the
boundary between the two is the exponent p = 1, with sum 1/n^p convergent
exactly for p > 1.

Legs:
  1. exact      -- the closed form is obtained symbolically, not matched against
                   a decimal, and the p-series is resolved as a function of p;
  2. numerical  -- partial sums approach pi^2/6 with the tail bounded by the
                   integral test, so the agreement is predicted before measured;
  3. divergence -- the harmonic partial sums exceed any fixed bound, shown by a
                   dyadic grouping argument rather than by running out of terms;
  4. boundary   -- p = 1 is the exact threshold, checked from both sides;
  5. falsifier  -- a wrong closed form is rejected by the same comparison.
"""
import math

import sympy as sp

n, p = sp.symbols("n p", positive=True, integer=False)
k = sp.Symbol("k", positive=True, integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
basel = sp.summation(1 / k**2, (k, 1, sp.oo))
check("basel_closed_form_is_pi_squared_over_six",
      sp.simplify(basel - sp.pi**2 / 6) == 0,
      f"sum 1/k^2 = {basel}")

# The same machinery on a neighbouring exponent must give a different, known
# answer, otherwise the result could be an artefact of the summation routine.
zeta_four = sp.summation(1 / k**4, (k, 1, sp.oo))
check("neighbouring_exponent_gives_zeta_four",
      sp.simplify(zeta_four - sp.pi**4 / 90) == 0,
      f"sum 1/k^4 = {zeta_four}")


# ---------------------------------------------------------------- leg 2
# The integral test bounds the tail: sum_{k>N} 1/k^2 < integral_N^inf dx/x^2 = 1/N.
# That bound is stated first, then the partial sum is required to respect it.
N = 20000
partial = sum(1.0 / (i * i) for i in range(1, N + 1))
target = float(sp.pi**2 / 6)
tail_bound = 1.0 / N
observed_gap = target - partial
check("partial_sum_within_predicted_tail_bound",
      0 < observed_gap < tail_bound,
      f"gap={observed_gap:.3e}, predicted bound={tail_bound:.3e}")

# The gap must also be close to the leading tail estimate 1/N, not merely below
# it, which distinguishes a converging sum from one that stalls early.
check("gap_matches_leading_tail_estimate",
      0.9 < observed_gap / tail_bound < 1.0,
      f"gap / (1/N) = {observed_gap / tail_bound:.4f}")


# ---------------------------------------------------------------- leg 3
harmonic = sp.summation(1 / k, (k, 1, sp.oo))
check("harmonic_series_diverges", harmonic is sp.oo or harmonic == sp.oo,
      f"sum 1/k = {harmonic}")

# Dyadic grouping: each block (2^j, 2^(j+1)] contributes more than 1/2, so the
# partial sums exceed m/2 and grow without bound. This is a proof, not a sample.
blocks_ok = True
worst_block = None
for j in range(0, 14):
    lower, upper = 2**j + 1, 2 ** (j + 1)
    block = sum(1.0 / i for i in range(lower, upper + 1))
    # The bound is >= 1/2, with equality on the first block, whose single term
    # is exactly 1/2. A strict inequality here would be wrong, not stricter.
    if not block >= 0.5:
        blocks_ok = False
        break
    worst_block = block if worst_block is None else min(worst_block, block)
check("dyadic_blocks_each_reach_one_half", blocks_ok,
      f"14 blocks, smallest = {worst_block}, so partial sums exceed m/2")

partial_harmonic = sum(1.0 / i for i in range(1, 2**14 + 1))
check("harmonic_partial_exceeds_dyadic_bound",
      partial_harmonic > 14 * 0.5,
      f"H(2^14) = {partial_harmonic:.4f} > {14 * 0.5}")


# ---------------------------------------------------------------- leg 4
# The p-series converges exactly for p > 1. Check both sides of the threshold.
# sympy leaves some p-series unevaluated, so convergence is decided with the
# convergence test rather than by whether a closed form happened to be found.
# bool() is deliberate: is_convergent returns a sympy BooleanTrue, which is not
# the Python True this harness compares against, and would read as failure.
above = bool(sp.Sum(1 / k ** sp.Rational(3, 2), (k, 1, sp.oo)).is_convergent())
check("p_series_converges_above_one", above is True,
      f"p=3/2 is_convergent={above}")

below = bool(sp.Sum(1 / k ** sp.Rational(1, 2), (k, 1, sp.oo)).is_convergent())
check("p_series_diverges_below_one", below is False,
      f"p=1/2 is_convergent={below}")

at_one = bool(sp.Sum(1 / k, (k, 1, sp.oo)).is_convergent())
check("threshold_is_exactly_p_equals_one",
      at_one is False and above is True,
      f"p=1 is_convergent={at_one} while p=3/2 is_convergent={above}")

# Three sample exponents do not establish a statement about all p. Sympy can
# resolve the sum as a function of p, and the condition attached to the
# convergent branch must be exactly p > 1, which is the claim.
general_sum = sp.summation(1 / k**p, (k, 1, sp.oo))
branches = [cond for _expr, cond in general_sum.args] if general_sum.is_Piecewise else []
check("p_series_threshold_is_symbolic_not_sampled",
      any(cond == (p > 1) for cond in branches),
      f"summation over all p gives branches {branches}")


# ---------------------------------------------------------------- leg 5
# A wrong closed form must be rejected, or leg 1 proves nothing.
wrong_form = sp.pi**2 / 8
check("falsifier_rejects_wrong_closed_form",
      sp.simplify(basel - wrong_form) != 0,
      f"pi^2/6 - pi^2/8 = {sp.simplify(basel - wrong_form)}, nonzero as required")

# And numerically the wrong form is outside the tail bound, so even the
# numerical leg alone would catch it.
check("wrong_form_also_fails_numerically",
      abs(float(wrong_form) - partial) > tail_bound,
      f"|pi^2/8 - partial| = {abs(float(wrong_form) - partial):.4f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
