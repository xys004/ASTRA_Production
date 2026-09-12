"""Above Nyquist a tone is indistinguishable from its alias, below it is not.

CLAIM: sampling cos(2 pi f t) at rate fs produces samples identical to those of
cos(2 pi (f + k fs) t) for every integer k, and identical to those of
cos(2 pi (fs - f) t); below fs/2 two distinct tones always produce distinguishable
sample sequences; and a band-limited signal is recovered exactly by sinc
interpolation of its samples.

The aliasing identities are proved symbolically at the sample times and then
confirmed to machine precision on real sample arrays, so a failure of either
would be localised by disagreement with the other. Exact bit equality is NOT
claimed: the arguments differ by a multiple of 2 pi before the cosine is taken,
and that shift is rounded.

Legs:
  1. periodicity  -- adding a whole sampling rate to the frequency leaves every
                     sample unchanged, shown symbolically at t = n/fs;
  2. folding      -- the reflection f -> fs - f also leaves the samples of a
                     cosine unchanged, which is what makes the fold two-sided;
  3. below        -- under Nyquist, distinct tones separate, with the smallest
                     separation over a grid reported rather than assumed;
  4. reconstruct  -- sinc interpolation of the samples reproduces the original
                     signal away from the edges of the window;
  5. falsifier    -- a tone above Nyquist is reconstructed as its alias, not as
                     itself, which is the failure the theorem predicts.
"""
import math

import sympy as sp

f, fs = sp.symbols("f f_s", positive=True)

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def samples(freq, rate, count):
    """Samples of cos(2 pi freq t) at t = i/rate, exact floating point."""
    return [math.cos(2 * math.pi * freq * i / rate) for i in range(count)]


# ---------------------------------------------------------------- leg 1
integer_n = sp.Symbol("n", integer=True)
integer_k = sp.Symbol("k", integer=True)
base_sample = sp.cos(2 * sp.pi * f * integer_n / fs)
shifted_sample = sp.cos(2 * sp.pi * (f + integer_k * fs) * integer_n / fs)
periodicity_gap = sp.simplify(sp.expand_trig(shifted_sample - base_sample))
check("adding_a_sampling_rate_leaves_every_sample_unchanged",
      periodicity_gap == 0,
      f"cos(2 pi (f + k fs) n/fs) - cos(2 pi f n/fs) = {periodicity_gap}")

# On real arrays the agreement is to machine precision, not bit for bit: the
# arguments differ by 2 pi n before the cosine is taken, and that difference is
# rounded. Claiming exact equality would be a stronger statement than floating
# point supports, so the figure is reported instead of asserted away.
FS = 1000.0
shift_error = max(
    abs(a - b) for a, b in zip(samples(137.0, FS, 64), samples(137.0 + FS, FS, 64))
)
check("numeric_samples_agree_to_machine_precision_under_the_shift",
      shift_error < 1e-12,
      f"64 samples of 137 Hz and 1137 Hz at 1000 Hz differ by at most "
      f"{shift_error:.3e}, which is rounding of the 2 pi n argument shift")


# ---------------------------------------------------------------- leg 2
reflected_sample = sp.cos(2 * sp.pi * (fs - f) * integer_n / fs)
folding_gap = sp.simplify(sp.expand_trig(reflected_sample - base_sample))
check("reflection_about_the_sampling_rate_also_leaves_samples_unchanged",
      folding_gap == 0,
      f"cos(2 pi (fs - f) n/fs) - cos(2 pi f n/fs) = {folding_gap}")

folded_numeric = max(
    abs(a - b) for a, b in zip(samples(300.0, FS, 64), samples(700.0, FS, 64))
)
check("three_hundred_and_seven_hundred_hertz_are_indistinguishable",
      folded_numeric < 1e-12,
      f"largest sample difference {folded_numeric:.3e} at fs = 1000 Hz")


