"""Matching an invariant is not being the same graph, twice over.

CLAIM: the degrees of any graph sum to twice its edge count; the Erdos-Gallai
inequalities decide exactly which non-increasing sequences are degree sequences
of some graph, which is checked in both directions against explicit construction
over every candidate on five vertices; the number of graphs up to isomorphism is
counted twice, by canonical forms and by Burnside's lemma, and the two agree; yet
a degree sequence does not determine a graph, several being shared by
non-isomorphic pairs; and the adjacency spectrum does not either, the star on
four leaves and a square beside an isolated point having the same characteristic
polynomial while differing in their degrees.

The escalation is the point. Each invariant that fails has to be caught by a
different one, and nothing in the list is ever enough on its own, which is what
"necessary but not sufficient" means when it is made concrete.

Legs:
  1. handshake -- the degree sum is twice the edge count on every graph, checked
                  over all of them rather than on examples;
  2. counted   -- the isomorphism classes are counted by canonical form and by
                  Burnside, two routes that must agree;
  3. gallai    -- the inequalities are tested against realisability on every
                  candidate sequence, in both directions;
  4. falsifier -- a degree sequence is shared by non-isomorphic graphs, with the
                  non-isomorphism established by exhausting the permutations;
  5. spectrum  -- a stronger invariant fails in the same way, and it is the
                  degrees that break that tie, each test needing another.
"""
import itertools

import sympy as sp

VERTICES = 5
PAIRS = list(itertools.combinations(range(VERTICES), 2))
PERMUTATIONS = list(itertools.permutations(range(VERTICES)))

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def every_graph():
    """All labelled graphs on the vertex set, as frozensets of edges."""
    for mask in range(1 << len(PAIRS)):
        yield frozenset(pair for index, pair in enumerate(PAIRS)
                        if mask >> index & 1)


def degrees(graph):
    counts = [0] * VERTICES
    for first, second in graph:
        counts[first] += 1
        counts[second] += 1
    return tuple(sorted(counts, reverse=True))


def relabel(graph, permutation):
    return frozenset(
        tuple(sorted((permutation[first], permutation[second])))
        for first, second in graph
    )


def canonical(graph):
    """The smallest relabelling, which is the same for isomorphic graphs."""
    return min(tuple(sorted(relabel(graph, p))) for p in PERMUTATIONS)


ALL = list(every_graph())


# ---------------------------------------------------------------- leg 1
mismatched = [
    graph for graph in ALL if sum(degrees(graph)) != 2 * len(graph)
]
check("the_degrees_sum_to_twice_the_edge_count_on_every_graph",
      mismatched == [],
      f"checked over all {len(ALL)} labelled graphs on {VERTICES} vertices, so "
      "the handshake lemma is settled here rather than sampled")

odd_degree_counts = {
    sum(1 for value in degrees(graph) if value % 2) % 2 for graph in ALL
}
check("so_the_number_of_odd_degree_vertices_is_always_even",
      odd_degree_counts == {0},
      "the parity follows from the sum being even, and it holds across the same "
      "exhaustive list")


# ---------------------------------------------------------------- leg 2
classes = {}
for graph in ALL:
    classes.setdefault(canonical(graph), graph)

# Burnside: the number of orbits is the average number of graphs each relabelling
# leaves alone, and a relabelling fixes exactly two to the power of its orbit
# count on the edge slots. An independent route to the same number.
def edge_orbits(permutation):
    seen, orbits = set(), 0
    for pair in PAIRS:
        if pair in seen:
            continue
        orbits += 1
        current = pair
        while current not in seen:
            seen.add(current)
            current = tuple(sorted((permutation[current[0]],
                                    permutation[current[1]])))
    return orbits


burnside = sum(1 << edge_orbits(p) for p in PERMUTATIONS) / len(PERMUTATIONS)
check("the_two_counts_of_isomorphism_classes_agree",
      len(classes) == burnside,
      f"canonical forms give {len(classes)} classes and Burnside gives "
      f"{burnside:.0f}, computed from the {len(PERMUTATIONS)} relabellings "
      "without ever building a canonical form")


# ---------------------------------------------------------------- leg 3
REALISABLE = {degrees(graph) for graph in ALL}
CANDIDATES = [
    sequence
    for sequence in itertools.combinations_with_replacement(
        range(VERTICES - 1, -1, -1), VERTICES)
]


def erdos_gallai(sequence):
    """Even sum, and the k-th inequality for every k."""
    if sum(sequence) % 2:
        return False
    for k in range(1, len(sequence) + 1):
        left = sum(sequence[:k])
        right = k * (k - 1) + sum(min(value, k) for value in sequence[k:])
        if left > right:
            return False
    return True


