"""The sample mean attains the Cramer-Rao bound, and a biased estimator beats it.

CLAIM: for n independent draws from N(mu, sigma^2) with sigma known, the score
equation solves to the sample mean; the Fisher information is n/sigma^2 by both
of its definitions; the variance of the sample mean equals 1/I, so the bound is
attained; an unbiased estimator built from fewer observations sits strictly above
it; and a shrunk estimator sits strictly BELOW it without contradicting anything,
because the bound is a statement about unbiased estimators only.

The last leg is the reason for the case. "No estimator can do better than 1/I"
is false as usually written, and a validator that never tests the unbiasedness
hypothesis cannot tell the difference. Every exact result is also measured by
simulation, with the tolerance derived from the number of replicates rather than
chosen.

Legs:
  1. score     -- the log-likelihood is differentiated and the stationary point
                  SOLVED for, then shown to be a maximum by the second derivative;
  2. fisher    -- both definitions of the information are computed, from the
                  curvature and from the squared score, and must agree;
  3. efficient -- the exact variance of the sample mean equals the reciprocal of
                  the information;
  4. bound     -- a different unbiased estimator lies strictly above it, so the
                  bound is a bound and not an identity;
  5. numeric   -- a search that never uses the analytic answer locates the same
                  maximiser, and simulation reproduces both variances;
  6. falsifier -- a shrunk estimator has variance and mean squared error below
                  1/I, and its bias is exhibited, which is what puts it outside
                  the theorem rather than against it.
"""
import math
import random

import sympy as sp
from sympy.stats import E as expectation
from sympy.stats import Normal, variance

