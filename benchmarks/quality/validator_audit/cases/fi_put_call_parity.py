"""Parity holds in every model, so checking it validates none of them.

CLAIM: a long call and a short put pay the forward at expiry whatever the
underlying does, which fixes C - P = S - K exp(-rT) by replication and without
any model at all; Black-Scholes satisfies that identity symbolically, and so does
the Bachelier model, whose prices are otherwise different; calibrating the second
to match the first at the money still leaves them disagreeing away from it; a
model that breaks parity admits a riskless profit equal to the breach, computed
here; and what does separate the two models is pricing against the dynamics
assumed, where a simulation of lognormal paths matches one and not the other.

The escalation is the point. Parity is necessary and every arbitrage-free model
has it, so a validator that checks parity has checked that its model is not
absurd, not that it is right, and adding one matched price does not rescue it.

Legs:
  1. replicate -- the terminal payoff is the forward in both regions, so parity
                  is a statement about payoffs and not about a model;
  2. black     -- the Black-Scholes prices satisfy the identity symbolically;
  3. bachelier -- so do the normal-model prices, with different formulas;
  4. calibrate -- the second is matched to the first at the money, which is a
                  construction and is reported as one;
  5. falsifier -- and away from the money the two disagree materially, so parity
                  and one matched price still do not identify the model;
  6. arbitrage -- a breach of parity is a riskless profit, exhibited as a
                  portfolio whose terminal value is identically zero;
  7. separate  -- simulation under the assumed dynamics does discriminate.
"""
import math

import numpy as np
import sympy as sp