disagreements = [
    sequence for sequence in CANDIDATES
    if erdos_gallai(sequence) != (sequence in REALISABLE)
]
check("the_inequalities_decide_realisability_on_every_candidate_sequence",
      disagreements == [],
      f"all {len(CANDIDATES)} non-increasing sequences agree with explicit "
      f"construction, {len(REALISABLE)} of them being realisable")

# Measured on the TEST rather than on the realisable set: the two coincide by
# the check above, but only one of them is the criterion being examined.
accepted = [sequence for sequence in CANDIDATES if erdos_gallai(sequence)]
check("and_the_test_separates_rather_than_accepting_everything",
      0 < len(accepted) < len(CANDIDATES),
      f"the inequalities reject {len(CANDIDATES) - len(accepted)} of the "
      f"{len(CANDIDATES)} candidates and accept {len(accepted)}, so the "
      "criterion is doing work rather than waving everything through")


# ---------------------------------------------------------------- leg 4
by_sequence = {}
for representative in classes.values():
    by_sequence.setdefault(degrees(representative), []).append(representative)

# Asked of the grouping itself rather than of the filtered dictionary, so that
# loosening the filter cannot make the statement true by construction.
check("falsifier_some_degree_sequences_belong_to_more_than_one_graph",
      max(len(members) for members in by_sequence.values()) > 1,
      f"{sum(1 for m in by_sequence.values() if len(m) > 1)} of the "
      f"{len(by_sequence)} realisable sequences are shared, covering "
      f"{sum(len(m) for m in by_sequence.values() if len(m) > 1)} of the "
      f"{len(classes)} classes")

# Every ambiguous pair is checked, not one of them, and nothing is indexed out
# of a list that could be empty: if no sequence were shared the check reports
# that rather than raising.
pairs = [(members[0], members[1]) for members in by_sequence.values()
         if len(members) >= 2]
example = (f"{sorted(pairs[0][0])} and {sorted(pairs[0][1])}" if pairs
           else "no pair at all")
check("and_every_such_pair_really_is_non_isomorphic",
      len(pairs) > 0
      and all(relabel(one, permutation) != other
              for one, other in pairs for permutation in PERMUTATIONS),
      f"{len(pairs)} shared sequences, the first carried by {example}, and none "
      f"of the {len(PERMUTATIONS)} relabellings carries either onto its partner")

# Comparing the two degree sequences here would be true by construction, the
# pair having been grouped by that very sequence. What is not automatic is how
# much the invariant loses: the map from classes to sequences is not injective,
# and the deficit is the number of classes with no sequence of their own.
check("so_the_degree_sequence_loses_information",
      len(by_sequence) < len(classes),
      f"the {len(classes)} classes map onto only {len(by_sequence)} sequences, "
      f"a deficit of {len(classes) - len(by_sequence)}, which is exactly how "
      "many classes the invariant cannot tell apart from another")


# ---------------------------------------------------------------- leg 5
def adjacency(graph):
    matrix = sp.zeros(VERTICES, VERTICES)
    for one, other in graph:
        matrix[one, other] = 1
        matrix[other, one] = 1
    return matrix


STAR = frozenset({(0, 1), (0, 2), (0, 3), (0, 4)})
SQUARE = frozenset({(1, 2), (2, 3), (3, 4), (1, 4)})
lam = sp.Symbol("lambda")
star_polynomial = sp.factor(adjacency(STAR).charpoly(lam).as_expr())
square_polynomial = sp.factor(adjacency(SQUARE).charpoly(lam).as_expr())
# Agreement alone is too weak a statement: two nilpotent matrices agree on the
# polynomial lambda to the fifth and say nothing. The shared polynomial is
# therefore named, which pins the spectrum to minus two, zero three times, and
# two.
expected_polynomial = lam ** 3 * (lam - 2) * (lam + 2)
check("the_star_and_the_square_share_a_characteristic_polynomial",
      sp.simplify(star_polynomial - square_polynomial) == 0
      and sp.simplify(sp.expand(star_polynomial - expected_polynomial)) == 0,
      f"both give {star_polynomial}, so the spectrum is minus two, zero three "
      "times and two in each case")

check("falsifier_yet_they_are_not_isomorphic",
      all(relabel(STAR, p) != SQUARE for p in PERMUTATIONS),
      f"no relabelling carries the star onto the square, so a stronger "
      "invariant fails in exactly the same way as the weaker one")

check("and_here_it_is_the_degrees_that_break_the_tie",
      degrees(STAR) != degrees(SQUARE),
      f"the star has degrees {degrees(STAR)} and the square {degrees(SQUARE)}, "
      "so the test that failed in leg four is the one that settles this pair, "
      "and neither is enough by itself")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