mu = sp.Symbol("mu", real=True)
sigma = sp.Symbol("sigma", positive=True)
n = sp.Symbol("n", positive=True, integer=True)
i = sp.Symbol("i", positive=True, integer=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def as_float(expression):
    """A plain float, or nan when free symbols survive the substitution.

    Returning nan keeps an upstream mistake visible as a failed check rather than
    a traceback, which would hide which leg actually went wrong.
    """
    value = sp.N(expression)
    return float(value) if value.is_number and value.is_real else math.nan



# ---------------------------------------------------------------- leg 1
# Two representations are used, and the split is deliberate. The curvature holds
# for symbolic n because its summand does not depend on the index, so sympy can
# evaluate that sum; the score does depend on the data, and a sum over indexed
# symbols stays unevaluated no matter how often doit() is called, which leaves a
# solver nothing to work on. So the stationary point is derived over an explicit
# sample of SAMPLE_SIZE symbols, and nothing below claims otherwise.
SAMPLE_SIZE = 4
data_symbols = sp.symbols(f"x1:{SAMPLE_SIZE + 1}", real=True)


def log_density(value):
    return -sp.log(sp.sqrt(2 * sp.pi) * sigma) - (value - mu) ** 2 / (2 * sigma ** 2)


log_likelihood = sum(log_density(value) for value in data_symbols)
score = sp.simplify(sp.diff(log_likelihood, mu))
check("the_score_is_the_summed_residual_over_the_variance",
      sp.simplify(score - (sum(data_symbols) - SAMPLE_SIZE * mu) / sigma ** 2) == 0,
      f"dl/dmu = {score}")

stationary = sp.solve(sp.Eq(score, 0), mu)
sample_mean = sum(data_symbols) / SAMPLE_SIZE
check("the_score_equation_has_a_single_stationary_point",
      len(stationary) == 1,
      f"dl/dmu = 0 at mu = {stationary or 'nothing'}")

solved = sp.simplify(sum(stationary)) if stationary else sp.nan
check("that_stationary_point_is_the_sample_mean",
      sp.simplify(solved - sample_mean) == 0,
      f"mu_hat = {solved}")

# The curvature, where the general n does survive.
x = sp.IndexedBase("x")
general_likelihood = sp.Sum(log_density(x[i]), (i, 1, n))
curvature = sp.simplify(sp.diff(general_likelihood, mu, 2).doit())
check("the_stationary_point_is_a_maximum_not_a_minimum",
      sp.simplify(curvature + n / sigma ** 2) == 0
      and curvature.is_negative is True,
      f"d2l/dmu2 = {curvature}, negative for every n and sigma, so the "
      "stationary point maximises")


# ---------------------------------------------------------------- leg 2
information_from_curvature = sp.simplify(-curvature)
check("the_information_from_the_curvature_is_n_over_sigma_squared",
      sp.simplify(information_from_curvature - n / sigma ** 2) == 0,
      f"-E[d2l/dmu2] = {information_from_curvature}, the curvature being "
      "deterministic here so the expectation leaves it unchanged")

# The other definition, I = E[(dl/dmu)^2], needs the joint law rather than a
# derivative, so it is computed over actual random variables at the same sample
# size. Agreement of the two is a real constraint: they coincide only because
# the score has mean zero, which is itself a property of the model.
draws = [Normal(f"X_{index}", mu, sigma) for index in range(SAMPLE_SIZE)]
realised_score = (sum(draws) - SAMPLE_SIZE * mu) / sigma ** 2
check("the_score_has_mean_zero",
      sp.simplify(expectation(realised_score)) == 0,
      f"E[dl/dmu] = {sp.simplify(expectation(realised_score))}")

information_from_score = sp.simplify(expectation(realised_score ** 2))
check("both_definitions_of_the_information_agree",
      sp.simplify(information_from_score
                  - information_from_curvature.subs(n, SAMPLE_SIZE)) == 0,
      f"E[(dl/dmu)^2] = {information_from_score} against "
      f"{sp.simplify(information_from_curvature.subs(n, SAMPLE_SIZE))} from the curvature")


# ---------------------------------------------------------------- leg 3
estimator_mean = sum(draws) / SAMPLE_SIZE
check("the_sample_mean_is_unbiased",
      sp.simplify(expectation(estimator_mean) - mu) == 0,
      f"E[mu_hat] = {sp.simplify(expectation(estimator_mean))}")

variance_mean = sp.simplify(variance(estimator_mean))
bound = sp.simplify(1 / information_from_score)
check("the_sample_mean_attains_the_cramer_rao_bound",
      sp.simplify(variance_mean - bound) == 0,
      f"Var[mu_hat] = {variance_mean} and 1/I = {bound}")


# ---------------------------------------------------------------- leg 4
# Averaging two of the four observations is still unbiased, so the theorem does
# apply to it, and it must therefore sit above the bound.
estimator_pair = (draws[0] + draws[1]) / 2
check("the_two_observation_average_is_also_unbiased",
      sp.simplify(expectation(estimator_pair) - mu) == 0,
      f"E[mu_pair] = {sp.simplify(expectation(estimator_pair))}")

variance_pair = sp.simplify(variance(estimator_pair))
# Asked as is_positive rather than as bool(expr > 0). The two differ when the
# sign cannot be decided: the first answers None, which fails the check, while
# the second raises. An undecidable sign is not a pass, and it is not a crash
# either; it is a result the check has to report.
check("an_unbiased_estimator_that_ignores_data_sits_above_the_bound",
      sp.simplify(variance_pair - bound).is_positive is True,
      f"Var[mu_pair] = {variance_pair} against the bound {bound}, a ratio of "
      f"{sp.simplify(variance_pair / bound)}")


# ---------------------------------------------------------------- leg 5
MU_TRUE, SIGMA_TRUE = 3.0, 2.0
REPLICATES = 200000
# Exact, not 0.9: a binary float leaves a residue of order 1e-17 times mu squared
# in the symbolic variance below, and sympy then cannot decide the sign of the
# comparison at all. The simulation uses the float form of the same number.
SHRINK = sp.Rational(9, 10)
SHRINK_NUMERIC = float(SHRINK)
rng = random.Random(20260911)


def log_likelihood_at(candidate, data):
    """The objective itself, with no reference to the analytic maximiser."""
    return sum(
        -math.log(math.sqrt(2 * math.pi) * SIGMA_TRUE)
        - (value - candidate) ** 2 / (2 * SIGMA_TRUE ** 2)
        for value in data
    )


def ternary_search(data, lower, upper):
    """Maximise by bracketing, which knows nothing about sample means."""
    for _ in range(400):
        first = lower + (upper - lower) / 3
        second = upper - (upper - lower) / 3
        if log_likelihood_at(first, data) < log_likelihood_at(second, data):
            lower = first
        else:
            upper = second
    return (lower + upper) / 2


one_sample = [rng.gauss(MU_TRUE, SIGMA_TRUE) for _ in range(SAMPLE_SIZE)]
located = ternary_search(one_sample, -50.0, 50.0)
arithmetic_mean = sum(one_sample) / SAMPLE_SIZE

# A maximiser cannot be located to machine precision, and asking for it would be
# a wrong claim rather than a strict one. Near the peak the objective moves by
# (n / 2 sigma^2) d^2 for a displacement d, so once d falls below the square root
# of the objective's own resolution the search is reading rounding. That floor is
# computed here and the observed gap is reported against it.
objective_resolution = abs(log_likelihood_at(arithmetic_mean, one_sample)) * 2.220446e-16
locating_floor = math.sqrt(
    2 * objective_resolution * SIGMA_TRUE ** 2 / SAMPLE_SIZE
)
check("a_blind_search_lands_on_the_sample_mean",
      abs(located - arithmetic_mean) < 3 * locating_floor,
      f"search gave {located:.12f}, the sample mean is {arithmetic_mean:.12f}, "
      f"apart by {abs(located - arithmetic_mean):.3e} against a floor of "
      f"{locating_floor:.3e} set by the curvature and the machine epsilon")

means, pairs, shrunk = [], [], []
for _ in range(REPLICATES):
    batch = [rng.gauss(MU_TRUE, SIGMA_TRUE) for _ in range(SAMPLE_SIZE)]
    average = sum(batch) / SAMPLE_SIZE
    means.append(average)
    pairs.append((batch[0] + batch[1]) / 2)
    shrunk.append(SHRINK_NUMERIC * average)


def moments(values):
    centre = sum(values) / len(values)
    spread = sum((value - centre) ** 2 for value in values) / (len(values) - 1)
    return centre, spread


# The tolerance follows the number of replicates instead of being chosen: the
# relative standard error of an estimated variance is sqrt(2/M), and six of those
# is the band used below.
RELATIVE_TOLERANCE = 6 * math.sqrt(2.0 / REPLICATES)
exact_mean_variance = as_float(variance_mean.subs({sigma: SIGMA_TRUE}))
exact_pair_variance = as_float(variance_pair.subs({sigma: SIGMA_TRUE}))

_, simulated_mean_variance = moments(means)
check("simulation_reproduces_the_variance_of_the_sample_mean",
      abs(simulated_mean_variance - exact_mean_variance) / exact_mean_variance
      < RELATIVE_TOLERANCE,
      f"simulated {simulated_mean_variance:.6f} against exact "
      f"{exact_mean_variance:.6f}, band {RELATIVE_TOLERANCE:.2%} from "
      f"{REPLICATES} replicates")

_, simulated_pair_variance = moments(pairs)
check("simulation_reproduces_the_variance_of_the_two_observation_average",
      abs(simulated_pair_variance - exact_pair_variance) / exact_pair_variance
      < RELATIVE_TOLERANCE,
      f"simulated {simulated_pair_variance:.6f} against exact "
      f"{exact_pair_variance:.6f}")


# ---------------------------------------------------------------- leg 6
# Shrinking the sample mean drops its variance below 1/I. Nothing is broken: the
# theorem speaks about unbiased estimators, and this one is not.
estimator_shrunk = SHRINK * estimator_mean
variance_shrunk = sp.simplify(variance(estimator_shrunk))
check("falsifier_a_shrunk_estimator_has_variance_below_the_bound",
      sp.simplify(variance_shrunk - bound).is_negative is True,
      f"Var = {variance_shrunk} against the bound {bound}, a ratio of "
      f"{sp.simplify(variance_shrunk / bound)}")

bias = sp.simplify(expectation(estimator_shrunk) - mu)
bias_at_truth = as_float(bias.subs(mu, MU_TRUE))
check("and_it_is_biased_which_is_what_puts_it_outside_the_theorem",
      sp.simplify(bias - (SHRINK - 1) * mu) == 0 and abs(bias_at_truth) > 0,
      f"bias = {bias}, which is {bias_at_truth:.4f} at mu = {MU_TRUE}, so the "
      "hypothesis of the bound fails and no contradiction arises")

# Its mean squared error is below the bound too, at this mu, which is the part
# that makes the unbiasedness hypothesis worth stating.
mean_squared_error = sp.simplify(variance_shrunk + bias ** 2)
at_truth = as_float(mean_squared_error.subs({sigma: SIGMA_TRUE, mu: MU_TRUE}))
check("its_mean_squared_error_also_sits_below_the_bound_here",
      at_truth < as_float(bound.subs(sigma, SIGMA_TRUE)),
      f"MSE = {at_truth:.6f} against 1/I = {as_float(bound.subs(sigma, SIGMA_TRUE)):.6f} "
      f"at mu = {MU_TRUE}")

simulated_bias = sum(shrunk) / len(shrunk) - MU_TRUE
expected_bias = as_float(bias.subs(mu, MU_TRUE))
standard_error = math.sqrt(as_float(variance_shrunk.subs(sigma, SIGMA_TRUE)) / REPLICATES)
check("simulation_sees_the_same_bias",
      abs(simulated_bias - expected_bias) < 6 * standard_error,
      f"simulated bias {simulated_bias:.6f} against {expected_bias:.6f}, "
      f"six standard errors being {6 * standard_error:.6f}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
