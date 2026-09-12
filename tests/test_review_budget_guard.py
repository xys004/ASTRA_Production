"""Budget-aware review/repair loop: stop clean instead of busting the wall.

Ported from ASTRA 2.0 (2026-09-05). The review loop ran until
ASTRA_VNEXT_MODEL_PATCH_MAX_REVISIONS with no check on the remaining wall, so
on a hard case the reviewer correctly rejected a defective validator up to the
cap and the cycle blew past the 1500 s wall -> hard-killed PARTIAL, no
certification. The fix reserves budget for what still has to run and refuses a
review/repair round that cannot fit, returning a clean "budget exhausted"
with the last real source preserved.

These tests pin the arithmetic the guard depends on -- the CycleBudget reserve
clamp and review_round_reserve -- deterministically, with an injected clock and
no model calls. They do NOT relax the reviewer: the rejections that trigger the
loop are genuine (undefined names, hard-coded PASS, tautologies), so the fix is
about failing clean and fast, not about approving weaker validators.
"""
import os
import unittest
from unittest.mock import patch

from astra_tool import (
    PHASE_MIN_USEFUL_SECONDS,
    _phase_downstream_reserve,
    review_round_reserve,
)
from core.cycle_budget import CycleBudget


def _budget(total, elapsed, buffer=60.0):
    # elapsed_seconds is clock() - started, with started taken on construction:
    # the fake clock returns 0 on the first call and `elapsed` after.
    calls = {"n": 0}

    def clock():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else elapsed

    return CycleBudget(total, return_buffer_seconds=buffer, clock=clock)


class PhaseTimeoutIsAdditive(unittest.TestCase):
    """Omitting reserve/share reproduces the historical clamp exactly."""

    def test_no_reserve_no_share_is_the_old_clamp(self):
        b = _budget(1000, 0)  # usable = 940
        self.assertEqual(b.phase_timeout(500, default_seconds=240), 500)
        self.assertEqual(b.phase_timeout(2000, default_seconds=240), 940)

    def test_reserve_is_subtracted_from_usable(self):
        b = _budget(1000, 0)  # usable = 940
        self.assertEqual(b.phase_timeout(2000, reserve_seconds=300), 640)
        # reserve never drives below the minimum floor
        b2 = _budget(1000, 900)  # usable = 40
        self.assertEqual(b2.phase_timeout(500, reserve_seconds=300), 1)

    def test_share_caps_at_a_fraction_of_usable(self):
        b = _budget(1000, 0)  # usable = 940
        self.assertEqual(b.phase_timeout(2000, share=0.3), 282)


class ReviewRoundReserve(unittest.TestCase):
    def test_terminal_round_reserves_only_the_tail(self):
        # Revisions spent: only execute/analyze/navigate can follow.
        self.assertEqual(
            review_round_reserve(2, 2, _budget(1500, 0)),
            _phase_downstream_reserve("TRANSLATOR_REPAIR"),
        )

    def test_revision_possible_with_room_reserves_repair_plus_tail(self):
        self.assertEqual(
            review_round_reserve(0, 2, _budget(1500, 0)),  # usable ~1440
            _phase_downstream_reserve("REVIEWER"),
        )

    def test_revision_possible_but_tight_downgrades_to_tail(self):
        # Usable below the repair-follows reserve: a repair can't be afforded
        # even if permitted, so don't refuse a review the cycle can still run.
        tight = _budget(1500, 1300)  # usable = 140 < 280
        self.assertEqual(
            review_round_reserve(0, 2, tight),
            _phase_downstream_reserve("TRANSLATOR_REPAIR"),
        )

    def test_no_inversion_band_just_above_the_full_reserve(self):
        # usable in [REVIEWER, REVIEWER+min_useful) must NOT keep the full
        # reserve (that would starve a review a lower-budget cycle would run).
        # At usable ~= 300 (full=280, min=45) it downgrades to the tail reserve
        # so the terminal review still runs, instead of a non-monotonic refusal.
        band = _budget(1500, 1140)  # usable = 300, in [280, 325)
        self.assertLess(band.usable_seconds - _phase_downstream_reserve("REVIEWER"),
                        PHASE_MIN_USEFUL_SECONDS)
        self.assertEqual(
            review_round_reserve(0, 2, band),
            _phase_downstream_reserve("TRANSLATOR_REPAIR"),
        )

    def test_ample_budget_keeps_the_full_repair_reserve(self):
        ample = _budget(1500, 800)  # usable = 640, well above 280+45
        self.assertEqual(
            review_round_reserve(0, 2, ample),
            _phase_downstream_reserve("REVIEWER"),
        )

    def test_reserves_are_env_overridable(self):
        with patch.dict(os.environ, {"ASTRA_REVIEWER_DOWNSTREAM_RESERVE": "500"}):
            self.assertEqual(_phase_downstream_reserve("REVIEWER"), 500)
        with patch.dict(os.environ, {"ASTRA_TRANSLATOR_REPAIR_DOWNSTREAM_RESERVE": "99"}):
            self.assertEqual(_phase_downstream_reserve("TRANSLATOR_REPAIR"), 99)


