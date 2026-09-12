"""Fermat's little theorem holds, and its converse does not.

CLAIM: for prime p and a not divisible by p, a^(p-1) = 1 (mod p). The converse
fails: there are composite n for which a^(n-1) = 1 (mod n) for every a coprime
to n, the Carmichael numbers, of which 561 is the smallest.

Legs:
  1. exhaustive -- for small primes, every admissible residue is checked, not a
                   sample, so the statement is settled on those primes;
  2. wide       -- larger primes with many bases, using exact modular arithmetic;
  3. converse   -- 561 passes the Fermat test for every coprime base yet factors
                   as 3*11*17, which is what stops the test being a primality
                   proof;
  4. falsifier  -- a composite that is not Carmichael is caught, showing the
                   test has power when it applies.
"""
import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def fermat_holds(base, modulus):
    """Exact modular exponentiation. No floating point anywhere."""
    return pow(base, modulus - 1, modulus) == 1


# ---------------------------------------------------------------- leg 1
SMALL_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
exhaustive_ok = True
counterexample = ""
checked = 0
for p in SMALL_PRIMES:
    if not sp.isprime(p):
        exhaustive_ok = False
        counterexample = f"{p} is not prime"
        break
    for base in range(1, p):          # every residue coprime to p
        checked += 1
        if not fermat_holds(base, p):
            exhaustive_ok = False
            counterexample = f"a={base}, p={p}"
            break
    if not exhaustive_ok:
        break
check("exhaustive_over_small_primes", exhaustive_ok,
      counterexample or f"{checked} base/prime pairs, every residue covered")


# ---------------------------------------------------------------- leg 2
LARGER_PRIMES = [101, 257, 1009, 7919, 104729]
wide_ok = True
wide_detail = ""
tested = 0
for p in LARGER_PRIMES:
    if not sp.isprime(p):
        wide_ok = False
        wide_detail = f"{p} is not prime"
        break
    for base in (2, 3, 5, 7, 10, 11, p - 1, p - 2, (p // 2) | 1):
        if base % p == 0:
            continue
        tested += 1
        if not fermat_holds(base, p):
            wide_ok = False
            wide_detail = f"a={base}, p={p}"
            break
    if not wide_ok:
        break
check("wide_bases_on_larger_primes", wide_ok,
      wide_detail or f"{tested} exponentiations, largest modulus 104729")

# The theorem needs the coprimality hypothesis. Dropping it must break the
# conclusion, otherwise the hypothesis is decorative.
non_coprime_breaks = pow(7, 6, 7) != 1
check("coprimality_hypothesis_is_necessary", non_coprime_breaks,
      f"7^6 mod 7 = {pow(7, 6, 7)}, not 1, as the hypothesis requires")


# ---------------------------------------------------------------- leg 3
CARMICHAEL = 561
factors = sp.factorint(CARMICHAEL)
composite = not sp.isprime(CARMICHAEL)
check("carmichael_is_composite", composite and factors == {3: 1, 11: 1, 17: 1},
      f"561 = {dict(factors)}")

carmichael_fools_test = True
coprime_bases = 0
for base in range(2, CARMICHAEL):
    if sp.gcd(base, CARMICHAEL) != 1:
        continue
    coprime_bases += 1
    if not fermat_holds(base, CARMICHAEL):
        carmichael_fools_test = False
        break
check("carmichael_passes_for_every_coprime_base", carmichael_fools_test,
      f"{coprime_bases} coprime bases, all satisfy a^560 = 1 (mod 561)")

# So the converse is false, and the validator states the limit of the theorem
# rather than overselling it.
check("converse_is_false", composite and carmichael_fools_test,
      "passing the Fermat test does not establish primality")


# ---------------------------------------------------------------- leg 4
# On a composite that is not Carmichael the test does have power, and must
# actually fire. Otherwise leg 3 would be indistinguishable from a broken test.
NON_CARMICHAEL = 15
witnesses = [
    base for base in range(2, NON_CARMICHAEL)
    if sp.gcd(base, NON_CARMICHAEL) == 1 and not fermat_holds(base, NON_CARMICHAEL)
]
check("falsifier_catches_ordinary_composite", len(witnesses) > 0,
      f"{len(witnesses)} Fermat witnesses for 15, e.g. a={witnesses[0] if witnesses else '-'}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
