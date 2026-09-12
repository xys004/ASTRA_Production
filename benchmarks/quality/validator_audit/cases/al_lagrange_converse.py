"""Lagrange's theorem holds and its converse does not, with the gap enumerated.

CLAIM: in a finite group the order of every subgroup divides the order of the
group, because the left cosets of a subgroup partition the group into blocks of
equal size; the converse, that every divisor is the order of some subgroup, is
false, and the smallest counterexample is the alternating group on four letters,
which has order twelve and subgroups of orders one, two, three, four and twelve
but none of order six; the reason is structural, since a subgroup of index two
would have to be normal and the only normal subgroups here have orders one, four
and twelve; and for cyclic groups the converse is true, so the failure belongs to
the group and not to small orders in general.

Everything is decided by exhaustive enumeration over a group of twelve elements,
so the statements about this group are settled rather than sampled. Nothing here
claims anything about groups in general except what the coset argument proves.

Legs:
  1. group     -- the alternating group is constructed and verified to be one;
  2. lagrange  -- over every subgroup, the cosets partition into equal blocks and
                  the order divides, with the partition itself exhibited;
  3. spectrum  -- the orders that actually occur are enumerated;
  4. falsifier -- six divides twelve and is not among them, so the converse is
                  false and its failure is found rather than asserted;
  5. reason    -- a subgroup of index two must be normal, and the normal
                  subgroups are computed, which explains the gap;
  6. contrast  -- in the cyclic group of order twelve every divisor is realised,
                  and in the symmetric group on three letters too.
"""
import itertools

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def compose(first, second):
    """Permutations as tuples, applied right to left.

    Nothing below depends on the convention. Reversing it gives the opposite
    group, which has the same subgroups and the same subgroup orders, so every
    count in this file is unchanged by the choice.
    """
    return tuple(first[second[index]] for index in range(len(second)))


def sign(permutation):
    """Parity by counting inversions, which is the definition rather than a table."""
    inversions = sum(
        1
        for i in range(len(permutation))
        for j in range(i + 1, len(permutation))
        if permutation[i] > permutation[j]
    )
    return (-1) ** inversions


def inverse(permutation):
    result = [0] * len(permutation)
    for index, image in enumerate(permutation):
        result[image] = index
    return tuple(result)


def is_group(elements, operation, identity, invert):
    """Closure, identity and inverses, all checked over the whole set."""
    closed = all(operation(a, b) in elements for a in elements for b in elements)
    neutral = all(operation(identity, a) == a and operation(a, identity) == a
                  for a in elements)
    inverses = all(operation(a, invert(a)) == identity for a in elements)
    return closed and neutral and inverses


def subgroups(elements, operation, identity):
    """Every subgroup, by testing every subset for closure.

    Exhaustive rather than generated: a search over generating sets would only
    find the subgroups its generators reach, and the claim below is about what
    does NOT exist, which a partial search cannot establish.
    A non-empty finite subset closed under the operation is already a subgroup,
    so the identity test below is only a shortcut that skips subsets which
    cannot work; dropping it would change the running time and not the answer.
    """
    found = []
    for size in range(1, len(elements) + 1):
        for subset in itertools.combinations(elements, size):
            block = set(subset)
            if identity not in block:
                continue
            if all(operation(a, b) in block for a in block for b in block):
                found.append(block)
    return found


# ---------------------------------------------------------------- leg 1
IDENTITY = (0, 1, 2, 3)
ALTERNATING = [p for p in itertools.permutations(range(4)) if sign(p) == 1]
check("the_alternating_group_has_twelve_elements",
      len(ALTERNATING) == 12 and len(set(ALTERNATING)) == 12,
      f"{len(ALTERNATING)} even permutations of four letters")

check("and_it_is_a_group",
      is_group(set(ALTERNATING), compose, IDENTITY, inverse),
      "closed under composition, with the identity and with inverses")

# That every element is even holds by construction, so it is not worth a check.
# What is worth one is that the other half is NOT a group: the product of two
# odd permutations is even, which is why the even half is the one taken.
ODD = [p for p in itertools.permutations(range(4)) if sign(p) == -1]
check("the_odd_permutations_are_as_many_but_do_not_form_a_group",
      len(ODD) == 12
      and not is_group(set(ODD), compose, IDENTITY, inverse),
      f"{len(ODD)} odd permutations, and the group test rejects them since "
      f"{ODD[0]} composed with itself gives {compose(ODD[0], ODD[0])}, which is "
      "even; this is also what exercises the closure clause of that test, which "
      "the alternating group alone could never do")


# ---------------------------------------------------------------- leg 2
FOUND = subgroups(ALTERNATING, compose, IDENTITY)


def left_cosets(subgroup, elements, operation):
    """The distinct sets gH, as frozensets so that repeats collapse."""
    return {frozenset(operation(g, h) for h in subgroup) for g in elements}


partitions_correctly = []
for subgroup in FOUND:
    cosets = left_cosets(subgroup, ALTERNATING, compose)
    disjoint = sum(len(coset) for coset in cosets) == len(ALTERNATING)
    covering = set().union(*cosets) == set(ALTERNATING)
    equal = {len(coset) for coset in cosets} == {len(subgroup)}
    counted = len(cosets) * len(subgroup) == len(ALTERNATING)
    partitions_correctly.append(disjoint and covering and equal and counted)

