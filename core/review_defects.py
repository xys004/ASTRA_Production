"""C2 of the cycle-robustness spec: classify reviewer rejections, detect a
stuck review loop, and turn a blind revision into a directed one.

Pure standard library, no model calls. See
docs/architecture/CYCLE_ROBUSTNESS_SPEC.md (C2, and Nelson's decision 4:
replace a blind revision by a directed one without raising the revision cap).

Taxonomy
--------
The six classes below are C0's wiring defects (the ones the independent
reviewer rejects every time) plus ``sampling_as_proof``, which the reviewer
already labels and which recurs as often as the five. A few of the reviewer's
other normalized labels are carried through as their own classes when they
name a defect on their own (``engine_mismatch``, ``unknown_as_pass``, ...).

Why prose and not only ``defect_labels``: on the two Abellan v03 cycles
(checkpoints 6bf68f83/pid 42724 and 80a8306/pid 30268) the reviewer labelled
every round ``missing_assumption`` while its reasoning named the actual,
repeating defect ("asserted only in comments", "independent positive symbols
wi, wf", "self-confirming", "denominator positivity", "L>0 is absent"). Labels
are used only where they are specific; ``missing_assumption`` and
``self_comparison`` are deliberately not classes because the reviewer stamps
them on nearly every rejection for unrelated reasons.

Only the reviewer's ``reasoning`` is scanned. ``revision_instructions`` are
prescriptive ("Preserve the continuity and domain legs ...") and would make
every round look like every other. Every pattern needs its negative context in
the same sentence: a bare "continuity", "domain" or "sampling" is a topic, not
a defect.

Repeat rule
-----------
A rejection's classes are ordered by priority; ``classes[0]`` is its primary
defect. A class counts as repeated only when it appears in two consecutive
rejections AND is the primary of at least one of them: the loop is stuck on
what the reviewer mainly complains about, not on an incidental remark.
``other`` (nothing recognised) never repeats.

Decision rule (``StuckTracker.observe``)
----------------------------------------
* first rejection, or new classes: ``directed_patch`` -- the next revision
  carries a correction aimed at the classes found (this replaces the blind
  "re-pass the reasoning" round; it is not an extra round);
* a repeated class: ``strategy_switch`` -- ONE full re-translation with an
  alternative certification route, still within the revision cap;
* a repeat after the switch was spent: ``stop`` -- clean stop with a diagnosis
  naming the class, instead of an opaque tool_error and instead of burning
  what remains of the cap on repetitions.
When the revision cap is already spent (``can_revise=False``) a repeated
class is ``stop`` (diagnosis, no invented switch) and anything else is
``cap_reached`` (the legacy message).
"""
from __future__ import annotations

import os
import re

# Order = priority when a rejection matches several classes.
DEFECT_CLASSES = (
    "assumed_bound",
    "undecidable_positivity",
    "link_in_comment",
    "proxy_continuity",
    "missing_domain",
    "sampling_as_proof",
)
# Reviewer labels specific enough to name the defect on their own.
LABEL_CLASSES = (
    "unreachable_failure",
    "unknown_as_pass",
    "swallowed_exception",
    "engine_mismatch",
    "missing_dependency",
    "wrong_tolerance",
    "wrong_units",
    "unsimplified_symbolic_zero",
)
OTHER = "other"
ALL_CLASSES = DEFECT_CLASSES + LABEL_CLASSES

# Specific reviewer labels that map onto one of the six C0 classes.
_LABEL_TO_CLASS = {
    "wrong_domain": "missing_domain",
    "sampling_as_proof": "sampling_as_proof",
    "hardcoded_pass": "link_in_comment",
}

