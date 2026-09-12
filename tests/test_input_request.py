"""The input request a NON_DECIDABLE cycle hands to the calling agent, and the
request fields that answer it (pure functions; the cycle wiring is covered in
tests/test_non_decidable.py)."""
from __future__ import annotations

import unittest

from core.input_request import (
    ASSUME_POLICY_TEXT,
    build_input_request,
    input_policy,
    inputs_block,
    inputs_text,
    parse_assumed_inputs,
)


class RequestFields(unittest.TestCase):
    def test_policy_defaults_to_strict_and_accepts_quoted_assume(self):
        self.assertEqual(input_policy({}), "strict")
        self.assertEqual(input_policy({"input_policy": "'Assume'"}), "assume")
        self.assertEqual(input_policy({"input_policy": "whatever"}), "strict")

    def test_inputs_render_as_text_or_name_value_lines(self):
        self.assertEqual(inputs_text({}), "")
        self.assertEqual(inputs_text({"inputs": "  U0 = 0.3\n"}), "U0 = 0.3")
        self.assertEqual(inputs_text({"inputs": {"U0": "0.3", "ansatz": {"kind": "gaussian", "w": 2}}}),
                         'U0: 0.3\nansatz: {"kind": "gaussian", "w": 2}')

    def test_block_is_empty_by_default_and_names_the_policy(self):
        self.assertEqual(inputs_block({}), "")
        block = inputs_block({"inputs": "U0 = 0.3", "input_policy": "assume"})
        self.assertTrue(block.startswith(ASSUME_POLICY_TEXT))        # policy first, never cut
        self.assertIn("FROZEN INPUTS (supplied by the user", block)
        self.assertIn("U0 = 0.3", block)
        self.assertEqual(inputs_block({"input_policy": "assume"}), ASSUME_POLICY_TEXT)
        short = inputs_block({"inputs": "v" * 3000, "input_policy": "assume"}, inputs_limit=100)
        self.assertTrue(short.startswith(ASSUME_POLICY_TEXT))
        self.assertIn("inputs shortened for this reader", short)
        self.assertLess(len(short), len(ASSUME_POLICY_TEXT) + 400)

    def test_inputs_are_capped_and_the_cap_is_reported(self):
        from core.input_request import INPUTS_MAX_CHARS, inputs_truncated

        big = {"inputs": "x" * (INPUTS_MAX_CHARS + 500)}
        text = inputs_text(big)
        self.assertTrue(inputs_truncated(big))
        self.assertIn("inputs truncated by ASTRA", text)
        self.assertLess(len(text), INPUTS_MAX_CHARS + 100)
        self.assertFalse(inputs_truncated({"inputs": "U0 = 1"}))

    def test_assumed_none_is_not_an_assumption(self):
        self.assertEqual(parse_assumed_inputs("ASSUMED: none\nAssumed: N/A\n"), [])

    def test_assumed_lines_are_parsed_once_each(self):
        stdout = ("ASSUMED: U0 = 0.30 -- typical fixed point\n"
                  "  assumed: ansatz = gaussian(w=2)\nASSUMED: U0 = 0.30 -- typical fixed point\n"
                  "CHECK a: OK\nVERDICT: PASS\n")
        self.assertEqual(parse_assumed_inputs(stdout),
                         ["U0 = 0.30 -- typical fixed point", "ansatz = gaussian(w=2)"])
        self.assertEqual(parse_assumed_inputs(""), [])


class TheQuestion(unittest.TestCase):
    def test_request_names_inputs_options_and_the_resume(self):
        req = {"intuition": "raw", "objective": "goal", "oracle": "astrum",
               "structure_request": True, "cycle_timeout_seconds": 1500, "max_mode": True,
               "axiomatic_base": "frozen"}
        ask = build_input_request(["a frozen fixed point U0", "the ansatz"], r"C:\ck\x_1.json", req)
        self.assertEqual(ask["action_required"], "ASK_USER")
        self.assertIn("a frozen fixed point U0, the ansatz", ask["question"])
        self.assertEqual(set(ask["options"]), {"provide", "assume", "extract"})
        for option in ask["options"].values():
            rerun = option["rerun"]
            self.assertEqual(rerun["intuition"], "raw")
            self.assertEqual(rerun["objective"], "goal")
            self.assertEqual(rerun["oracle"], "astrum")
            self.assertIs(rerun["structure_request"], True)
            self.assertIs(rerun["max_mode"], True)                     # a MAX cycle re-runs as MAX
            self.assertEqual(rerun["axiomatic_base"], "frozen")
            self.assertEqual(rerun["resume_checkpoint"], r"C:\ck\x_1.json")
            self.assertNotIn("cycle_timeout_seconds", rerun)          # the caller sets its wall
        self.assertEqual(ask["options"]["assume"]["rerun"]["input_policy"], "assume")
        self.assertIn("inputs", ask["options"]["provide"]["rerun"])
        self.assertIn("inputs", ask["options"]["extract"]["rerun"])
        self.assertNotIn("input_policy", ask["options"]["provide"]["rerun"])
        # Inputs already supplied survive in the re-run recipe.
        again = build_input_request(["the ansatz"], "ck", {"intuition": "raw", "inputs": "U0 = 0.3"})
        self.assertTrue(again["options"]["provide"]["rerun"]["inputs"].startswith("U0 = 0.3\n<"))
        self.assertTrue(again["options"]["extract"]["rerun"]["inputs"].startswith("U0 = 0.3\n<"))

    def test_request_without_checkpoint_or_inputs_still_asks(self):
        ask = build_input_request([], "", {"intuition": "raw"})
        self.assertIn("inputs the request does not contain", ask["question"])
        self.assertNotIn("resume_checkpoint", ask["options"]["assume"]["rerun"])
        self.assertEqual(ask["resume_checkpoint"], "")


if __name__ == "__main__":
    unittest.main()