# ---------------------------------------------------------------- leg 3
# Below Nyquist, every pair of distinct tones must separate. Report the
# SMALLEST separation found, so the claim rests on the worst case.
nyquist = FS / 2
candidates = [25.0 * i for i in range(1, 20)]         # 25 .. 475 Hz, all under 500
assert all(freq < nyquist for freq in candidates)
separations = []
for i, first in enumerate(candidates):
    for second in candidates[i + 1:]:
        separations.append(max(
            abs(a - b) for a, b in zip(samples(first, FS, 256), samples(second, FS, 256))
        ))

# `worst is not None` would be a check that cannot fail, since the loops above
# always run. The content is that every pair separated, and that the expected
# number of pairs was actually compared.
expected_pairs = len(candidates) * (len(candidates) - 1) // 2
check("every_pair_below_nyquist_was_compared",
      len(separations) == expected_pairs,
      f"{len(separations)} pairs compared, {expected_pairs} expected")
check("distinct_tones_below_nyquist_always_separate",
      min(separations) > 0.1,
      f"smallest separation over {len(candidates)} tones = {min(separations):.6f}")


# ---------------------------------------------------------------- leg 4
def sinc_reconstruct(sample_values, rate, at_time):
    """Whittaker-Shannon interpolation from the samples."""
    total = 0.0
    for index, value in enumerate(sample_values):
        argument = math.pi * (at_time * rate - index)
        weight = 1.0 if argument == 0.0 else math.sin(argument) / argument
        total += value * weight
    return total


TONE = 120.0
COUNT = 4096
values = samples(TONE, FS, COUNT)
# Evaluate well inside the window, where truncation of the infinite sum is
# smallest; near the edges the sum is badly incomplete.
probe_times = [(COUNT / 2 + offset) / FS for offset in (0.25, 0.5, 1.5, 2.25)]
errors = [
    abs(sinc_reconstruct(values, FS, t) - math.cos(2 * math.pi * TONE * t))
    for t in probe_times
]

# The interpolation sum is infinite and this one is truncated, so the residual
# is a property of the window rather than of the theorem. Rather than choosing a
# tolerance, show that it SHRINKS as the window grows: that is the statement the
# reconstruction theorem actually makes.
def centre_error(count):
    window = samples(TONE, FS, count)
    times = [(count / 2 + offset) / FS for offset in (0.25, 0.5, 1.5, 2.25)]
    return max(
        abs(sinc_reconstruct(window, FS, t) - math.cos(2 * math.pi * TONE * t))
        for t in times
    )


small = centre_error(1024)
large = max(errors)
check("sinc_interpolation_reproduces_a_band_limited_tone",
      large < small and large < 1e-5,
      f"error falls from {small:.3e} at 1024 samples to {large:.3e} at {COUNT}, "
      "so the residual is window truncation and not a failure of the theorem")

edge_error = abs(
    sinc_reconstruct(values, FS, 1.5 / FS) - math.cos(2 * math.pi * TONE * 1.5 / FS)
)
check("truncation_near_the_edge_is_visible_and_stated",
      edge_error > max(errors),
      f"error at the third sample is {edge_error:.3e}, larger than at the centre, "
      "because the interpolation sum is truncated there")


# ---------------------------------------------------------------- leg 5
# A tone above Nyquist is reconstructed as its alias. This is the theorem's own
# prediction of failure, so seeing it is confirmation rather than a problem.
ABOVE = 700.0
ALIAS = FS - ABOVE           # 300 Hz
above_values = samples(ABOVE, FS, COUNT)
alias_error = max(
    abs(sinc_reconstruct(above_values, FS, t) - math.cos(2 * math.pi * ALIAS * t))
    for t in probe_times
)
true_error = max(
    abs(sinc_reconstruct(above_values, FS, t) - math.cos(2 * math.pi * ABOVE * t))
    for t in probe_times
)
check("falsifier_above_nyquist_reconstructs_the_alias_not_the_tone",
      alias_error < 1e-6 < true_error,
      f"error against the 300 Hz alias {alias_error:.3e}, against the true "
      f"700 Hz tone {true_error:.3e}")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