_PATTERNS = {
    "link_in_comment": (
        # "asserted only in comments or final prose", "exists only as a docstring"
        r"\b(asserted|stated|established|claimed|proved|proven|justified|represented|exists?)"
        r"\s+only\s+(in|by|through|as)\s+(the\s+|an?\s+)?(comments?|prose|docstrings?|names?|labels?)\b",
        # "only stated in comments"
        r"\bonly\s+(stated|asserted|claimed|established)\s+(in|by)\s+(the\s+)?(comments?|prose|docstrings?)\b",
        r"\b(is|are)\s+assigned\s+True\b",
        r"\bmerely\s+(combines?|reuses?|restates?)\b",
        r"\b(alias(es)?|reuse[sd]?)\s+[A-Za-z_]*positive\b",
        r"\bnever\s+(exercised|consumed)\b",
        r"\bnot\s+(genuinely\s+)?(executable|exercised|consumed)\b",
        # "`wi_ge_mi` does not prove `wi >= mi`": a named link that proves nothing
        r"`[A-Za-z_]\w*`\s+does\s+not\s+prove\b",
        r"\bcannot\s+expose\b",
        r"\bnot\s+(yet\s+)?(constitute\s+)?(an?\s+)?executable\s+(exact\s+)?certificate\b",
    ),
    "undecidable_positivity": (
        r"\bindependent\s+(positive\s+)?symbols?\b",
        r"\bundecidable\b",
        r"\bcannot\s+(be\s+)?decide",
        r"\bnot\s+decid(ed|able)\b",
        r"\bis_positive\b",
        r"\b(never|not)\s+connected\b",
        r"\bunrelated\s+numerator\b",
        r"\b(detached|disconnected)\s+(copy|placeholder|variables?)\b",
        r"\bneed\s+not\s+be\s+positive\b",
        r"\bindependent\s+of\s+q\b",
        r"\bpositivity\s+of\b[^.]{0,120}\b(never|not)\b",
    ),
    "assumed_bound": (
        r"\bself[- ]confirming\b",
        r"\bcircular\b",
        r"\bas\s+(solver\s+)?premises\b",
        r"\btaken\s+as\s+given\b",
        r"\bassume\s*\(",
        r"\bconclusions?\s+that\s+must\s+be\s+justified\b",
        # "assumes `IonI <= gmaxI*measI`", "assumes the two decisive integral bounds"
        r"\bassumes?\s+`[^`]+`",
        r"\bassumes?\s+(the\s+|its\s+|both\s+|two\s+)?(decisive\s+|integral\s+|abstract\s+)*"
        r"(bounds?|inequalit(y|ies)|conclusions?|premises?)\b",
        # "never proves |g|<=2B<=M": a bound the verdict rests on is not proven
        r"\bnever\s+proves?\s+\|",
    ),
    "proxy_continuity": (
        r"\bcontinuity\b[^.;]{0,100}\b(proxy|denominator|assigned|asserted|never|not|only)\b",
        r"\b(proxy|denominator)\b[^.;]{0,100}\bcontinuity\b",
        r"\bdenominator[- ]?(positivity|only)\b",
        r"\b(weaker\s+)?proxy\s+checks?\b",
        r"\bby\s+proxy\b",
        r"\b(without|not|never|merely)\b[^.;]{0,120}\bneighbou?rhood\b",
        r"\bneighbou?rhood\b[^.;]{0,120}\b(without|not|never|asserted)\b",
    ),
    "missing_domain": (
        r"\bdeclared\s+only\s+real\b",
        r"\bunconstrained\s+positive\s+real\b",
        # an inequality next to absent/omits/missing: "omits t>0", "L>0 is absent"
        r"\b[A-Za-z_]+\s*>\s*0\b[^.;]{0,60}\b(absent|missing|omitted|not\s+represented)\b",
        r"\b(absent|missing|omits?|omitted|without)\b[^.;]{0,60}\b[A-Za-z_]+\s*>\s*0\b",
        r"\bwithout\s+encoding\s+[A-Za-z_+\-]+\s*>",
        r"\bdomain\b[^.;]{0,60}\b(absent|missing|incomplete|omitted|not\s+decided)\b",
        r"\b(incomplete|missing|absent)\s+domain\b",
        # "proves only radicand ordering, not q_plus > q_minus > 0"
        r"\bnot\s+[A-Za-z_]+\s*>\s*[A-Za-z_]+\s*>\s*0\b",
    ),
    "sampling_as_proof": (
        r"\bsampl(es|ing)\b[^.,;]{0,40}\b(gates?\s+PASS|as\s+proof|into\s+universal|universal\s+claims?)\b",
        r"\bpromotes\s+tests\b",
        r"\bfinitely\s+many\b",
        r"\bone\s+(numerical\s+)?(parameter\s+)?(substitution|mass\s+pair|positive\s+lambda)\b",
        r"\bsampled\s+at\s+one\b",
    ),
}
_COMPILED = {
    cls: tuple(re.compile(p, re.IGNORECASE) for p in pats)
    for cls, pats in _PATTERNS.items()
}

