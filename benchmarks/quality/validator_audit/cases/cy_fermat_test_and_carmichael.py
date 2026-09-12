"""A test no base can fail: Carmichael numbers and the Fermat primality test.

CLAIM: Fermat's little theorem holds for every prime and every base coprime to
it; its converse is false, and for a Carmichael number it fails as badly as
possible, since EVERY base coprime to n satisfies the congruence, so no amount of
retrying can expose one; Korselt's criterion says exactly which numbers do this;
and Miller-Rabin does catch them, because it also asks for square roots of one,
with at least three quarters of the bases acting as witnesses.

This is the cleanest instance in the corpus of a check that passes and proves
nothing. The Fermat test on 561 is not a weak test, it is a test whose failure
branch is unreachable, and running it on more bases cannot help.

Legs:
  1. fermat    -- the little theorem verified exhaustively, so over this range it
                  is a proof and not a sample;
  2. converse  -- 561 is composite and passes base two;
  3. korselt   -- the criterion is checked for three Carmichael numbers and
                  shown to fail for a composite that is not one;
  4. subgroup  -- the bases that fail to expose n form a subgroup of the units,
                  and for a Carmichael number it is the whole group;
  5. contrast  -- on an ordinary composite that subgroup is proper, so it holds
                  at most half the units, and the closure that forces the bound
                  is verified rather than cited;
  6. falsifier -- Miller-Rabin catches all three, the witness fraction clears
                  three quarters, and the mechanism is a nontrivial square root
                  of one, exhibited.
"""
import math

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def is_prime(number):
    """Trial division. Slow and obviously correct, which is what is wanted here."""
    if number < 2:
        return False
    for candidate in range(2, int(math.isqrt(number)) + 1):
        if number % candidate == 0:
            return False
    return True


def factorise(number):
    """Prime factorisation with multiplicity, by trial division."""
    factors = {}
    remaining = number
    divisor = 2
    while divisor * divisor <= remaining:
        while remaining % divisor == 0:
            factors[divisor] = factors.get(divisor, 0) + 1
            remaining //= divisor
        divisor += 1
    if remaining > 1:
        factors[remaining] = factors.get(remaining, 0) + 1
    return factors


# ---------------------------------------------------------------- leg 1
# Over this range the loop covers every case, so the statement is established
# for these primes rather than sampled. That distinction is the whole subject of
# the case, and it would be dishonest to blur it: nothing here proves the
# theorem in general.
PRIMES = [p for p in range(2, 60) if is_prime(p)]
violations = [
    (base, prime)
    for prime in PRIMES
    for base in range(1, prime)
    if pow(base, prime - 1, prime) != 1
]
check("fermats_little_theorem_holds_for_every_prime_and_base_in_range",
      violations == [],
      f"checked every one of the "
      f"{sum(p - 1 for p in PRIMES)} base and prime pairs up to {PRIMES[-1]}, "
      "which settles those primes and asserts nothing beyond them")


# ---------------------------------------------------------------- leg 2
CARMICHAELS = [561, 1105, 1729]
check("the_first_carmichael_number_is_composite",
      not is_prime(561) and factorise(561) == {3: 1, 11: 1, 17: 1},
      f"561 = {factorise(561)}")

check("yet_it_passes_the_fermat_test_at_base_two",
      pow(2, 560, 561) == 1,
      f"2^560 mod 561 = {pow(2, 560, 561)}, the answer a prime would give")


# ---------------------------------------------------------------- leg 3
def korselt(number):
    """Squarefree, and p - 1 divides n - 1 for every prime factor p."""
    factors = factorise(number)
    squarefree = all(power == 1 for power in factors.values())
    divides = all((number - 1) % (prime - 1) == 0 for prime in factors)
    return squarefree and divides


for candidate in CARMICHAELS:
    check(f"korselt_holds_for_{candidate}",
          korselt(candidate) and not is_prime(candidate),
          f"{candidate} = {factorise(candidate)}, each p - 1 dividing "
          f"{candidate - 1}")

# And it must fail for something. 15 is squarefree and composite, but 4 does not
# divide 14, so the criterion separates rather than accepting everything.
check("korselt_fails_for_a_composite_that_is_not_carmichael",
      not korselt(15) and not korselt(9),
      f"15 = {factorise(15)} fails the divisibility, 9 = {factorise(9)} fails "
      "squarefreeness")


# ---------------------------------------------------------------- leg 4
def units(number):
    """The bases coprime to n, which are the units of the ring modulo n."""
    return [a for a in range(1, number) if math.gcd(a, number) == 1]


def fermat_liars(number):
    """Units that FAIL to expose n.

    Bases sharing a factor with n are left out on purpose: such a base exposes n
    through the greatest common divisor, which means having already factored it,
    so it is not something the test contributes.

    These liars form a subgroup of the units, which is the fact that decides
    everything below. If even one unit exposes n the subgroup is proper, so its
    index is at least two and it can hold at most half the units. A Carmichael
    number is precisely one where the subgroup is not proper at all.
    """
    return [a for a in units(number) if pow(a, number - 1, number) == 1]


for candidate in CARMICHAELS:
    total = len(units(candidate))
    liars = fermat_liars(candidate)
    check(f"the_liars_modulo_{candidate}_are_every_last_unit",
          len(liars) == total,
          f"all {total} units lie, so the subgroup is the whole group, there is "
          "no witness to find and retrying with more bases cannot help")


