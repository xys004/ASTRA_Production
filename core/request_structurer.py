"""C3 of the cycle-robustness spec: the opt-in request structurer.

Pure standard library. The model call lives in
``core.llm_client.ASTRAIntelligence.structure_request`` (prompt in
agents/structurer.py); this module decides whether a request asked for it,
parses the structured text, and composes the direction the conjecture engine
receives. Both the original and the structured request are kept on the
checkpoint and the result (spec 'Transversal: procedencia').
"""
from __future__ import annotations

import re

HEADINGS = (
    "BOUNDED CLAIM",
    "HYPOTHESES",
    "DECISIVE",
    "AUXILIARY",
    "CERTIFICATION",
    "REQUIRED INPUTS",
    "ANTI-PATTERNS",
    "DEFERRED",
)
_HEADING_RE = re.compile(
    r"^\s*(?:\*\*|#+\s*)?(" + "|".join(re.escape(h) for h in HEADINGS) + r")\s*(?:\*\*)?\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)
_NONE_WORDS = {"", "none", "none.", "n/a", "ninguno", "ninguna", "nothing", "-"}


def structure_requested(req: dict) -> bool:
    """True when the request opted in (``structure_request`` truthy)."""
    raw = (req or {}).get("structure_request")
    if isinstance(raw, str):
        return raw.strip().strip("'\"").lower() in {"1", "true", "on", "yes"}
    return bool(raw)


def parse_structured_request(text: str) -> dict:
    """Split the structurer's reply into its sections.

    Returns ``sections`` (heading -> text, missing headings map to ""),
    ``complete`` (every heading present), and ``required_inputs`` (the
    REQUIRED INPUTS list, empty when it says none).
    """
    text = str(text or "")
    sections = {h: "" for h in HEADINGS}
    matches = list(_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        heading = match.group(1).upper()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if not sections[heading]:            # first occurrence wins
            sections[heading] = body
    required_raw = sections["REQUIRED INPUTS"]
    required = []
    for line in re.split(r"[\n;]+", required_raw):
        item = line.strip().lstrip("-*0123456789.) ").strip()
        if item and item.lower() not in _NONE_WORDS:
            required.append(item)
    return {
        "sections": sections,
        "complete": all(sections[h] for h in HEADINGS),
        "required_inputs": required,
    }


def has_bounded_claim(parsed: dict) -> bool:
    """True when the structurer actually produced a claim (not empty, not 'none')."""
    body = str((parsed or {}).get("sections", {}).get("BOUNDED CLAIM") or "").strip()
    return bool(body) and body.lower() not in _NONE_WORDS


def compose_direction(structured: str, original: str, original_limit: int = 3000) -> str:
    """The ``intuition`` the cycle runs on: the structured direction first, the
    raw request after it as context only (truncated so it cannot dominate)."""
    original = str(original or "")
    if len(original) > original_limit:
        original = original[:original_limit] + "\n[... raw request truncated ...]"
    return (
        "STRUCTURED RESEARCH DIRECTION (ASTRA request structurer, C3; the raw "
        "request follows for context only):\n"
        f"{str(structured or '').strip()}\n\n"
        "RAW REQUEST (context, not the direction):\n"
        f"{original}"
    )