DIRECTED_CORRECTIONS = {
    "assumed_bound": (
        "Remove every assumed conclusion: no `assume(X <= Y)`, no bound taken as a "
        "solver premise, no self-confirming gate. Derive each bound the verdict "
        "depends on from the actual expressions in code (exact inequality, unsat "
        "negation, or an explicit computed comparison) or let the verdict fail."
    ),
    "undecidable_positivity": (
        "Make signs decidable: write the relations between symbols into the symbols "
        "themselves (m_f = m_i + d with d > 0; omega = sqrt(q**2 + m**2)) instead of "
        "declaring related quantities as independent positive symbols, and certify "
        "each sign on the SAME expression the integrand or verdict uses, never on a "
        "detached numerator or manifest copy."
    ),
    "link_in_comment": (
        "Turn every logical link into an EXECUTED check whose boolean feeds the final "
        "verdict. A fact stated only in a comment, docstring, label, or by reusing an "
        "earlier boolean proves nothing; if a step cannot be checked executably, "
        "report it as an unresolved obligation and let the verdict fail."
    ),
    "proxy_continuity": (
        "Certify continuity and strict positivity on the actual expression: query the "
        "continuous domain of the real integrand (not only denominator > 0) and exhibit "
        "an explicit point where it is strictly positive, with the neighbourhood argument "
        "computed in code, not asserted."
    ),
    "missing_domain": (
        "Encode the full domain in the symbols and check it: positivity of every "
        "parameter the claim needs (L > 0, t > 0, m_i > 0, d > 0), the ordering of "
        "interval endpoints (q_+ > q_- > 0), and the case split of every min/max or "
        "piecewise definition, each as its own executed check."
    ),
    "sampling_as_proof": (
        "Numerical samples corroborate, they never discharge a universal claim: supply "
        "an exact or formal argument (symbolic identity, Z3 unsat of the negation, "
        "exhibited point plus continuity), or explicitly narrow the validated scope "
        "and keep the sampling as a non-gating diagnostic leg."
    ),
    "unreachable_failure": (
        "Make the FAIL branch reachable: bind VERDICT to computed booleans so a wrong "
        "sign, a nonzero residual, or a non-empty zero set flips it."
    ),
    "unknown_as_pass": (
        "Treat unknown, indeterminate, or None results from the solver as OPERATIONAL "
        "failures (exit nonzero), never as PASS; check `== unsat`, not `!= sat`."
    ),
    "swallowed_exception": (
        "Let exceptions propagate or exit nonzero; never map an exception to PASS or "
        "FAIL."
    ),
    "engine_mismatch": (
        "Use the engine the code needs: put the matching `# ASTRA_ENGINE:` marker on "
        "the first line or rewrite the check for the engine that runs it."
    ),
    "missing_dependency": (
        "Use only libraries available to the selected engine, or route the script to "
        "the engine that has them; a missing import must exit nonzero, not pass."
    ),
    "wrong_tolerance": (
        "Derive every tolerance from the problem scale and bound the numerical error; "
        "a decisive check must be exact or carry a certified error bound."
    ),
    "wrong_units": (
        "Check units explicitly (dimensional analysis or `pint`) on every quantity the "
        "verdict compares."
    ),
    "unsimplified_symbolic_zero": (
        "Canonicalize before comparing to zero (simplify, expand, trigsimp, or "
        "`.equals`); a raw symbolic entry compared to 0 proves nothing."
    ),
}

ALTERNATIVE_STRATEGIES = {
    "assumed_bound": (
        "certify the sign by an EXHIBITED POINT plus continuity (construct the point "
        "explicitly for every parameter value) instead of bounding the integral by "
        "estimates you have not proven"
    ),
    "undecidable_positivity": (
        "re-parameterize the whole validator on the bound, q-dependent expressions "
        "(define omega_i, omega_f, B_q once from q, m_i, d) so every sign is decided "
        "by the engine on the expression actually used"
    ),
    "link_in_comment": (
        "restructure the validator as a chain of executed CHECK legs where each "
        "logical link is a computed boolean and the verdict is their conjunction"
    ),
    "proxy_continuity": (
        "replace the continuity argument by an exact domain query on the real "
        "expression plus an explicit epsilon-neighbourhood bound computed in code"
    ),
    "missing_domain": (
        "declare every parameter with its domain in the symbol assumptions "
        "(positive=True, real=True) and split cases explicitly instead of testing a "
        "single representative"
    ),
    "sampling_as_proof": (
        "replace sampling by an exact route: a symbolic identity, a Z3 proof that the "
        "negation is unsat, or an explicit counterexample search with a certified "
        "witness; keep numerics as a non-gating leg"
    ),
}
_GENERIC_ALTERNATIVE = (
    "choose a different computational route for the decisive claim (exact CAS "
    "identity, Z3 unsat of the negation, or an explicit certified counterexample) "
    "rather than repairing the rejected wiring"
)


