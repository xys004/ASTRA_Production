"""Zero training error is arithmetic, and a held-out set stops holding out once
you choose on it.

CLAIM: a polynomial with as many coefficients as there are data points passes
through all of them exactly, so a training error at the rounding floor is forced
by the parameter count and says nothing about the function; on noisy samples of a
cubic the test error is not monotone in the degree but has an interior minimum at
the true degree, and the interpolant is many times worse than that; the best
achievable test error is the noise level itself; and a degree chosen by the test
error and then reported with that same error is optimistic, which a third
untouched sample exposes.

Both failures in this file look like successes while they are happening. A fit
that goes through every point looks excellent, and a test error quoted after
selecting on that very test set looks like an out-of-sample number.

Legs:
  1. capacity  -- the interpolating degree drives the training residual to the
                  rounding floor, and it does so by construction;
  2. monotone  -- training error never rises with degree, which is why it cannot
                  be used to choose one;
  3. ushape    -- test error falls then rises, with an interior minimum;
  4. floor     -- the best test error reached is the noise level, not zero;
  5. falsifier -- choosing the degree on the test set makes that test error an
                  underestimate, measured against a fresh sample;
  6. honest    -- cross-validation inside the training set alone chooses well and
                  its estimate survives contact with the fresh sample.
"""
import math

import numpy as np

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


TRUE_DEGREE = 3
NOISE = 0.15
SAMPLE = 12
rng = np.random.default_rng(20260911)


def truth(points):
    """The function behind the data, a cubic, so the right degree is known."""
    return 1.5 * points ** 3 - 2.0 * points + 0.5


def sample(count):
    points = np.sort(rng.uniform(-1.0, 1.0, count))
    return points, truth(points) + rng.normal(0.0, NOISE, count)


def fit(points, values, degree):
    """Least squares on a domain-mapped basis, so the fit is not fighting
    conditioning at high degree; the subject here is capacity, not arithmetic."""
    return np.polynomial.polynomial.Polynomial.fit(points, values, degree)


def rmse(model, points, values):
    return float(np.sqrt(np.mean((model(points) - values) ** 2)))


train_x, train_y = sample(SAMPLE)
test_x, test_y = sample(400)
fresh_x, fresh_y = sample(400)

DEGREES = list(range(0, SAMPLE))
models = [fit(train_x, train_y, degree) for degree in DEGREES]
train_errors = [rmse(model, train_x, train_y) for model in models]
test_errors = [rmse(model, test_x, test_y) for model in models]


# ---------------------------------------------------------------- leg 1
# The interpolating degree has as many coefficients as there are points, so the
# system is square and the residual is zero up to arithmetic. Nothing is learned
# from that, and the case says so rather than reporting it as a success.
check("the_interpolating_degree_drives_the_training_error_to_the_floor",
      bool(train_errors[-1] < 1e-10),
      f"degree {DEGREES[-1]} on {SAMPLE} points leaves a training error of "
      f"{train_errors[-1]:.3e}, which is the square system being solved and not "
      "a discovery about the data")

noise_targets = rng.normal(0.0, 5.0, SAMPLE)
noise_model = fit(train_x, noise_targets, SAMPLE - 1)
check("and_it_does_so_whatever_the_data_are",
      bool(rmse(noise_model, train_x, noise_targets) < 1e-9),
      f"fitted to pure noise of standard deviation five, the same degree still "
      f"leaves {rmse(noise_model, train_x, noise_targets):.3e}, which is what "
      "calling it arithmetic means")


# ---------------------------------------------------------------- leg 2
descending = all(later <= earlier + 1e-12
                 for earlier, later in zip(train_errors, train_errors[1:]))
check("training_error_never_rises_with_degree",
      descending,
      f"from {train_errors[0]:.4f} at degree 0 down to {train_errors[-1]:.3e} at "
      f"degree {DEGREES[-1]}, never once increasing, so it cannot choose a degree")


# ---------------------------------------------------------------- leg 3
best = int(np.argmin(test_errors))
check("test_error_has_an_interior_minimum",
      0 < best < len(DEGREES) - 1,
      f"the smallest test error is at degree {best}, with neither endpoint "
      f"winning: degree 0 gives {test_errors[0]:.4f} and degree "
      f"{DEGREES[-1]} gives {test_errors[-1]:.4f}")

check("and_that_minimum_sits_at_the_degree_the_data_were_made_with",
      best == TRUE_DEGREE,
      f"degree {best} against the cubic the samples came from")

check("while_the_interpolant_is_far_worse_out_of_sample",
      bool(test_errors[-1] > 10 * test_errors[best]),
      f"test error {test_errors[-1]:.4f} at the interpolating degree against "
      f"{test_errors[best]:.4f} at degree {best}, a factor of "
      f"{test_errors[-1] / test_errors[best]:.1f}, on a training error that was "
      "the smaller of the two")


# ---------------------------------------------------------------- leg 4
# The floor is the noise, not zero: even the true cubic cannot do better than
# the deviations that were added. Computed from the truth rather than assumed.
oracle = float(np.sqrt(np.mean((truth(test_x) - test_y) ** 2)))
check("the_best_attainable_test_error_is_the_noise_level",
      abs(oracle - NOISE) < 4 * NOISE / math.sqrt(2 * len(test_x)),
      f"the true function itself scores {oracle:.4f} against a noise level of "
      f"{NOISE}, inside the {4 * NOISE / math.sqrt(2 * len(test_x)):.4f} that "
      f"{len(test_x)} samples allow")