check("the_cosets_of_every_subgroup_partition_the_group_into_equal_blocks",
      all(partitions_correctly),
      f"checked for all {len(FOUND)} subgroups, each giving blocks of its own "
      "size that cover the group without overlapping, with the number of blocks "
      "times the block size coming to twelve every time")

check("so_every_subgroup_order_divides_the_group_order",
      all(len(ALTERNATING) % len(subgroup) == 0 for subgroup in FOUND),
      "which is the coset count times the block size, not a separate fact")

# The partition exhibited once, so the mechanism is visible and not only asserted.
threes = [s for s in FOUND if len(s) == 3]
sample_cosets = left_cosets(threes[0], ALTERNATING, compose) if threes else set()
check("the_partition_is_exhibited_for_a_subgroup_of_order_three",
      len(threes) == 4 and len(sample_cosets) == 4
      and all(len(c) == 3 for c in sample_cosets),
      f"there are {len(threes)} subgroups of order three, and one of them gives "
      f"{len(sample_cosets)} cosets of size three, four times three being twelve")


# ---------------------------------------------------------------- leg 3
ORDERS = sorted({len(subgroup) for subgroup in FOUND})
DIVISORS = sorted(d for d in range(1, 13) if 12 % d == 0)
check("the_subgroup_orders_that_occur_are_one_two_three_four_and_twelve",
      ORDERS == [1, 2, 3, 4, 12],
      f"orders found: {ORDERS}, from {len(FOUND)} subgroups in all")

check("and_the_divisors_of_twelve_are_one_more_than_that",
      DIVISORS == [1, 2, 3, 4, 6, 12],
      f"divisors of twelve: {DIVISORS}")


# ---------------------------------------------------------------- leg 4
missing = [d for d in DIVISORS if d not in ORDERS]
check("falsifier_six_divides_twelve_and_no_subgroup_has_that_order",
      missing == [6],
      f"the divisors not realised are {missing}, so the converse of Lagrange "
      "fails here, and it fails for exactly one divisor")

# Stated as an exhaustive search rather than a failure to find: every subset of
# size six was examined, and none of them was closed.
sixes = [
    subset for subset in itertools.combinations(ALTERNATING, 6)
    if IDENTITY in subset
    and all(compose(a, b) in set(subset) for a in subset for b in subset)
]
with_identity = [subset for subset in itertools.combinations(ALTERNATING, 6)
                 if IDENTITY in subset]
check("and_the_search_over_subsets_of_size_six_was_exhaustive",
      sixes == [],
      f"of the {len(list(itertools.combinations(ALTERNATING, 6)))} subsets of size "
      f"six, the {len(with_identity)} containing the identity were tested for "
      "closure, the rest being disqualified by not containing it, and none is "
      "a subgroup")


# ---------------------------------------------------------------- leg 5
def add_mod_twelve(first, second):
    return (first + second) % 12


def negate_mod_twelve(value):
    return (-value) % 12


def is_normal(subgroup, elements, operation, invert):
    return all(
        {operation(operation(g, h), invert(g)) for h in subgroup} == subgroup
        for g in elements
    )


CYCLIC = list(range(12))
SYMMETRIC = list(itertools.permutations(range(3)))
cyclic_subgroups = subgroups(CYCLIC, add_mod_twelve, 0)
symmetric_subgroups = subgroups(SYMMETRIC, compose, (0, 1, 2))

normal_orders = sorted({
    len(subgroup) for subgroup in FOUND
    if is_normal(subgroup, ALTERNATING, compose, inverse)
})
check("the_normal_subgroups_have_orders_one_four_and_twelve",
      normal_orders == [1, 4, 12],
      f"normal subgroup orders: {normal_orders}")

# The rule the explanation rests on, tested where there is something to test it
# on. The alternating group has no subgroup of index two at all, so the rule
# cannot be exercised there, and leaning on it while never checking it anywhere
# would leave the explanation resting on an unverified claim.
index_two_cases = (
    [(s, CYCLIC, add_mod_twelve, negate_mod_twelve)
     for s in cyclic_subgroups if len(CYCLIC) // len(s) == 2]
    + [(s, SYMMETRIC, compose, inverse)
       for s in symmetric_subgroups if len(SYMMETRIC) // len(s) == 2]
)
check("every_subgroup_of_index_two_found_here_is_normal",
      len(index_two_cases) >= 2
      and all(len(elements) == 2 * len(group)
              for group, elements, _, _ in index_two_cases)
      and all(is_normal(group, elements, operation, invert)
              for group, elements, operation, invert in index_two_cases),
      f"{len(index_two_cases)} subgroups of index two across the cyclic and the "
      "symmetric group, every one of them normal")

check("so_an_order_six_subgroup_would_have_to_be_normal_and_none_is",
      6 not in normal_orders,
      "a subgroup of order six would have index two and so be normal, and six "
      f"is absent from {normal_orders}, which is why the gap is where it is")


# ---------------------------------------------------------------- leg 6
cyclic_orders = sorted({len(s) for s in cyclic_subgroups})
check("in_the_cyclic_group_of_order_twelve_every_divisor_is_realised",
      cyclic_orders == DIVISORS,
      f"orders found: {cyclic_orders}, matching the divisors exactly, so the "
      "converse of Lagrange is true here and the failure belongs to the group")

symmetric_orders = sorted({len(s) for s in symmetric_subgroups})
check("and_in_the_symmetric_group_on_three_letters_too",
      symmetric_orders == [1, 2, 3, 6],
      f"orders found: {symmetric_orders} against the divisors of six, so a "
      "non-abelian group is not enough on its own to break the converse")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
