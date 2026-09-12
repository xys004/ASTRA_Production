"""MAX mode: one deliberate cycle on each CLI's top model, non-persistent.

MAX pins every CLI to its top model at max reasoning with no fallback, raises
per-call timeouts so the slow top models are not killed at their ceiling (the
heavy-model-timeout blocker), and runs fresh (no cache). It is triggered per
request and never persisted -- astra_tool runs one action per process, so the
env overrides die with the cycle. MAX deliberately does NOT set the cycle wall
(that stays the caller's deadline), so it can never desync the budget guard
from the watchdog.
"""
import os
import unittest
from unittest.mock import patch

from astra_tool import (
    apply_max_mode,
    restore_max_mode,
    _max_mode_requested,
    _MAX_MODE_ENV,
)


class Trigger(unittest.TestCase):
    def test_absent_or_falsey_is_not_requested(self):
        for req in ({}, {"max_mode": False}, {"max_mode": "0"}, {"max_mode": "no"}, {"max_mode": ""}):
            with self.subTest(req=req):
                self.assertFalse(_max_mode_requested(req))

    def test_truthy_forms_are_requested(self):
        for v in (True, "1", "true", "TRUE", "on", "yes"):
            with self.subTest(v=v):
                self.assertTrue(_max_mode_requested({"max_mode": v}))


class Apply(unittest.TestCase):
    def test_not_requested_changes_nothing_and_returns_none(self):
        with patch.dict(os.environ, {}, clear=False):
            before = dict(os.environ)
            self.assertIsNone(apply_max_mode({"intuition": "x"}))
            self.assertEqual(dict(os.environ), before)

    def test_requested_pins_top_models_effort_and_timeouts(self):
        with patch.dict(os.environ, {}, clear=False):
            self.assertTrue(apply_max_mode({"max_mode": True}))
            self.assertEqual(os.environ["ASTRA_CODEX_MODELS"], "gpt-5.6-sol")
            self.assertEqual(os.environ["ASTRA_CLAUDE_MODELS"], "claude-opus-4-8")
            self.assertEqual(os.environ["ASTRA_TRANSLATOR_MODELS"], "claude-opus-4-8")
            self.assertEqual(os.environ["ASTRA_AGY_MODELS"], "gemini-3.1-pro-high")
            self.assertEqual(os.environ["ASTRA_MUSE_MODELS"], "muse-spark-1.3")
            self.assertEqual(os.environ["ASTRA_CODEX_REASONING"], "xhigh")
            self.assertEqual(os.environ["ASTRA_MUSE_REASONING"], "ultra")
            # per-call ceilings raised well above the defaults (codex 240)
            self.assertGreaterEqual(int(os.environ["ASTRA_CLI_TIMEOUT"]), 900)
            self.assertGreaterEqual(int(os.environ["ASTRA_TRANSLATOR_TIMEOUT"]), 1800)
            # fresh run, no cache
            self.assertEqual(os.environ["ASTRA_CYCLE_CACHE"], "0")

    def test_models_have_no_fallback_rung(self):
        # A single id per ladder -> the top model, no degrade to sonnet/gpt-5.5.
        with patch.dict(os.environ, {}, clear=False):
            apply_max_mode({"max_mode": True})
            for key in ("ASTRA_CODEX_MODELS", "ASTRA_CLAUDE_MODELS",
                        "ASTRA_AGY_MODELS", "ASTRA_MUSE_MODELS"):
                self.assertNotIn(",", os.environ[key], f"{key} must be top-only")

    def test_does_not_set_the_cycle_wall(self):
        # The wall is the caller's deadline; MAX must not touch it, or the
        # budget guard would desync from the interactive/watchdog kill.
        req = {"max_mode": True}
        with patch.dict(os.environ, {}, clear=False):
            apply_max_mode(req)
        self.assertNotIn("cycle_timeout_seconds", req)

    def test_overrides_the_normal_ladders(self):
        # Even if a run had cheaper/fallback ladders configured, MAX overrides.
        with patch.dict(os.environ, {"ASTRA_CODEX_MODELS": "gpt-5.5",
                                     "ASTRA_CLAUDE_MODELS": "sonnet"}, clear=False):
            apply_max_mode({"max_mode": True})
            self.assertEqual(os.environ["ASTRA_CODEX_MODELS"], "gpt-5.6-sol")
            self.assertEqual(os.environ["ASTRA_CLAUDE_MODELS"], "claude-opus-4-8")

    def test_every_declared_key_is_applied(self):
        with patch.dict(os.environ, {}, clear=False):
            apply_max_mode({"max_mode": True})
            for key, value in _MAX_MODE_ENV.items():
                self.assertEqual(os.environ[key], value)


class RestoreRoundTrip(unittest.TestCase):
    """apply/restore leaves os.environ exactly as it was -- so MAX can never
    leak into a later cycle even if this runs in-process (a campaign step)."""

    def test_restore_reverts_prior_values_and_removes_new_keys(self):
        with patch.dict(os.environ, {}, clear=False):
            # A key that pre-exists (must be restored to its old value) and one
            # that does not (must be removed on restore).
            os.environ["ASTRA_CODEX_MODELS"] = "gpt-5.5"
            os.environ.pop("ASTRA_MUSE_MODELS", None)
            before = dict(os.environ)
            snapshot = apply_max_mode({"max_mode": True})
            self.assertEqual(os.environ["ASTRA_CODEX_MODELS"], "gpt-5.6-sol")
            self.assertEqual(os.environ["ASTRA_MUSE_MODELS"], "muse-spark-1.3")
            restore_max_mode(snapshot)
            self.assertEqual(os.environ["ASTRA_CODEX_MODELS"], "gpt-5.5")
            self.assertNotIn("ASTRA_MUSE_MODELS", os.environ)
            self.assertEqual(dict(os.environ), before)

    def test_restore_none_is_a_noop(self):
        with patch.dict(os.environ, {}, clear=False):
            before = dict(os.environ)
            restore_max_mode(None)
            self.assertEqual(dict(os.environ), before)


if __name__ == "__main__":
    unittest.main()
