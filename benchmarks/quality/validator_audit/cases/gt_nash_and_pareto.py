"""Equilibrium is not efficiency, and in pure strategies it need not exist.

CLAIM: a pure Nash equilibrium is a cell that is a best response for both
players, which over a finite game is decided by enumeration; the prisoner's
dilemma has exactly one, at mutual defection, and it is strictly worse for BOTH
players than mutual cooperation, so being an equilibrium says nothing about
being efficient; matching pennies has no pure equilibrium at all, so existence
needs mixed strategies; and the mixed equilibrium is found by the indifference
condition and then verified to be one, since solving the condition and having an
equilibrium are different statements.

Two separate failures of the same word. "Equilibrium" is read as "good outcome"
and as "the outcome", and it is neither.

Legs:
  1. best      -- the best-response sets are built from the payoffs and checked
                  to attain the maximum they claim to;
  2. dilemma   -- the pure equilibria are enumerated and there is exactly one;
  3. falsifier -- that equilibrium is strictly worse for both than another cell,
                  with the losses computed;
  4. stable    -- and the better cell is not an equilibrium, each player's gain
                  from deviating being positive and computed;
  5. pennies   -- a game with no pure equilibrium, shown by exhausting the cells;
  6. mixed     -- the indifference condition is solved and the solution is then
                  tested as an equilibrium rather than assumed to be one.
"""
import itertools

import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# A game is a pair of payoff tables indexed by (row action, column action).
DILEMMA = {
    ("cooperate", "cooperate"): (sp.Integer(3), sp.Integer(3)),
    ("cooperate", "defect"): (sp.Integer(0), sp.Integer(5)),
    ("defect", "cooperate"): (sp.Integer(5), sp.Integer(0)),
    ("defect", "defect"): (sp.Integer(1), sp.Integer(1)),
}
ROWS = ["cooperate", "defect"]
COLUMNS = ["cooperate", "defect"]


def best_responses(game, rows, columns, player):
    """For each choice of the opponent, the actions attaining the best payoff."""
    answer = {}
    if player == 0:
        for column in columns:
            payoffs = {row: game[(row, column)][0] for row in rows}
            top = max(payoffs.values())
            answer[column] = {row for row, value in payoffs.items() if value == top}
    else:
        for row in rows:
            payoffs = {column: game[(row, column)][1] for column in columns}
            top = max(payoffs.values())
            answer[row] = {column for column, value in payoffs.items()
                           if value == top}
    return answer


def pure_equilibria(game, rows, columns):
    row_best = best_responses(game, rows, columns, 0)
    column_best = best_responses(game, rows, columns, 1)
    return [(row, column) for row in rows for column in columns
            if row in row_best[column] and column in column_best[row]]


# ---------------------------------------------------------------- leg 1
row_best = best_responses(DILEMMA, ROWS, COLUMNS, 0)
attains = all(
    DILEMMA[(choice, column)][0] == max(DILEMMA[(row, column)][0] for row in ROWS)
    for column, choices in row_best.items() for choice in choices
)
check("every_listed_best_response_really_attains_the_best_payoff",
      attains,
      f"checked over all {sum(len(v) for v in row_best.values())} listed "
      "responses, each equal to the maximum of its column")

misses = all(
    DILEMMA[(row, column)][0] < max(DILEMMA[(other, column)][0] for other in ROWS)
    for column in COLUMNS for row in ROWS if row not in row_best[column]
)
check("and_every_action_left_out_falls_strictly_short",
      misses,
      "so the sets are the best responses and not merely a subset of them")


# ---------------------------------------------------------------- leg 2
equilibria = pure_equilibria(DILEMMA, ROWS, COLUMNS)
check("the_dilemma_has_exactly_one_pure_equilibrium",
      len(equilibria) == 1 and equilibria[0] == ("defect", "defect"),
      f"enumerating all {len(ROWS) * len(COLUMNS)} cells leaves {equilibria}")