def detector_enabled(env=None) -> bool:
    """ASTRA_REVIEW_STUCK_DETECTOR: on by default; 0/off/false/no disables C2
    entirely and the review loop behaves exactly as before."""
    source = os.environ if env is None else env
    raw = str(source.get("ASTRA_REVIEW_STUCK_DETECTOR", "1") or "").strip().strip("'\"")
    return raw.lower() not in {"0", "off", "false", "no"}


_CLAUSE_SPLIT = re.compile(r"(?<=[.;])\s+|,?\s+\b(?:but|however|whereas|although|yet)\b,?\s+")
# Anchored on an auxiliary verb so "fixed t = 1", "the fixed point U0" or
# "the fix removed the only executed check" (live defects) are not scrubbed.
_RESOLVED = re.compile(
    r"\b((is|are|was|were|has\s+been|have\s+been|now)\s+(resolved|fixed|addressed|"
    r"removed|sound|correct)|no\s+longer|now\s+(exact|bound|connected|decidable|"
    r"executed|certified))\b",
    re.IGNORECASE,
)


def _review_text(review: dict) -> str:
    """The reviewer's reasoning with resolution clauses removed.

    Reasoning only: revision_instructions are prescriptive and name every leg
    to preserve, which would classify every round as every class. Clauses that
    say a defect is fixed ("the independent-symbols issue is now resolved,
    however ...") are dropped so the resolved class is not re-detected and
    mistaken for a repeat. A clause that praises and complains at once ("X is
    sound, but Y is asserted only in comments") is split at the contrast word
    so only the praise is dropped.
    """
    text = str((review or {}).get("reasoning") or "")
    clauses = _CLAUSE_SPLIT.split(text)
    # A dropped clause becomes "." so its neighbours do not fuse into one
    # sentence that the [^.;]{0,N} context windows would then span.
    return " ".join("." if _RESOLVED.search(c) else c for c in clauses if c)


def classify_review(review: dict) -> dict:
    """Classes a rejection belongs to, in priority order, with the evidence.

    Returns ``{"classes": [...], "primary": str, "evidence": {cls: [snippet]}}``.
    ``classes[0]`` is the primary defect; ``classes`` is empty and ``primary``
    is ``other`` when nothing is recognised.
    """
    text = _review_text(review)
    labels = {
        str(item).strip().lower()
        for item in ((review or {}).get("defect_labels") or [])
    }
    evidence: dict[str, list[str]] = {}
    for cls, patterns in _COMPILED.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                evidence.setdefault(cls, []).append(match.group(0)[:80])
    for label, cls in _LABEL_TO_CLASS.items():
        if label in labels:
            evidence.setdefault(cls, []).append(f"label:{label}")
    for label in LABEL_CLASSES:
        if label in labels:
            evidence.setdefault(label, []).append(f"label:{label}")
    classes = [cls for cls in ALL_CLASSES if cls in evidence]
    return {
        "classes": classes,
        "primary": classes[0] if classes else OTHER,
        "evidence": evidence,
    }


def repeated_classes(previous: list, current: list) -> list:
    """Classes present in both consecutive rejections that are the primary
    (first) class of at least one of them. ``other`` never repeats."""
    previous = [c for c in (previous or []) if c != OTHER]
    current = [c for c in (current or []) if c != OTHER]
    if not previous or not current:
        return []
    anchors = {previous[0], current[0]}
    return [
        cls for cls in ALL_CLASSES
        if cls in previous and cls in current and cls in anchors
    ]


def directed_correction(classes: list) -> str:
    named = [c for c in classes if c in DIRECTED_CORRECTIONS]
    if not named:
        return ""
    return (
        "DIRECTED CORRECTION (ASTRA C2, defect class(es): "
        + ", ".join(named)
        + "). The reviewer's rejection matches known wiring defects; fix them at "
        "the root, not by rewording:\n- "
        + "\n- ".join(DIRECTED_CORRECTIONS[c] for c in named)
    )


