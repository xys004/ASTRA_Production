"""A first-class "non-decidable with these inputs" outcome for one cycle.

Motivation (cycle pid 32808, 2026-09-09): the conjecture required inputs the
request never contained (a material class, a frozen fixed point, an ansatz,
boundary data). The translator did the right thing -- its validator checked
for them, printed ``RESULT: NON-DECIDABLE`` with one ``missing:`` line per
input, emitted no VERDICT and exited 3 -- but the analyst only knew
VALIDATED / REFUTED / CODE_ERROR, mapped it to CODE_ERROR with a
``corrected_code``, and the post-oracle retry loop regenerated the validator
twice with the same outcome. Thirty minutes to learn what the first run had
already said.

Protocol (agents/translator.py, vNEXT contract rule 6): a validator that cannot
be instantiated because decisive inputs are absent prints
``VERDICT: NON-DECIDABLE``, one ``MISSING: <input>`` line per absent input,
and exits with code 3. ``RESULT: NON-DECIDABLE`` and lower-case ``missing:``
are accepted too (that is what the 32808 validator produced on its own).

Rules (``resolve_non_decidable``), deterministic and conservative:

* the analyst may return ``NON_DECIDABLE`` only when the validator declared
  it (core/llm_client.py downgrades an undeclared one to CODE_ERROR);
* declared + analyst agrees -> NON_DECIDABLE, no retry: a rewrite cannot
  supply data the request does not contain;
* declared + analyst says VALIDATED/REFUTED -> NON_DECIDABLE: there is no
  oracle verdict to support a decisive status;
* declared + analyst says CODE_ERROR/WEAK_PASS -> the analyst may know the
  inputs are derivable, so ONE retry is allowed; a second declaration by
  the regenerated validator ends the cycle as NON_DECIDABLE.
"""
from __future__ import annotations

import re

NON_DECIDABLE = "NON_DECIDABLE"

_MARKER = re.compile(r"^\s*(?:VERDICT|RESULT)\s*:\s*NON[-_ ]?DECIDABLE\b", re.IGNORECASE | re.MULTILINE)
_MISSING = re.compile(r"^\s*MISSING\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_VERDICT = re.compile(r"VERDICT\s*:\s*(PASS|FAIL)\b", re.IGNORECASE)

HINT = (
    "Answer the result's input_request: re-run with `inputs` (values or pasted "
    "frozen contents), with input_policy='assume' (declared placeholders, verdict "
    "conditional on them), or with values the agent extracts from a source; "
    "resume_checkpoint reuses this cycle's conjecture. structure_request=true "
    "lists REQUIRED INPUTS before a cycle runs."
)


def _clean_items(items) -> list:
    seen = []
    for item in items or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" -*\t")
        if text and text not in seen:
            seen.append(text)
    return seen


def detect_non_decidable(exec_result: dict) -> dict | None:
    """The validator's own declaration, or None.

    Requires the marker, at least one MISSING line (a declaration that names
    nothing missing is not a declaration: a bare marker, or a physics sentence
    such as "result: non-decidable region found", must not turn a crash into
    NON_DECIDABLE) and the absence of a PASS/FAIL verdict (a script printing
    both is contradictory and is left to the analyst/guard).
    """
    stdout = str((exec_result or {}).get("stdout") or "")
    if not _MARKER.search(stdout) or _VERDICT.search(stdout):
        return None
    missing = _clean_items(_MISSING.findall(stdout))
    if not missing:
        return None
    return {
        "declared_by": "validator",
        "missing_inputs": missing,
        "exit_code": (exec_result or {}).get("exit_code"),
    }


def resolve_non_decidable(analysis: dict, declaration: dict | None, declarations: int,
                          retry_available: bool = True) -> dict:
    """Apply the rules above to one analyst verdict. Returns a new dict.

    ``declarations`` counts how many validators of this cycle have declared
    non-decidability so far (this one included). ``retry_available`` says
    whether the post-oracle loop can still run a retry: without one, a
    CODE_ERROR/WEAK_PASS analysis on a declared validator is finalized as
    NON_DECIDABLE instead of ending the cycle as a code error with the
    declaration half recorded.
    """
    analysis = dict(analysis or {})
    status = str(analysis.get("status") or "").upper()
    analyst_inputs = _clean_items(analysis.get("missing_inputs"))
    if declaration is None:
        if status == NON_DECIDABLE:
            # Belt and braces: llm_client already downgrades this case.
            analysis["status"] = "CODE_ERROR"
            analysis["reasoning"] = (
                "Analyst proposed NON_DECIDABLE but the validator declared no "
                "VERDICT: NON-DECIDABLE; treated as CODE_ERROR. "
                + str(analysis.get("reasoning") or "")
            ).strip()
            analysis["missing_inputs"] = analyst_inputs
        return analysis

    missing = _clean_items(list(declaration.get("missing_inputs") or []) + analyst_inputs)
    record = {
        "declared_by": declaration.get("declared_by", "validator"),
        "declarations": declarations,
        "missing_inputs": missing,
        "analyst_status": status,
        "hint": HINT,
    }
    if status == NON_DECIDABLE:
        record["resolution"] = "validator declared, analyst agreed"
    elif status in {"VALIDATED", "REFUTED"}:
        record["resolution"] = (
            f"validator declared non-decidability and emitted no VERDICT; the analyst's "
            f"{status} has no oracle verdict to rest on"
        )
        analysis["reasoning"] = (
            f"[{record['resolution']}] " + str(analysis.get("reasoning") or "")
        ).strip()
    elif status not in {"CODE_ERROR", "WEAK_PASS"}:
        # API_ERROR or anything unexpected: keep the analysis as it is, but do
        # not lose the declaration (provenance for whoever reads the result).
        record["resolution"] = f"validator declared; analyst status {status or 'missing'} left as is"
        analysis["non_decidable"] = record
        analysis["missing_inputs"] = missing
        return analysis
    elif declarations >= 2:
        record["resolution"] = (
            f"declared by {declarations} validators so far in this cycle; a regenerated "
            "validator cannot supply data the request does not contain"
        )
        analysis["reasoning"] = (
            f"[{record['resolution']}] " + str(analysis.get("reasoning") or "")
        ).strip()
    elif not retry_available:
        record["resolution"] = (
            "validator declared; the analyst asked for a rewrite but no retry is "
            "available, and a rewrite cannot supply data the request does not contain"
        )
        analysis["reasoning"] = (
            f"[{record['resolution']}] " + str(analysis.get("reasoning") or "")
        ).strip()
    else:
        # First declaration, analyst thinks it is a code problem (the inputs
        # may be derivable): keep CODE_ERROR/WEAK_PASS, allow the one retry.
        record["resolution"] = "first declaration; analyst asked for a rewrite, one retry allowed"
        analysis["non_decidable"] = record
        analysis["missing_inputs"] = missing
        return analysis

    analysis["status"] = NON_DECIDABLE
    analysis["non_decidable"] = record
    analysis["missing_inputs"] = missing
    analysis.pop("corrected_code", None)
    analysis["goal_coverage"] = "PARTIAL"
    analysis["goal_resolved"] = False
    raw_deferred = analysis.get("deferred_items")
    deferred = (
        [raw_deferred.strip()] if isinstance(raw_deferred, str) and raw_deferred.strip()
        else [str(x) for x in raw_deferred] if isinstance(raw_deferred, list) else []
    )
    for item in missing:
        entry = f"Provide the missing input: {item}"
        if entry not in deferred:
            deferred.append(entry)
    analysis["deferred_items"] = deferred
    return analysis