dominant = all(
    DILEMMA[("defect", column)][0] > DILEMMA[("cooperate", column)][0]
    for column in COLUMNS
)
check("because_defection_beats_cooperation_whatever_the_other_does",
      dominant,
      f"defecting pays {[DILEMMA[('defect', c)][0] for c in COLUMNS]} against "
      f"{[DILEMMA[('cooperate', c)][0] for c in COLUMNS]}, column by column")


# ---------------------------------------------------------------- leg 3
at_equilibrium = DILEMMA[("defect", "defect")]
alternative = DILEMMA[("cooperate", "cooperate")]
losses = [other - here for here, other in zip(at_equilibrium, alternative)]
check("falsifier_that_equilibrium_is_worse_for_both_than_another_cell",
      all(value > 0 for value in losses),
      f"mutual cooperation pays {alternative} against {at_equilibrium}, so each "
      f"player gives up {losses[0]} by playing the equilibrium")

dominated = [
    cell for cell in DILEMMA
    if all(DILEMMA[cell][i] < alternative[i] for i in (0, 1))
]
check("and_it_is_the_only_cell_that_mutual_cooperation_beats_outright",
      dominated == [("defect", "defect")],
      f"the cells strictly worse for both are {dominated}, the two asymmetric "
      "ones being better for whoever defects")


# ---------------------------------------------------------------- leg 4
gains = [
    DILEMMA[("defect", "cooperate")][0] - alternative[0],
    DILEMMA[("cooperate", "defect")][1] - alternative[1],
]
check("but_the_better_cell_is_not_stable_either",
      all(value > 0 for value in gains) and ("cooperate", "cooperate") not in equilibria,
      f"from mutual cooperation each player gains {gains[0]} by deviating, which "
      "is why the efficient cell is not an equilibrium and the two notions come "
      "apart in both directions")


# ---------------------------------------------------------------- leg 5
PENNIES = {
    ("heads", "heads"): (sp.Integer(1), sp.Integer(-1)),
    ("heads", "tails"): (sp.Integer(-1), sp.Integer(1)),
    ("tails", "heads"): (sp.Integer(-1), sp.Integer(1)),
    ("tails", "tails"): (sp.Integer(1), sp.Integer(-1)),
}
SIDES = ["heads", "tails"]
pennies_pure = pure_equilibria(PENNIES, SIDES, SIDES)
check("matching_pennies_has_no_pure_equilibrium_at_all",
      pennies_pure == [],
      f"all {len(SIDES) ** 2} cells were tested and none is a best response for "
      "both, so existence in pure strategies is simply false")

# Asked of EITHER player, not of the row player alone: in two of these cells
# the row player is already content and it is the column player who wants to
# move. Having no equilibrium means somebody wants to move in every cell, not
# that the same somebody always does.
def restlessness(game, rows, columns, row, column):
    """The most either player can gain by moving on their own from this cell."""
    return max(
        max(game[(other, column)][0] for other in rows) - game[(row, column)][0],
        max(game[(row, other)][1] for other in columns) - game[(row, column)][1],
    )


deviations = [restlessness(PENNIES, SIDES, SIDES, row, column)
              for row, column in itertools.product(SIDES, SIDES)]
check("and_in_every_cell_somebody_strictly_wants_to_move",
      all(value > 0 for value in deviations),
      f"the larger of the two gains from moving alone is {deviations} across "
      "the four cells, positive in every one, which is what having no "
      "equilibrium looks like cell by cell")


# ---------------------------------------------------------------- leg 6
# The indifference condition: the row player mixes so that the column player is
# indifferent. Solved, and then the solution is tested, because a solution to an
# indifference equation is not yet an equilibrium.
probability = sp.Symbol("p", positive=True)


def column_payoff(choice, weight):
    """The column player's expected payoff when the row mixes with this weight."""
    return (weight * PENNIES[("heads", choice)][1]
            + (1 - weight) * PENNIES[("tails", choice)][1])


