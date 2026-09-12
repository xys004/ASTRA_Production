"""Ask instead of stop: what a cycle says when decisive inputs are missing.

Nelson, 2026-09-09: "si faltan cosas que se necesitan, que ASTRA me pregunte,
para ver si las tengo, si le doy valores, le digo que suponga valores o los
extraiga de algun lugar; no tiene que finalizar el ciclo sin decidir como
unica salida". ASTRA has no channel to the user of its own: it answers the
calling agent. So a NON_DECIDABLE result carries an explicit ``input_request``
the agent must put to the user, with three answers and, for each, the exact
re-run request (``inputs``, ``input_policy``, ``resume_checkpoint``).

Request fields (astra_cycle / astra_cycle_submit)
-------------------------------------------------
* ``inputs``: the values or frozen contents the user supplies (free text, or
  a mapping name -> value). They reach the conjecture engine, the structurer
  and the validator author as an authoritative FROZEN INPUTS block.
* ``input_policy``: ``strict`` (default: a missing input ends the cycle as
  NON_DECIDABLE with the question) or ``assume`` (the user approved
  placeholder values: the validator declares each one in an ``ASSUMED:``
  line and proceeds; the verdict is reported as conditional on them).
* ``resume_checkpoint``: the checkpoint of the cycle that asked; its
  conjecture is reused (it was already paid for) and the new run starts at
  the validator with the inputs in hand.
"""
from __future__ import annotations

import json
import re

INPUT_POLICIES = ("strict", "assume")

ASSUME_POLICY_TEXT = (
    "INPUT POLICY: assume. The user approved placeholder values for the inputs "
    "this request does not contain. Do NOT declare non-decidability for them: "
    "choose explicit, physically reasonable values, print one line "
    "`ASSUMED: <input> = <value> -- <reason>` per assumption before the CHECK "
    "lines, and proceed to a PASS/FAIL verdict. The verdict is conditional on "
    "those assumptions and ASTRA reports them as such."
)

_ASSUMED = re.compile(r"^\s*ASSUMED\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_RERUN_KEYS = ("intuition", "objective", "oracle", "exec_timeout", "structure_request",
               "max_mode", "axiomatic_base")
_NONE_WORDS = {"none", "none.", "n/a", "nothing", "-"}
# A pasted table or paper must not blow the CLI prompt (agy passes it as argv,
# ~32 KB ceiling in core/cli_backend.py); the excess is cut and reported.
INPUTS_MAX_CHARS = 20000


def input_policy(req: dict) -> str:
    raw = str((req or {}).get("input_policy") or "strict").strip().strip("'\"").lower()
    return raw if raw in INPUT_POLICIES else "strict"


def inputs_text(req: dict) -> str:
    """The user's inputs as text: a mapping becomes ``name: value`` lines.
    Capped at INPUTS_MAX_CHARS (see ``inputs_truncated``)."""
    raw = (req or {}).get("inputs")
    if not raw:
        return ""
    if isinstance(raw, dict):
        lines = []
        for name, value in raw.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines.append(f"{name}: {rendered}")
        text = "\n".join(lines)
    else:
        text = str(raw).strip()
    if len(text) > INPUTS_MAX_CHARS:
        text = text[:INPUTS_MAX_CHARS] + "\n[... inputs truncated by ASTRA at 20000 characters ...]"
    return text


def inputs_truncated(req: dict) -> bool:
    raw = (req or {}).get("inputs")
    if not raw:
        return False
    length = len(str(raw)) if not isinstance(raw, dict) else sum(
        len(str(k)) + len(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) + 2
        for k, v in raw.items()
    )
    return length > INPUTS_MAX_CHARS


def inputs_block(req: dict, inputs_limit: int | None = None) -> str:
    """Prompt block for the conjecture engine, the structurer and the author.

    The policy comes FIRST: whoever truncates the block downstream (the
    reviewer's 5000-character conjecture window, the structurer's 6000) must
    lose values before losing the one sentence that says placeholders were
    approved. ``inputs_limit`` caps the values for those auditors. Empty when
    the request supplies nothing and keeps the strict policy, so prompts are
    byte-for-byte what they were.
    """
    parts = []
    if input_policy(req) == "assume":
        parts.append(ASSUME_POLICY_TEXT)
    text = inputs_text(req)
    if text:
        if inputs_limit is not None and len(text) > inputs_limit:
            text = text[:inputs_limit] + "\n[... inputs shortened for this reader ...]"
        parts.append(
            "FROZEN INPUTS (supplied by the user; authoritative, use these exact "
            "values instead of declaring them missing):\n" + text
        )
    return "\n\n".join(parts)


def parse_assumed_inputs(stdout: str) -> list:
    seen = []
    for item in _ASSUMED.findall(str(stdout or "")):
        text = re.sub(r"\s+", " ", item).strip()
        if text and text.lower() not in _NONE_WORDS and text not in seen:
            seen.append(text)
    return seen


SILENT_ASSUME_DEFERRED = (
    "The validator ran under input policy 'assume' but declared no ASSUMED line: "
    "the placeholder values it used are unknown; confirm them before relying on "
    "this verdict."
)


def build_input_request(missing: list, checkpoint_path: str, req: dict) -> dict:
    """The question the calling agent must put to the user, with the three
    answers and the exact re-run for each."""
    missing = [str(m) for m in (missing or []) if str(m).strip()]
    base = {key: (req or {})[key] for key in _RERUN_KEYS if (req or {}).get(key)}
    resume = {"resume_checkpoint": checkpoint_path} if checkpoint_path else {}
    already = inputs_text(req)
    placeholder = "<name: value, or the pasted contents, one input per line>"
    extracted = "<the extracted values>"
    if already:
        # Keep what the user already supplied; the cycle still needs more.
        placeholder = already + "\n" + placeholder
        extracted = already + "\n" + extracted
    listed = ", ".join(missing) if missing else "inputs the request does not contain"
    return {
        "action_required": "ASK_USER",
        "question": (
            f"ASTRA cannot decide this cycle without: {listed}. Do you have these "
            "values (provide), should ASTRA assume explicit placeholder values and "
            "report the verdict as conditional on them (assume), or should they be "
            "extracted from a file or an earlier result (extract)?"
        ),
        "missing_inputs": missing,
        "options": {
            "provide": {
                "when": "the user has the values or the frozen contents",
                "rerun": {**base, **resume, "inputs": placeholder},
            },
            "assume": {
                "when": "the user lets ASTRA pick explicit placeholder values; the result "
                        "carries assumed_inputs and the verdict is conditional on them",
                "rerun": {**base, **resume, "input_policy": "assume"},
            },
            "extract": {
                "when": "the values live in a file, a paper, or a previous ASTRA result: the "
                        "agent reads them and passes them as inputs",
                "rerun": {**base, **resume, "inputs": extracted},
            },
        },
        "resume_checkpoint": checkpoint_path,
        "note": (
            "resume_checkpoint reuses this cycle's conjecture (already paid for) and "
            "starts the new run at the validator with the inputs in hand."
        ),
    }
