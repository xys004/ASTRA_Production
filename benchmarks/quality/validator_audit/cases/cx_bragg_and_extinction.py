"""Satisfying Bragg's law is not seeing a reflection.

CLAIM: the path difference between planes gives n lambda = 2 d sin(theta), which
has a solution only while lambda stays under twice the spacing, so the law
carries its own domain; for a cubic cell the spacing is a over the root of the
sum of squared indices; and the structure factor decides whether anything is
actually there, vanishing for every odd index sum in a body-centred cell and for
every mixed parity in a face-centred one. Half the Bragg angles of one lattice
and three quarters of the other show nothing at all, and the surviving sequences
differ, which is what lets a powder pattern name the lattice.

Bragg's law is the necessary half. A validator that checks an angle against it
has checked that a reflection is not forbidden by geometry, not that it exists.

Legs:
  1. bragg      -- the condition is solved for the angle, and the wavelength
                   bound that makes a solution possible is solved for too;
  2. spacing    -- the cubic spacing is derived from the plane normal;
  3. centred    -- the body-centred structure factor is computed and shown to
                   vanish exactly on the odd index sums;
  4. falsifier  -- so Bragg-allowed angles with odd sums carry no intensity,
                   enumerated rather than described;
  5. faces      -- the face-centred factor vanishes on mixed parity, leaving a
                   different and sparser set;
  6. identify   -- the two surviving sequences differ from the start, so the
                   pattern identifies the lattice that the law alone cannot.
"""
import itertools

import sympy as sp