indifference = sp.solve(
    sp.Eq(column_payoff("heads", probability), column_payoff("tails", probability)),
    probability,
)
check("the_indifference_condition_has_one_interior_solution",
      len(indifference) == 1 and bool(0 < indifference[0] < 1),
      f"solving for the mix that leaves the column player indifferent gives "
      f"p = {indifference[0] if indifference else 'nothing'}")

mix = indifference[0]
check("and_it_is_the_even_mix",
      sp.simplify(mix - sp.Rational(1, 2)) == 0,
      f"p = {mix}")

payoffs_at_mix = {choice: sp.simplify(column_payoff(choice, mix))
                  for choice in SIDES}
check("at_that_mix_the_column_player_cannot_do_better_by_any_pure_choice",
      len(set(payoffs_at_mix.values())) == 1,
      f"both pure replies pay {set(payoffs_at_mix.values())}, so no deviation "
      "gains anything and the profile is an equilibrium rather than merely a "
      "solution of the equation")

off_mix = sp.Rational(3, 4)
spread = sp.simplify(
    sp.Max(*[column_payoff(choice, off_mix) for choice in SIDES])
    - sp.Min(*[column_payoff(choice, off_mix) for choice in SIDES])
)
check("while_away_from_it_one_reply_is_strictly_better",
      bool(spread > 0),
      f"at p = {off_mix} the two replies differ by {spread}, so the row player "
      "would be exploited, which is what the indifference condition prevents")

# Matching pennies is zero sum, so the two players' indifference conditions
# coincide and this game cannot tell whose payoffs the condition should use.
# Getting that wrong is a common error, so a game where the two answers differ
# is added rather than leaving the question untested.
SEXES = {
    ("opera", "opera"): (sp.Integer(2), sp.Integer(1)),
    ("opera", "football"): (sp.Integer(0), sp.Integer(0)),
    ("football", "opera"): (sp.Integer(0), sp.Integer(0)),
    ("football", "football"): (sp.Integer(1), sp.Integer(2)),
}
VENUES = ["opera", "football"]


def mix_making_opponent_indifferent(game, rows, columns, index):
    """The row mix leaving the column player indifferent, read off payoff `index`."""
    first, second = columns
    left = (probability * game[(rows[0], first)][index]
            + (1 - probability) * game[(rows[1], first)][index])
    right = (probability * game[(rows[0], second)][index]
             + (1 - probability) * game[(rows[1], second)][index])
    found = sp.solve(sp.Eq(left, right), probability)
    return sp.simplify(sum(found)) if found else sp.nan


correct = mix_making_opponent_indifferent(SEXES, VENUES, VENUES, 1)
wrong = mix_making_opponent_indifferent(SEXES, VENUES, VENUES, 0)
check("in_a_non_zero_sum_game_the_two_indifference_conditions_differ",
      sp.simplify(correct - wrong) != 0,
      f"using the column player's payoffs gives p = {correct} and using the row "
      f"player's gives p = {wrong}, so the two are not interchangeable")

check("and_it_is_the_opponents_payoffs_that_the_condition_uses",
      sp.simplify(correct - sp.Rational(2, 3)) == 0,
      f"the equilibrium mix is p = {correct}, which is what leaves the column "
      "player unable to prefer either venue")


# And in the dilemma the same construction finds nothing interior, because a
# dominant strategy leaves no mix that makes the opponent indifferent.
dilemma_indifference = sp.solve(
    sp.Eq(
        probability * DILEMMA[("cooperate", "cooperate")][1]
        + (1 - probability) * DILEMMA[("defect", "cooperate")][1],
        probability * DILEMMA[("cooperate", "defect")][1]
        + (1 - probability) * DILEMMA[("defect", "defect")][1],
    ),
    probability,
)
check("and_the_dilemma_admits_no_interior_mix_at_all",
      dilemma_indifference == [],
      f"the same equation has solutions {dilemma_indifference} there, since a "
      "dominant strategy leaves nothing to be indifferent about")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
