"""C2 classifier and stuck tracker, pinned on the reviewer's REAL rejections.

The fixtures are verbatim excerpts of the model reviewer's `reasoning` /
`revision_instructions` / `defect_labels` on the three Abellan v03 cycles the
spec cites as evidence (checkpoints 6bf68f83/pid 42724, 80a8306/pid 30268,
9a7b0bba/pid 42916). Each of those loops burned its whole revision cap on the
same defect; the rule must recognise the repetition from the second round.
"""
from __future__ import annotations

import unittest

from core.review_defects import (
    ALL_CLASSES,
    DEFECT_CLASSES,
    LABEL_CLASSES,
    OTHER,
    StuckTracker,
    alternative_strategy,
    classify_review,
    detector_enabled,
    directed_correction,
    repeated_classes,
    stuck_message,
)

ABELLAN_42724 = [
    {
        "status": "REVISE",
        "defect_labels": ["missing_assumption", "wrong_domain", "sampling_as_proof"],
        "reasoning": (
            "The exact modal and time-average algebra are sound, but the final PASS does not "
            "consume a complete universal certificate. The symbolic omega_i and omega_f are "
            "independent of q,m_i,d, so the proven positivity of (m_i+d)^2-m_i^2 is never "
            "connected to the B_q used in the modal identity. The pointwise majorant "
            "inequality, absolute-integrability/Fubini bound, both-case proof of sin(u)<u, and "
            "continuity/local-neighborhood argument for strict positivity of the H_L integral "
            "are asserted only in comments or final prose. Moreover, L>0 is not represented in "
            "those missing obligations, numerical sampling gates PASS despite being declared "
            "non-certifying, and unresolved SymPy expressions can currently be classified as "
            "mathematical FAIL rather than INCONCLUSIVE."
        ),
        "revision_instructions": (
            "Preserve the sound modal, time-average, exact majorant-integral, and Z3 legs, then "
            "apply these bounded changes: 1. Unify the physical definitions by imposing "
            "omega_i^2=q^2+m_i^2 and omega_f^2=q^2+(m_i+d)^2, and explicitly certify "
            "omega_f^2-omega_i^2=2m_i d+d^2 before using the positivity result for the modal B_q."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["missing_assumption", "wrong_domain", "hardcoded_pass"],
        "reasoning": (
            "The analytic chain has two decisive domain/linkage defects. L is declared only "
            "real, so L>0 is absent and HL_uarg_positive and HL_continuous cannot be certified. "
            "More seriously, Bq uses independent positive symbols wi and wf, while Bq_positive "
            "checks the unrelated numerator num; omega_diff_identity never establishes "
            "wf^2-wi^2=num for those symbols. For example, wi=2 and wf=1 satisfies their "
            "declared assumptions but makes Bq<0. Claim 4 is also not genuinely certified: "
            "HL_continuous is assigned True from denominator positivity, and "
            "strict_positive_integral merely combines labels without constructing or "
            "verifying the required positive neighborhood."
        ),
        "revision_instructions": (
            "Declare L positive. Use one q-dependent definition throughout: wi=sqrt(q^2+mi^2), "
            "wf=sqrt(q^2+(mi+d)^2), and Bq=num/(4*wi*wf^2), or add and consume exact "
            "substitution certificates linking every abstract occurrence to these expressions."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["missing_assumption"],
        "reasoning": (
            "The analytic strategy is sound, but the current wiring cannot certify it. "
            "`Bq_positive` checks the manifest numerator `num` while the actual abstract `Bq` "
            "contains `wf**2-wi**2`; with independent positive `wi,wf`, `Bq` need not be "
            "positive. Consequently `(2*Bq).is_positive` in `fubini_integrand_nonneg` is "
            "undecidable and forces the final verdict to INCONCLUSIVE. In addition, "
            "`HL_continuous` checks only denominator positivity, not continuity of the actual "
            "`HL_expr`, so the epsilon-neighborhood certificate is not genuinely falsifiable."
        ),
        "revision_instructions": (
            "Preserve the modal, trigonometric, Z3, and non-gating numerical legs. Patch "
            "Claim 1/2 to use the bound q-dependent expression `Bq_q` and `wf_q` for every "
            "positivity and Fubini check."
        ),
    },
]

ABELLAN_30268 = [
    {
        "status": "REVISE",
        "defect_labels": ["sampling_as_proof", "wrong_domain", "missing_assumption",
                          "self_comparison", "wrong_tolerance"],
        "reasoning": (
            "The overall certificate strategy is viable, but several decisive gates do not "
            "establish their advertised universal obligations. continuity_exact checks one "
            "numerical parameter substitution rather than all positive m_i,d,t. "
            "majorant_integrable verifies an algebraic identity and the integral but never "
            "proves |g|<=2B<=M. The construction omits t>0, k in N, the two exact min cases, "
            "delta<=pi/(6t), both endpoint/image implications, the trigonometric interval "
            "inequality, and the signs needed to infer monotonicity of B. integral_comparison "
            "assumes abstract positive symbols without encoding q_+>q_-; substituting q_-=0 "
            "does not prove negativity for the original expression."
        ),
        "revision_instructions": (
            "Preserve the sound modal residual, sequence-limit, exact-integral, and auxiliary "
            "numerical legs. Patch continuity_exact to query the two full parameterized "
            "expressions with m_i,d,t positive and q real, without substitutions."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["self_comparison", "missing_assumption"],
        "reasoning": (
            "The overall constructive strategy is sound, exact, and independent of temporal "
            "sampling, but several decisive gates do not establish what their names claim. "
            "continuity_exact evaluates the same modal expression twice and never checks the "
            "closed form g_closed = -2*B*sin(wf*t)^2. phase_bound checks a derivative identity, "
            "parity, and an endpoint value but never proves cos(z)^2 >= 3/4 on |z| <= pi/6; "
            "moreover P6 is an unconstrained positive real rather than pi/6. interval_ordered "
            "uses disconnected placeholder variables and proves only radicand ordering, not "
            "q_plus > q_minus > 0 for the defined square roots. Finally, integral_comparison "
            "assumes the two decisive integral bounds as solver premises, so that gate is "
            "self-confirming unless those premises are explicitly instantiated."
        ),
        "revision_instructions": (
            "Define g_closed = -2*B*sin(wf*t)^2 and query continuous_domain separately for "
            "g_closed and the unsimplified modal expression."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["self_comparison", "unreachable_failure", "missing_assumption"],
        "reasoning": (
            "Most algebraic ingredients are sound, but the decisive strict-integral gate is "
            "self-confirming. It assumes `IonI <= gmaxI*measI` and `Irest <= 0`, which are the "
            "analytic conclusions that must be justified from the actual integrand; "
            "consequently `ic` cannot expose a failed comparison. Several prerequisite links "
            "are also only stated in comments: `wi_ge_mi` does not prove `wi >= mi`, the floor "
            "lemma is not algebraically connected to the defined `omega_*`, and the phase, "
            "monotonicity, and interval gates never jointly derive the actual pointwise bound "
            "on I. Thus PASS does not yet constitute an executable exact certificate."
        ),
        "revision_instructions": (
            "Replace `wi_ge_mi` with an exact proof of `sqrt(q**2+mi**2) >= mi`, then "
            "explicitly certify `Abs(g_closed) <= M` from that result."
        ),
    },
]

ABELLAN_42916 = [
    {
        "status": "REVISE",
        "defect_labels": ["sampling_as_proof", "wrong_domain", "wrong_tolerance",
                          "missing_assumption", "unknown_as_pass"],
        "reasoning": (
            "The exact modal identity and independent ODE leg are sound, but the script is not "
            "oracle-ready. leg_limits deterministically raises TypeError because deltaF returns "
            "a tuple. More importantly, PASS promotes tests at one mass pair and finitely many "
            "t and L values into universal claims for all admissible masses, t>0, and L>0. The "
            "L-to-infinity claim is represented only by L=5000 with an arbitrary tolerance. The "
            "Hartree sign is likewise sampled at one positive lambda rather than derived under "
            "lambda>0. Finally, leg_z3 accepts unknown as proof because it checks r != sat "
            "instead of r == unsat."
        ),
        "revision_instructions": (
            "Fix leg_limits by unpacking deltaF; make universal PASS depend on exact checks of "
            "mf>mi>0, B_q>0, the modal identity, and the strict-integral argument; retain "
            "finite sampling only as adversarial evidence."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["self_comparison", "hardcoded_pass"],
        "reasoning": (
            "The symbolic modal identity, ODE initial conditions, universal Z3 proof of B_q>0, "
            "and conditional Hartree-sign propagation are sound. Claim 2 is not executable as "
            "claimed: avg_deltaF is never exercised or derived, cert_sinx_over_x_lt_1 checks "
            "only a derivative identity, and both universal-average and limit checks merely "
            "reuse I_positive. The stated remainder bound, B_q=O(|q|^-3), and analytic tail "
            "bounds are asserted only in comments; scipy quad error estimates are not certified "
            "bounds."
        ),
        "revision_instructions": (
            "Patch Claim 1 to certify that for every t>0 the set of q with "
            "sin^2(omega_f(q)t)>0 has positive measure."
        ),
    },
    {
        "status": "REVISE",
        "defect_labels": ["self_comparison"],
        "reasoning": (
            "The modal identity, ODE cross-check, parameter sign, asymptotic decay, and tail "
            "constants are sound legs. However, the universal strict-sign claims are accepted "
            "through weaker proxy checks: sin_zeros != Reals does not prove that the zero set "
            "has measure zero, and differentiating x-sin(x) without proving positivity does "
            "not establish sin(x)/x<1 for every x>0. The Hartree checks also introduce DeltaF "
            "as a symbol declared negative instead of consuming the verified Claim 1 and "
            "Claim 2 results."
        ),
        "revision_instructions": (
            "Replace claim1_positive_measure_support with an exact certificate that the zeros "
            "are precisely pi times the integers."
        ),
    },
]

REAL_LOOPS = {"42724": ABELLAN_42724, "30268": ABELLAN_30268, "42916": ABELLAN_42916}


class ClassifierOnRealRejections(unittest.TestCase):
    def test_every_real_rejection_is_recognised(self):
        for pid, rounds in REAL_LOOPS.items():
            for index, review in enumerate(rounds):
                with self.subTest(pid=pid, round=index):
                    found = classify_review(review)
                    self.assertTrue(found["classes"], found)
                    self.assertNotEqual(found["primary"], OTHER)
                    for cls in found["classes"]:
                        self.assertIn(cls, ALL_CLASSES)
                        self.assertTrue(found["evidence"][cls])

    def test_the_two_stuck_loops_repeat_from_the_second_round(self):
        """The spec's evidence: 42724 and 30268 burned the cap on one defect."""
        for pid in ("42724", "30268"):
            rounds = REAL_LOOPS[pid]
            previous = classify_review(rounds[0])["classes"]
            for index in range(1, len(rounds)):
                current = classify_review(rounds[index])["classes"]
                with self.subTest(pid=pid, round=index):
                    self.assertTrue(repeated_classes(previous, current),
                                    (previous, current))
                previous = current

    def test_a_loop_that_moves_on_is_not_called_stuck(self):
        """42916's defects change every round (sampling -> links in comments ->
        proxy checks): the rule must not declare a repeat. This guards against
        the over-firing an adversarial audit caught in the first version."""
        rounds = ABELLAN_42916
        previous = classify_review(rounds[0])["classes"]
        for index in range(1, len(rounds)):
            current = classify_review(rounds[index])["classes"]
            with self.subTest(round=index):
                self.assertEqual(repeated_classes(previous, current), [], (previous, current))
            previous = current

    def test_innocuous_sentences_classify_nothing(self):
        probes = [
            {"reasoning": "Off-by-one in the loop bound.",
             "revision_instructions": "Preserve the continuity and domain legs.",
             "defect_labels": []},
            {"reasoning": "The overall constructive strategy is sound, exact, and "
                          "independent of temporal sampling.", "defect_labels": []},
            {"reasoning": "The script samples 200 random points; fine as a diagnostic.",
             "defect_labels": []},
            {"reasoning": "Continuity is established by an exact domain query; the "
                          "tolerance is the only problem.", "defect_labels": ["wrong_tolerance"]},
            {"reasoning": "Tighten the exact witness.",
             "defect_labels": ["missing_assumption", "self_comparison"]},
        ]
        expected = [[], [], [], ["wrong_tolerance"], []]
        for probe, want in zip(probes, expected):
            with self.subTest(text=probe["reasoning"][:40]):
                self.assertEqual(classify_review(probe)["classes"], want)

    def test_resolution_prose_does_not_resurrect_a_fixed_class(self):
        review = {
            "reasoning": (
                "The independent positive symbols issue is now resolved and B_q is bound "
                "to q; however the Fubini bound is asserted only in comments."
            ),
            "defect_labels": [],
        }
        self.assertEqual(classify_review(review)["classes"], ["link_in_comment"])
        praise_then_defect = {
            "reasoning": "The modal legs are sound, but `wi_ge_mi` does not prove `wi >= mi`.",
            "defect_labels": [],
        }
        self.assertEqual(classify_review(praise_then_defect)["classes"], ["link_in_comment"])
        # "fixed" as an adjective, or the fix as a subject, is a live defect, not a
        # resolution; and a scrubbed clause must not fuse its neighbours.
        for text, want in (
            ("Sampling at fixed t = 1 gates PASS for every t.", ["sampling_as_proof"]),
            ("The fix removed the only executed check, so PASS is asserted only in comments.",
             ["link_in_comment"]),
            ("Continuity is established by an exact domain query, but the previous objection "
             "is now resolved. The tolerance is not derived from the problem scale.", []),
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(
                    classify_review({"reasoning": text, "defect_labels": []})["classes"], want
                )

    def test_repeat_is_anchored_on_a_primary_class(self):
        # Incidental overlap on a secondary class is not a repeat ...
        self.assertEqual(repeated_classes(["assumed_bound", "missing_domain"],
                                          ["link_in_comment", "missing_domain"]), [])
        # ... unless the overlapping class is what one round is mainly about.
        self.assertEqual(repeated_classes(["undecidable_positivity", "missing_domain"],
                                          ["missing_domain"]), ["missing_domain"])

    def test_signatures_named_by_the_spec(self):
        # 42724 round 1: "independent positive symbols wi and wf", "L is declared only real"
        found = classify_review(ABELLAN_42724[1])["classes"]
        self.assertIn("undecidable_positivity", found)
        self.assertIn("missing_domain", found)
        self.assertIn("proxy_continuity", found)
        # 42724 round 0: "asserted only in comments or final prose"
        self.assertIn("link_in_comment", classify_review(ABELLAN_42724[0])["classes"])
        # 30268 round 2: self-confirming gate assuming the conclusion
        found = classify_review(ABELLAN_30268[2])["classes"]
        self.assertEqual(found[0], "assumed_bound")     # highest priority class
        self.assertIn("link_in_comment", found)
        # 42916 round 0: sampling promoted to a universal claim; unknown accepted as proof
        found = classify_review(ABELLAN_42916[0])["classes"]
        self.assertIn("sampling_as_proof", found)
        self.assertIn("unknown_as_pass", found)

    def test_approved_or_generic_reviews_are_other(self):
        approved = {"status": "APPROVED", "reasoning": "Exact witness ready.", "defect_labels": []}
        self.assertEqual(classify_review(approved), {"classes": [], "primary": OTHER, "evidence": {}})
        generic = {"status": "REVISE", "reasoning": "Tighten the exact witness.",
                   "revision_instructions": "Preserve the witness and clarify it.",
                   "defect_labels": ["missing_assumption"]}
        self.assertEqual(classify_review(generic)["primary"], OTHER)

    def test_other_never_repeats(self):
        self.assertEqual(repeated_classes([], []), [])
        self.assertEqual(repeated_classes([OTHER], [OTHER]), [])
        self.assertEqual(repeated_classes(["missing_domain"], ["sampling_as_proof"]), [])
        self.assertEqual(repeated_classes(["missing_domain", "assumed_bound"],
                                          ["assumed_bound"]), ["assumed_bound"])


class TextsAndMessages(unittest.TestCase):
    def test_every_class_has_a_directed_correction_and_an_alternative(self):
        for cls in DEFECT_CLASSES + LABEL_CLASSES:
            with self.subTest(cls=cls):
                text = directed_correction([cls])
                self.assertIn("DIRECTED CORRECTION", text)
                self.assertIn(cls, text)
                alt = alternative_strategy([cls])
                self.assertIn("STRATEGY SWITCH", alt)
                self.assertIn(cls, alt)
        self.assertEqual(directed_correction([]), "")
        self.assertEqual(directed_correction([OTHER]), "")

    def test_stuck_message_names_where_the_single_switch_went(self):
        msg = stuck_message(["missing_domain"], [2, 3], 2, 3, "",
                            actions=["directed_patch", "strategy_switch", "directed_patch", "stop"],
                            switched_for=["undecidable_positivity"])
        self.assertIn("with the single strategy switch already spent on undecidable_positivity", msg)
        self.assertNotIn("and a strategy switch", msg)

    def test_manifest_stamps_the_detector_like_the_strict_contract(self):
        from core.architecture_contract import production_manifest

        self.assertIs(production_manifest({})["controls"]["review_stuck_detector"], True)
        self.assertIs(production_manifest({"ASTRA_REVIEW_STUCK_DETECTOR": "0"})["controls"]
                      ["review_stuck_detector"], False)

    def test_stuck_message_never_reads_as_a_deadline(self):
        # astra_tool._fail classifies "time budget" / "timeout tras" as PARTIAL.
        msg = stuck_message(["undecidable_positivity"], [0, 1, 2], 2, 2, "reason",
                            actions=["directed_patch", "strategy_switch", "stop"])
        self.assertTrue(msg.startswith("Review stuck on defect class undecidable_positivity"))
        self.assertIn("after a directed correction and a strategy switch", msg)
        self.assertIn("2 model revision(s) used of 2", msg)
        self.assertNotIn("time budget", msg.lower())
        self.assertNotIn("timeout tras", msg.lower())
        # Cap reached before any switch (cap 1): the message must not invent one.
        short = stuck_message(["missing_domain"], [0, 1], 1, 1, "", actions=["directed_patch"])
        self.assertIn("after a directed correction;", short)
        self.assertNotIn("strategy switch", short)


class Tracker(unittest.TestCase):
    def test_same_class_thrice_escalates_directed_switch_stop(self):
        trace = []
        tracker = StuckTracker(trace)
        actions = [tracker.observe(ABELLAN_42724[i], i, i)["action"] for i in range(3)]
        self.assertEqual(actions, ["directed_patch", "strategy_switch", "stop"])
        self.assertTrue(tracker.switched)
        diagnosis = tracker.diagnosis()
        self.assertEqual(diagnosis["rejections"], 3)
        self.assertEqual(diagnosis["actions"], actions)
        self.assertTrue(diagnosis["stuck_classes"])
        self.assertIs(tracker.trace, trace)          # shared list for provenance

    def test_second_class_after_the_switch_stops_and_remembers_the_switch(self):
        a = {"reasoning": "Bq uses independent positive symbols wi and wf.", "defect_labels": []}
        b = {"reasoning": "PASS promotes tests at one mass pair into universal claims.",
             "defect_labels": []}
        tracker = StuckTracker()
        actions = [tracker.observe(r, i, i)["action"] for i, r in enumerate((a, a, b, b))]
        self.assertEqual(actions, ["directed_patch", "strategy_switch", "directed_patch", "stop"])
        self.assertEqual(tracker.diagnosis()["switched_for"], ["undecidable_positivity"])
        self.assertEqual(tracker.diagnosis()["stuck_classes"], ["sampling_as_proof"])

    def test_a_new_loop_does_not_compare_against_an_earlier_loop(self):
        """astra_tool re-enters the review loop after a post-oracle retry with a
        fresh tracker on the SAME shared trace; the earlier loop's last
        rejection (followed by an APPROVED) must not seed a false repeat."""
        trace = []
        first = StuckTracker(trace)
        first.observe(ABELLAN_42724[0], 0, 0)            # then APPROVED, oracle, retry
        second = StuckTracker(trace)
        record = second.observe(ABELLAN_42724[1], 0, 0)  # same class, new script
        self.assertEqual(record["action"], "directed_patch")
        self.assertEqual(record["repeated"], [])
        self.assertEqual(len(trace), 2)                  # provenance keeps both
        self.assertEqual(second.diagnosis()["rejections"], 1)
        self.assertEqual(second.diagnosis()["earlier_rejections"], 1)
        again = second.observe(ABELLAN_42724[2], 1, 1)
        self.assertEqual(again["action"], "strategy_switch")

    def test_a_new_class_is_directed_again_not_switched(self):
        tracker = StuckTracker()
        first = tracker.observe({"reasoning": "L is declared only real, so L>0 is absent.",
                                 "defect_labels": []}, 0, 0)
        second = tracker.observe({"reasoning": "PASS promotes finitely many samples into a "
                                               "universal claim.", "defect_labels": []}, 1, 1)
        self.assertEqual(first["action"], "directed_patch")
        self.assertEqual(second["action"], "directed_patch")
        self.assertEqual(second["repeated"], [])
        self.assertFalse(tracker.switched)

    def test_cap_spent_stops_on_a_repeat_and_never_invents_a_switch(self):
        tracker = StuckTracker()
        tracker.observe(ABELLAN_42724[0], 0, 0, can_revise=True)
        last = tracker.observe(ABELLAN_42724[1], 1, 1, can_revise=False)
        self.assertEqual(last["action"], "stop")
        self.assertFalse(tracker.switched)
        self.assertNotIn("strategy_switch", tracker.diagnosis()["actions"])
        fresh = StuckTracker()
        fresh.observe({"reasoning": "L>0 is absent.", "defect_labels": []}, 0, 0)
        capped = fresh.observe({"reasoning": "PASS promotes finitely many samples.",
                                "defect_labels": []}, 1, 1, can_revise=False)
        self.assertEqual(capped["action"], "cap_reached")

    def test_unrecognised_rejections_stay_blind(self):
        tracker = StuckTracker()
        record = tracker.observe({"reasoning": "Tighten the witness.", "defect_labels": []}, 0, 0)
        again = tracker.observe({"reasoning": "Tighten the witness.", "defect_labels": []}, 1, 1)
        self.assertEqual(record["action"], "blind")
        self.assertEqual(again["action"], "blind")       # other never repeats

    def test_detector_env_switch(self):
        self.assertTrue(detector_enabled({}))
        self.assertTrue(detector_enabled({"ASTRA_REVIEW_STUCK_DETECTOR": "'1'"}))
        for raw in ("0", "off", "false", "no", " OFF "):
            self.assertFalse(detector_enabled({"ASTRA_REVIEW_STUCK_DETECTOR": raw}), raw)


if __name__ == "__main__":
    unittest.main()