# A fit with p coefficients estimated from n points carries, in expectation, a
# mean squared error of sigma^2 (1 + p/n) out of sample: the noise it cannot
# beat plus the cost of having estimated the coefficients. That is the level to
# compare against, and it is computed rather than picked.
parameters = best + 1
expected = oracle * math.sqrt(1 + parameters / SAMPLE)
check("and_the_chosen_degree_lands_where_estimation_cost_says_it_should",
      bool(test_errors[best] < expected),
      f"degree {best} scores {test_errors[best]:.4f} against an oracle of "
      f"{oracle:.4f} and an expected {expected:.4f} once the {parameters} "
      f"coefficients estimated from {SAMPLE} points are paid for")


# ---------------------------------------------------------------- leg 5
# Selecting on a held-out set and then quoting that set's error is optimistic,
# but one split cannot establish it and the size of the set decides how much it
# matters. The whole select-and-report procedure is therefore repeated over
# independent splits, at two selection sizes, and the average gap carries the
# claim. A single split here was briefly reported as five per cent optimistic;
# repeated three hundred times at the same size the effect is half a standard
# error from zero, so that five per cent was noise.
REPEATS = 300
SMALL, LARGE = 8, 100


def selection_optimism(selection_size):
    """Choose the degree on a sample of this size, then score on an untouched one."""
    gaps, chosen, landed = [], [], []
    for _ in range(REPEATS):
        probe_x, probe_y = sample(selection_size)
        other_x, other_y = sample(400)
        scores = [rmse(model, probe_x, probe_y) for model in models]
        picked = int(np.argmin(scores))
        chosen.append(picked)
        outside = rmse(models[picked], other_x, other_y)
        landed.append(outside)
        gaps.append(outside - scores[picked])
    spread = float(np.std(gaps, ddof=1) / math.sqrt(REPEATS))
    return (float(np.mean(gaps)), spread, sorted(set(chosen)),
            float(np.mean(landed)))


small_gap, small_error, small_degrees, _small_landed = selection_optimism(SMALL)
large_gap, large_error, large_degrees, large_landed = selection_optimism(LARGE)

check("falsifier_choosing_on_a_small_held_out_set_makes_its_error_optimistic",
      bool(small_gap > 3 * small_error),
      f"selecting on {SMALL} points, the untouched sample scores {small_gap:.5f} "
      f"worse on average than the selecting sample, {small_gap / small_error:.1f} "
      f"standard errors above zero over {REPEATS} splits")

check("because_the_choice_itself_is_unstable_at_that_size",
      len(small_degrees) > len(large_degrees),
      f"the chosen degree wanders over {small_degrees} at {SMALL} points and "
      f"settles to {large_degrees} at {LARGE}, and it is the wandering that the "
      "winner's curse feeds on")

# The bias above sits on top of a procedure that works: the degree chosen on a
# large set really is a good one. Without this the leg would pass just as well
# if the selection picked the WORST degree every time, which is a different
# phenomenon wearing the same numbers.
check("and_the_selection_does_pick_a_good_model_when_the_set_is_large",
      bool(large_landed < 1.5 * oracle),
      f"the degree chosen on {LARGE} points scores {large_landed:.4f} on untouched "
      f"data against an oracle of {oracle:.4f}")

check("and_the_optimism_shrinks_with_the_selection_set_rather_than_being_fixed",
      bool(small_gap > 10 * abs(large_gap)),
      f"the gap falls from {small_gap:.5f} at {SMALL} points to {large_gap:.5f} "
      f"at {LARGE}, a factor of {small_gap / abs(large_gap):.0f}, so the failure "
      "is in how noisily the choice is made and not in holding out as such")


# ---------------------------------------------------------------- leg 6
def cross_validated(points, values, degree, folds=4):
    """Leave-one-fold-out error, using only the training sample."""
    order = np.arange(len(points))
    scores = []
    for fold in range(folds):
        held = order % folds == fold
        if held.all() or (~held).all():
            continue
        model = fit(points[~held], values[~held], degree)
        scores.append(rmse(model, points[held], values[held]))
    return float(np.mean(scores))


DEGREE_RANGE = list(range(0, SAMPLE // 2))
cv_scores = [cross_validated(train_x, train_y, degree) for degree in DEGREE_RANGE]
cv_choice = DEGREE_RANGE[int(np.argmin(cv_scores))]
check("cross_validation_inside_the_training_sample_picks_a_sane_degree",
      abs(cv_choice - TRUE_DEGREE) <= 1,
      f"it chooses degree {cv_choice} against the true {TRUE_DEGREE}, having "
      f"never seen the test or the fresh sample")

cv_model = fit(train_x, train_y, cv_choice)
cv_fresh = rmse(cv_model, fresh_x, fresh_y)
check("and_its_choice_survives_contact_with_the_untouched_sample",
      bool(cv_fresh < 2 * oracle),
      f"the cross-validated model scores {cv_fresh:.4f} on the untouched sample "
      f"against an oracle of {oracle:.4f}, while the interpolant would have "
      f"scored {rmse(models[-1], fresh_x, fresh_y):.4f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