wavelength, spacing, cell = sp.symbols("lambda d a", positive=True)
angle = sp.Symbol("theta", positive=True)
order = sp.Symbol("n", positive=True, integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# ---------------------------------------------------------------- leg 1
# Two rays reflecting off neighbouring planes differ in path by twice the
# spacing times the sine of the glancing angle. Constructive interference wants
# that to be a whole number of wavelengths.
path_difference = 2 * spacing * sp.sin(angle)
solved_angle = sp.solve(sp.Eq(path_difference, order * wavelength), angle)
check("the_bragg_condition_solves_for_the_glancing_angle",
      len(solved_angle) >= 1
      and sp.simplify(sp.sin(solved_angle[0]) - order * wavelength / (2 * spacing)) == 0,
      f"solving 2 d sin(theta) = n lambda gives sin(theta) = "
      f"{sp.simplify(sp.sin(solved_angle[0]))}")

# The sine cannot exceed one, so the law has a reach and says nothing past it.
reach = sp.solve(sp.Eq(order * wavelength / (2 * spacing), 1), wavelength)
check("and_the_law_reaches_only_while_the_wavelength_stays_under_twice_the_spacing",
      len(reach) == 1 and sp.simplify(reach[0] - 2 * spacing / order) == 0,
      f"the first order runs out at lambda = {sp.simplify(reach[0].subs(order, 1))}, "
      "beyond which no angle satisfies the condition at all")


# ---------------------------------------------------------------- leg 2
h, k, l = sp.symbols("h k l", integer=True)
# The plane (h k l) cuts the axes at a/h, a/k, a/l, so its unit normal is the
# index vector normalised and the spacing is the projection of one intercept.
normal = sp.Matrix([h, k, l])
intercept = sp.Matrix([cell / h, 0, 0])
derived_spacing = sp.simplify(
    (intercept.dot(normal) / sp.sqrt(normal.dot(normal)))
)
check("the_cubic_spacing_is_the_cell_over_the_root_of_the_squared_indices",
      sp.simplify(derived_spacing - cell / sp.sqrt(h ** 2 + k ** 2 + l ** 2)) == 0,
      f"projecting an intercept on the plane normal gives d = {derived_spacing}")


# ---------------------------------------------------------------- leg 3
scatter = sp.Symbol("f", positive=True)


def structure_factor(basis, indices):
    """The sum of scattering from each atom, with its phase."""
    return sp.simplify(sum(
        scatter * sp.exp(2 * sp.pi * sp.I * (indices[0] * x + indices[1] * y
                                             + indices[2] * z))
        for x, y, z in basis
    ))


BODY = [(0, 0, 0), (sp.Rational(1, 2),) * 3]
body_factor = structure_factor(BODY, (h, k, l))
check("the_body_centred_factor_is_one_plus_minus_one_to_the_index_sum",
      sp.simplify(body_factor - scatter * (1 + (-1) ** (h + k + l))) == 0,
      f"F = {body_factor}, so the two atoms interfere according to the parity of "
      "the index sum and nothing else")

GRID = [triple for triple in itertools.product(range(1, 5), repeat=3)]
odd = [triple for triple in GRID if sum(triple) % 2 == 1]
even = [triple for triple in GRID if sum(triple) % 2 == 0]
check("it_vanishes_on_every_odd_index_sum_and_on_no_even_one",
      all(sp.simplify(structure_factor(BODY, triple)) == 0 for triple in odd)
      and all(sp.simplify(structure_factor(BODY, triple)) == 2 * scatter
              for triple in even),
      f"checked over all {len(odd)} odd and {len(even)} even triples with "
      "indices from one to four, each vanishing or doubling exactly as the "
      "parity says")


# ---------------------------------------------------------------- leg 4
def allowed_by_bragg(triple):
    """Whether some angle satisfies the law for this plane at a usable ratio.

    Taken at a wavelength of half the cell, so the reach of leg 1 admits the
    first several planes and excludes the rest; this is the geometric half of
    the question and says nothing about intensity.
    """
    squared = sum(index ** 2 for index in triple)
    return squared > 0 and sp.Rational(1, 2) * sp.sqrt(squared) <= 2

geometric = [triple for triple in itertools.product(range(4), repeat=3)
             if allowed_by_bragg(triple)]
silent = [triple for triple in geometric
          if sp.simplify(structure_factor(BODY, triple)) == 0]
check("falsifier_half_the_bragg_allowed_planes_show_nothing",
      len(silent) > 0 and abs(len(silent) / len(geometric) - 0.5) < 0.1,
      f"of the {len(geometric)} planes the law admits at this wavelength, "
      f"{len(silent)} carry no intensity, a fraction of "
      f"{len(silent) / len(geometric):.2f}, so the angle being right is the "
      "necessary half and not the sufficient one")

check("and_the_silent_ones_are_exactly_the_odd_sums",
      {triple for triple in silent} == {triple for triple in geometric
                                        if sum(triple) % 2 == 1},
      "the extinction rule and the enumeration agree on which planes go dark, "
      "so the count above is explained rather than merely observed")


# ---------------------------------------------------------------- leg 5
FACES = [(0, 0, 0), (0, sp.Rational(1, 2), sp.Rational(1, 2)),
         (sp.Rational(1, 2), 0, sp.Rational(1, 2)),
         (sp.Rational(1, 2), sp.Rational(1, 2), 0)]


def same_parity(triple):
    return len({index % 2 for index in triple}) == 1


mixed = [triple for triple in GRID if not same_parity(triple)]
uniform = [triple for triple in GRID if same_parity(triple)]
check("the_face_centred_factor_vanishes_on_mixed_parity",
      all(sp.simplify(structure_factor(FACES, triple)) == 0 for triple in mixed)
      and all(sp.simplify(structure_factor(FACES, triple)) == 4 * scatter
              for triple in uniform),
      f"across {len(mixed)} mixed and {len(uniform)} uniform triples the factor "
      "is zero or four times the scattering, with nothing in between")

# Compared as fractions over the SAME enumeration. Counting one rule on one
# range and the other on another would compare two different questions.
body_dark = len(odd) / len(GRID)
faces_dark = len(mixed) / len(GRID)
check("so_it_extinguishes_more_than_the_body_centred_cell_does",
      faces_dark > body_dark,
      f"over the same {len(GRID)} triples the face-centred cell silences "
      f"{faces_dark:.2f} of them against {body_dark:.2f} for the body-centred "
      "one, which is three quarters against a half: only two of the eight "
      "parity patterns survive the first rule and four survive the second")


# ---------------------------------------------------------------- leg 6
def surviving(basis, limit=6):
    """The squared index sums that keep some intensity, in order."""
    values = sorted({
        sum(index ** 2 for index in triple)
        for triple in itertools.product(range(5), repeat=3)
        if any(triple) and sp.simplify(structure_factor(basis, triple)) != 0
    })
    return values[:limit]


body_sequence = surviving(BODY)
faces_sequence = surviving(FACES)
check("the_two_lattices_leave_different_sequences",
      body_sequence != faces_sequence and body_sequence[0] != faces_sequence[0],
      f"the body-centred cell keeps {body_sequence} and the face-centred one "
      f"{faces_sequence}, differing from the very first reflection")

check("and_the_body_centred_sequence_is_the_even_sums",
      all(value % 2 == 0 for value in body_sequence),
      f"{body_sequence}, every one even, which is the extinction rule read off "
      "the pattern instead of off the basis")

check("so_the_pattern_names_the_lattice_that_the_law_alone_cannot",
      set(body_sequence) != set(faces_sequence)
      and len(set(body_sequence) & set(faces_sequence)) < len(body_sequence),
      f"the sequences share only {sorted(set(body_sequence) & set(faces_sequence))}, "
      "so an observed list of ratios distinguishes the two cells while Bragg's "
      "law, which knows only the spacings, cannot")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