# ---------------------------------------------------------------- leg 5
# The contrast, and the sharp form of it: on an ordinary composite the liars are
# a PROPER subgroup, so they cannot exceed half the units. The bound is the
# theorem; here it is attained exactly, at index two.
ORDINARY = 91
ordinary_units = len(units(ORDINARY))
ordinary_liars = fermat_liars(ORDINARY)
# Two separate statements, because they are two. That the subgroup is proper is
# what a single witness establishes; that it holds at most half the units is the
# sharp bound, and folding them into one check would let the sharp half go
# missing while the conjunction still passed on the weak half.
check("an_ordinary_composite_has_a_proper_liar_subgroup",
      len(ordinary_liars) < ordinary_units,
      f"{len(ordinary_liars)} liars among {ordinary_units} units modulo "
      f"{ORDINARY} = {factorise(ORDINARY)}, so at least one unit exposes it")

check("and_that_subgroup_holds_at_most_half_the_units",
      len(ordinary_liars) <= ordinary_units // 2,
      f"{len(ordinary_liars)} against the {ordinary_units // 2} a proper "
      f"subgroup can hold; the index is "
      f"{ordinary_units // len(ordinary_liars)}, so the bound is attained")

check("and_the_liars_really_do_form_a_subgroup_there",
      all((first * second) % ORDINARY in ordinary_liars
          for first in ordinary_liars for second in ordinary_liars),
      f"the {len(ordinary_liars)} liars are closed under multiplication modulo "
      f"{ORDINARY}, which is what forces the index and hence the bound")


# ---------------------------------------------------------------- leg 6
def miller_rabin_witness(number, base):
    """Does this base expose n, either by Fermat or by a square root of one?"""
    exponent = number - 1
    twos = 0
    while exponent % 2 == 0:
        exponent //= 2
        twos += 1
    value = pow(base, exponent, number)
    if value in (1, number - 1):
        return False
    for _ in range(twos - 1):
        value = pow(value, 2, number)
        if value == number - 1:
            return False
    return True


# Counted over ALL bases in the usual range, not only the coprime ones. A base
# sharing a factor with n is a witness too, and the three quarters of Monier and
# Rabin is a statement about every base; restricting the count to units while
# dividing by all of them would understate it badly.
for candidate in CARMICHAELS:
    population = list(range(2, candidate - 1))
    caught = [a for a in population if miller_rabin_witness(candidate, a)]
    check(f"falsifier_miller_rabin_exposes_{candidate}",
          len(caught) >= 0.75 * len(population),
          f"{len(caught)} witnesses among {len(population)} bases, a fraction of "
          f"{len(caught) / len(population):.4f}, clearing the three quarters "
          "the theorem guarantees for any odd composite")

# The mechanism, exhibited rather than described: somewhere in the squaring chain
# a base produces a square root of one that is neither 1 nor n - 1, which cannot
# happen modulo a prime.
def nontrivial_root(number, base):
    exponent = number - 1
    twos = 0
    while exponent % 2 == 0:
        exponent //= 2
        twos += 1
    value = pow(base, exponent, number)
    for _ in range(twos):
        squared = pow(value, 2, number)
        if squared == 1 and value not in (1, number - 1):
            return value
        value = squared
    return 0


roots = [(base, nontrivial_root(561, base)) for base in range(2, 561)]
found_roots = [(base, root) for base, root in roots if root != 0]
check("a_nontrivial_square_root_of_one_exists_modulo_561",
      len(found_roots) > 0
      and all(pow(root, 2, 561) == 1 and root not in (1, 560)
              for _, root in found_roots),
      f"{len(found_roots)} bases produce one, the first being base "
      f"{found_roots[0][0]} with root {found_roots[0][1]}, whose square is "
      f"{pow(found_roots[0][1], 2, 561)} modulo 561")

# A test that called everything a witness would satisfy the lower bounds above
# while being useless, so the specificity side has to be checked too: on an
# actual prime Miller-Rabin must accuse nobody.
# 577 rather than a prime like 563: 562 carries a single factor of two, so the
# square root chain never runs and a Miller-Rabin with that chain deleted would
# still accuse nobody. 576 is 2^6 times 9, so the chain is exercised and the
# control has something to control.
PRIME_CONTROL = 577
false_accusations = [
    base for base in range(2, PRIME_CONTROL - 1)
    if miller_rabin_witness(PRIME_CONTROL, base)
]
check("and_accuses_no_base_when_the_number_is_prime",
      false_accusations == [] and is_prime(PRIME_CONTROL),
      f"{PRIME_CONTROL} is prime and {len(false_accusations)} of its "
      f"{PRIME_CONTROL - 3} bases are witnesses, so the three quarters above is "
      "selectivity and not indiscriminate accusation")


# Modulo a prime the same search must come up empty, since a field has only the
# two square roots of one. That is what makes the finding above evidence.
prime_roots = [
    base for base in range(2, PRIME_CONTROL)
    if nontrivial_root(PRIME_CONTROL, base) != 0
]
check("and_no_such_root_exists_modulo_a_prime",
      prime_roots == [] and is_prime(PRIME_CONTROL),
      f"{PRIME_CONTROL} is prime and {len(prime_roots)} bases produce a "
      "nontrivial root, as a field permits only plus and minus one")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