def alternative_strategy(classes: list) -> str:
    items = [ALTERNATIVE_STRATEGIES.get(c, _GENERIC_ALTERNATIVE) for c in classes]
    if not items:
        items = [_GENERIC_ALTERNATIVE]
    return (
        "STRATEGY SWITCH (ASTRA C2): the independent reviewer rejected the same "
        "defect class(es) again (" + ", ".join(classes) + ") after a directed "
        "correction. Do NOT patch the previous script again. Re-derive the "
        "validator with a different certification route:\n- "
        + "\n- ".join(dict.fromkeys(items))
        + "\nKeep the scientific claim unchanged, keep every leg the reviewer "
        "called sound, and discard the rejected wiring."
    )


def stuck_message(classes: list, rounds: list, revisions: int, max_revisions: int,
                  reasoning: str = "", actions: list | None = None,
                  switched_for: list | None = None) -> str:
    """Error text for the clean stop.

    Must not contain "time budget" or "timeout tras": astra_tool._fail keys on
    those phrases to classify a PARTIAL (deadline) outcome, and a stuck loop is
    a TOOL_ERROR with a diagnosis, not a deadline.
    """
    taken = [a for a in (actions or []) if a in ("directed_patch", "strategy_switch")]
    if not taken:
        after = "with no revision left to try"
    elif "strategy_switch" not in taken:
        after = "after a directed correction"
    elif not switched_for or set(switched_for) & set(classes):
        after = "after a directed correction and a strategy switch"
    else:
        after = (
            "after a directed correction, with the single strategy switch already "
            f"spent on {', '.join(switched_for)}"
        )
    return (
        f"Review stuck on defect class {', '.join(classes)}: the independent "
        f"reviewer rejected the same class in review rounds {rounds} {after}; "
        f"stopping clean with {revisions} model revision(s) used of "
        f"{max_revisions} instead of repeating. Last reviewer reasoning: "
        f"{str(reasoning or '')[:600]}"
    )


class StuckTracker:
    """Remembers the classes of every model-reviewer rejection in one cycle and
    decides the next action. ``trace`` may be a shared list so the caller can
    stamp it on the checkpoint and the result (spec 'Transversal:
    procedencia')."""

    def __init__(self, trace: list | None = None):
        # ``trace`` may already hold the rejections of an earlier review loop
        # of the same cycle (astra_tool re-enters _review_or_revise after a
        # post-oracle retry with a regenerated validator). Those belong to a
        # different script and end with an APPROVED, so they are provenance
        # only: repeats are detected within this loop, from ``_base`` on.
        self.trace = trace if trace is not None else []
        self._base = len(self.trace)
        self.switched = False
        self.switched_for: list = []

    @property
    def own(self) -> list:
        """This loop's rejections (the shared trace from ``_base`` on)."""
        return self.trace[self._base:]

    def observe(self, review: dict, review_round: int, revision: int,
                can_revise: bool = True) -> dict:
        found = classify_review(review)
        previous = self.own[-1]["classes"] if self.own else []
        repeated = repeated_classes(previous, found["classes"])
        if repeated and (self.switched or not can_revise):
            action = "stop"
        elif not can_revise:
            action = "cap_reached"
        elif repeated:
            action = "strategy_switch"
            self.switched = True
            self.switched_for = list(repeated)
        elif found["classes"]:
            action = "directed_patch"
        else:
            action = "blind"
        record = {
            "review_round": review_round,
            "revision": revision,
            "classes": found["classes"],
            "primary": found["primary"],
            "repeated": repeated,
            "action": action,
            "evidence": found["evidence"],
        }
        self.trace.append(record)
        return record

    def diagnosis(self) -> dict:
        own = self.own
        repeated = [r for r in own if r["repeated"]]
        classes = repeated[-1]["repeated"] if repeated else []
        return {
            "stuck_classes": classes,
            "rounds": [r["review_round"] for r in own],
            "rejections": len(own),
            "actions": [r["action"] for r in own],
            "switched_for": list(self.switched_for),
            "classes_per_round": [r["classes"] for r in own],
            "earlier_rejections": self._base,
        }