spot, strike, rate, horizon, vol = sp.symbols("S K r T sigma", positive=True)
terminal = sp.Symbol("S_T", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def normal_cdf(value):
    return (1 + sp.erf(value / sp.sqrt(2))) / 2


# ---------------------------------------------------------------- leg 1
call_payoff = sp.Max(terminal - strike, 0)
put_payoff = sp.Max(strike - terminal, 0)


def by_region(expression):
    """The expression above and below the strike, with the maxima resolved.

    A maximum carries no sign information, so no simplifier will fold the
    difference of two of them; the identity is a statement about two regions and
    it is proved by entering each of them.
    """
    high = sp.simplify(
        expression.subs(call_payoff, terminal - strike).subs(put_payoff, 0))
    low = sp.simplify(
        expression.subs(call_payoff, 0).subs(put_payoff, strike - terminal))
    return high, low


forward_high, forward_low = by_region(call_payoff - put_payoff)
check("the_combination_pays_the_forward_whatever_the_underlying_does",
      sp.simplify(forward_high - (terminal - strike)) == 0
      and sp.simplify(forward_low - (terminal - strike)) == 0,
      f"above the strike it pays {forward_high} and below it {forward_low}, the "
      "same forward in both regions and no optionality left in either")

above = sp.simplify((call_payoff - put_payoff).subs(terminal, strike * 2))
below = sp.simplify((call_payoff - put_payoff).subs(terminal, strike / 2))
check("and_the_two_regions_are_checked_separately",
      sp.simplify(above - strike) == 0 and sp.simplify(below + strike / 2) == 0,
      f"at twice the strike it pays {above} and at half the strike {below}, so "
      "neither branch was assumed away")


# ---------------------------------------------------------------- leg 2
d_one = (sp.log(spot / strike) + (rate + vol ** 2 / 2) * horizon) / (
    vol * sp.sqrt(horizon))
d_two = d_one - vol * sp.sqrt(horizon)
black_call = spot * normal_cdf(d_one) - strike * sp.exp(-rate * horizon) * normal_cdf(d_two)
black_put = (strike * sp.exp(-rate * horizon) * normal_cdf(-d_two)
             - spot * normal_cdf(-d_one))
black_parity = sp.simplify(
    black_call - black_put - (spot - strike * sp.exp(-rate * horizon))
)
check("the_black_scholes_prices_satisfy_parity_identically",
      black_parity == 0,
      f"C - P - (S - K e^-rT) simplifies to {black_parity} for every strike, "
      "spot, rate, horizon and volatility")


# ---------------------------------------------------------------- leg 3
forward = spot * sp.exp(rate * horizon)
normal_vol = sp.Symbol("sigma_N", positive=True)
d_normal = (forward - strike) / (normal_vol * sp.sqrt(horizon))
bell = sp.exp(-d_normal ** 2 / 2) / sp.sqrt(2 * sp.pi)
bachelier_call = sp.exp(-rate * horizon) * (
    (forward - strike) * normal_cdf(d_normal) + normal_vol * sp.sqrt(horizon) * bell
)
bachelier_put = sp.exp(-rate * horizon) * (
    (strike - forward) * normal_cdf(-d_normal) + normal_vol * sp.sqrt(horizon) * bell
)
bachelier_parity = sp.simplify(
    bachelier_call - bachelier_put - (spot - strike * sp.exp(-rate * horizon))
)
check("the_normal_model_prices_satisfy_the_same_identity",
      bachelier_parity == 0,
      f"a completely different pair of formulas gives {bachelier_parity} for the "
      "same difference, which is what makes parity useless as a test of either")


# ---------------------------------------------------------------- leg 4
SPOT, RATE, HORIZON, VOL = 100.0, 0.03, 1.0, 0.25
FORWARD = SPOT * math.exp(RATE * HORIZON)


def cumulative(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_price(price, kay, years, sigma, interest):
    first = (math.log(price / kay) + (interest + sigma ** 2 / 2) * years) / (
        sigma * math.sqrt(years))
    second = first - sigma * math.sqrt(years)
    return price * cumulative(first) - kay * math.exp(-interest * years) * cumulative(second)


def normal_price(price, kay, years, sigma_normal, interest):
    ahead = price * math.exp(interest * years)
    moneyness = (ahead - kay) / (sigma_normal * math.sqrt(years))
    density = math.exp(-moneyness ** 2 / 2) / math.sqrt(2 * math.pi)
    return math.exp(-interest * years) * (
        (ahead - kay) * cumulative(moneyness) + sigma_normal * math.sqrt(years) * density
    )


# At the money the Black-Scholes call is S times twice the cumulative at half the
# variance minus one, and the normal call is the discounted density term, so the
# matching volatility can be written down rather than searched for.
at_money = SPOT * (2 * cumulative(VOL * math.sqrt(HORIZON) / 2) - 1)
NORMAL_VOL = (at_money * math.exp(RATE * HORIZON) * math.sqrt(2 * math.pi)
              / math.sqrt(HORIZON))
check("the_normal_volatility_is_solved_to_match_at_the_money",
      abs(normal_price(SPOT, FORWARD, HORIZON, NORMAL_VOL, RATE)
          - black_price(SPOT, FORWARD, HORIZON, VOL, RATE)) < 1e-10,
      f"a normal volatility of {NORMAL_VOL:.4f} reproduces the Black-Scholes "
      f"price of {black_price(SPOT, FORWARD, HORIZON, VOL, RATE):.6f} at the "
      "forward; this is a calibration and is reported as one, not as agreement")


# ---------------------------------------------------------------- leg 5
STRIKES = [60.0, 80.0, 120.0, 150.0]
gaps = {
    kay: normal_price(SPOT, kay, HORIZON, NORMAL_VOL, RATE)
         - black_price(SPOT, kay, HORIZON, VOL, RATE)
    for kay in STRIKES
}
relative = {kay: gaps[kay] / black_price(SPOT, kay, HORIZON, VOL, RATE)
            for kay in STRIKES}
check("falsifier_away_from_the_money_the_two_models_disagree",
      max(abs(value) for value in relative.values()) > 0.2,
      "the normal model differs from Black-Scholes by "
      + ", ".join(f"{100 * relative[kay]:+.1f} per cent at {kay:.0f}"
                  for kay in STRIKES))

def black_put_price(price, kay, years, sigma, interest):
    return (kay * math.exp(-interest * years)
            - price + black_price(price, kay, years, sigma, interest))


def normal_put_price(price, kay, years, sigma_normal, interest):
    ahead = price * math.exp(interest * years)
    moneyness = (ahead - kay) / (sigma_normal * math.sqrt(years))
    density = math.exp(-moneyness ** 2 / 2) / math.sqrt(2 * math.pi)
    return math.exp(-interest * years) * (
        (kay - ahead) * cumulative(-moneyness) + sigma_normal * math.sqrt(years) * density
    )


# The put is priced from its own formula in the normal model, so the check below
# is a real one; taking it from parity would make the parity test circular.
both_parities = {
    kay: max(
        abs(black_price(SPOT, kay, HORIZON, VOL, RATE)
            - black_put_price(SPOT, kay, HORIZON, VOL, RATE)
            - (SPOT - kay * math.exp(-RATE * HORIZON))),
        abs(normal_price(SPOT, kay, HORIZON, NORMAL_VOL, RATE)
            - normal_put_price(SPOT, kay, HORIZON, NORMAL_VOL, RATE)
            - (SPOT - kay * math.exp(-RATE * HORIZON))),
    )
    for kay in STRIKES
}
check("while_both_still_satisfy_parity_at_every_one_of_those_strikes",
      all(value < 1e-12 for value in both_parities.values()),
      "parity is an identity in each model and stays exact wherever the prices "
      "differ, so it cannot be the thing that separates them")


# ---------------------------------------------------------------- leg 6
breach = sp.Symbol("delta", positive=True)
# A quoted call too dear by delta: sell it, buy the put, buy the stock, borrow
# the discounted strike. Terminal value of that book, for any outcome.
book_high, book_low = by_region(-call_payoff + put_payoff + terminal - strike)
check("a_portfolio_against_a_parity_breach_is_worth_nothing_at_expiry",
      book_high == 0 and book_low == 0,
      f"the book settles at {book_high} above the strike and {book_low} below "
      "it, so its value at expiry is zero for every outcome")

# What it costs to put on, using the Black-Scholes put and the parity of leg 2.
# The quoted call is dear by delta and everything else is at its model price.
opening = sp.simplify(
    (black_call + breach) - black_put - spot + strike * sp.exp(-rate * horizon)
)
check("so_the_breach_itself_is_the_riskless_profit",
      sp.simplify(opening - breach) == 0,
      f"the book opens for {opening} and settles at nothing, so a model quoting "
      "a price off parity by delta hands delta over for no risk at all")


# ---------------------------------------------------------------- leg 7
PATHS = 400000
rng = np.random.default_rng(20260912)
shocks = rng.normal(size=PATHS)
endings = SPOT * np.exp((RATE - VOL ** 2 / 2) * HORIZON
                        + VOL * math.sqrt(HORIZON) * shocks)
PROBE = 120.0
payoffs = np.maximum(endings - PROBE, 0.0) * math.exp(-RATE * HORIZON)
simulated = float(payoffs.mean())
standard_error = float(payoffs.std(ddof=1) / math.sqrt(PATHS))

black_at_probe = black_price(SPOT, PROBE, HORIZON, VOL, RATE)
normal_at_probe = normal_price(SPOT, PROBE, HORIZON, NORMAL_VOL, RATE)
check("simulating_the_assumed_dynamics_matches_black_scholes",
      abs(simulated - black_at_probe) < 3 * standard_error,
      f"the simulated price is {simulated:.4f} against {black_at_probe:.4f}, "
      f"inside three standard errors of {standard_error:.4f}")

check("and_separates_it_from_the_normal_model_by_many_standard_errors",
      abs(simulated - normal_at_probe) > 20 * standard_error,
      f"the same simulation sits {abs(simulated - normal_at_probe) / standard_error:.0f} "
      f"standard errors from the normal model's {normal_at_probe:.4f}, so what "
      "discriminates is the dynamics and never the identity")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