class TheGuardArithmetic(unittest.TestCase):
    """Replicates the guard's decision: phase_timeout(reserve) < min_useful."""

    # The review call's configured per-call timeout is ASTRA_CLI_TIMEOUT (240)
    # unless ASTRA_REVIEWER_TIMEOUT is set; the guard clamps that to the
    # budget minus the round reserve.
    REVIEW_CONFIGURED = 240

    def _review_allowance(self, total, elapsed, revisions=0, max_rev=2):
        b = _budget(total, elapsed)
        reserve = review_round_reserve(revisions, max_rev, b)
        return b.phase_timeout(self.REVIEW_CONFIGURED, default_seconds=240, reserve_seconds=reserve)

    def test_a_fresh_cycle_is_never_starved(self):
        # Early in a 1500 s cycle there is ample room for a review round.
        self.assertGreaterEqual(self._review_allowance(1500, 200), PHASE_MIN_USEFUL_SECONDS)

    def test_a_late_cycle_refuses_a_new_round_clean(self):
        # A cycle that reaches the review loop with almost no wall left (the
        # wall-buster pattern: conjecture+translate already ate ~1300 s) is
        # refused instead of starting a repair that would overflow.
        allowance = self._review_allowance(1500, 1330)  # usable = 110
        self.assertLess(allowance, PHASE_MIN_USEFUL_SECONDS)

    def test_boundary_is_governed_by_the_reserve_not_a_hardcoded_time(self):
        # With a bigger wall the same elapsed is fine: the guard tracks the
        # budget, not a fixed clock time.
        self.assertGreaterEqual(self._review_allowance(3600, 1330), PHASE_MIN_USEFUL_SECONDS)

    def test_the_inversion_band_now_runs_a_terminal_review(self):
        # usable ~= 300 used to be refused (kept the 280 reserve -> 20s review);
        # after the downgrade fix it runs as a terminal round (tail reserve).
        self.assertGreaterEqual(self._review_allowance(1500, 1140), PHASE_MIN_USEFUL_SECONDS)

    def test_repair_guard_reserves_the_tail(self):
        # The pre-repair guard uses the TRANSLATOR_REPAIR (tail) reserve on the
        # TRANSLATOR phase; a repair only starts if the tail still fits.
        b = _budget(1500, 1300)  # usable = 140
        tail = _phase_downstream_reserve("TRANSLATOR_REPAIR")  # 160
        # 140 - 160 < 0 -> floored to 1 -> starved, repair refused clean.
        self.assertLess(
            b.phase_timeout(720, default_seconds=240, reserve_seconds=tail),
            PHASE_MIN_USEFUL_SECONDS,
        )
        b2 = _budget(1500, 1000)  # usable = 440
        self.assertGreaterEqual(
            b2.phase_timeout(720, default_seconds=240, reserve_seconds=tail),
            PHASE_MIN_USEFUL_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
