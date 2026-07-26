"""Bounded exact-edit patches for model-assisted validator repair."""
from __future__ import annotations

import hashlib
from typing import Any


def apply_exact_edit_patch(
    code: str,
    payload: dict[str, Any] | None,
    *,
    max_edits: int = 8,
    max_replaced_fraction: float = 0.65,
    max_new_characters: int = 8000,
) -> dict[str, Any]:
    """Apply a small JSON exact-replacement patch without fuzzy guessing.

    Every ``old`` snippet must occur exactly once. This makes the change
    auditable and prevents a model from silently rewriting the whole validator.
    """
    if not isinstance(payload, dict):
        return {
            "status": "REJECTED",
            "reason": "Patch response was not a JSON object.",
            "code": code,
            "edits": [],
        }
    status = str(payload.get("status") or "PATCH").strip().upper()
    if status in {"CANNOT_PATCH", "REJECT", "REJECTED"}:
        return {
            "status": "CANNOT_PATCH",
            "reason": str(payload.get("reason") or "Model declined a local repair.")[:1000],
            "code": code,
            "edits": [],
        }
    edits = payload.get("edits")
    if not isinstance(edits, list) or not edits:
        return {
            "status": "REJECTED",
            "reason": "Patch must contain a non-empty `edits` list.",
            "code": code,
            "edits": [],
        }
    if len(edits) > max_edits:
        return {
            "status": "REJECTED",
            "reason": f"Patch requested {len(edits)} edits; limit is {max_edits}.",
            "code": code,
            "edits": [],
        }

    normalized: list[tuple[str, str]] = []
    total_old = 0
    total_new = 0
    for index, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict):
            return {
                "status": "REJECTED",
                "reason": f"Edit {index} is not an object.",
                "code": code,
                "edits": [],
            }
        old = edit.get("old")
        new = edit.get("new")
        if not isinstance(old, str) or not old:
            return {
                "status": "REJECTED",
                "reason": f"Edit {index} has an empty/non-string `old` snippet.",
                "code": code,
                "edits": [],
            }
        if not isinstance(new, str):
            return {
                "status": "REJECTED",
                "reason": f"Edit {index} has a non-string `new` snippet.",
                "code": code,
                "edits": [],
            }
        if old == new:
            return {
                "status": "REJECTED",
                "reason": f"Edit {index} makes no change.",
                "code": code,
                "edits": [],
            }
        occurrences = code.count(old)
        if occurrences != 1:
            return {
                "status": "REJECTED",
                "reason": (
                    f"Edit {index} `old` snippet occurs {occurrences} times; "
                    "exactly one occurrence is required."
                ),
                "code": code,
                "edits": [],
            }
        normalized.append((old, new))
        total_old += len(old)
        total_new += len(new)

    allowed_old = max(1, int(len(code) * max_replaced_fraction))
    if total_old > allowed_old:
        return {
            "status": "REJECTED",
            "reason": (
                f"Patch replaces {total_old}/{len(code)} source characters; "
                f"local-repair limit is {max_replaced_fraction:.0%}."
            ),
            "code": code,
            "edits": [],
        }
    if total_new > max_new_characters:
        return {
            "status": "REJECTED",
            "reason": (
                f"Patch introduces {total_new} characters; "
                f"limit is {max_new_characters}."
            ),
            "code": code,
            "edits": [],
        }

    patched = code
    records: list[dict[str, Any]] = []
    for old, new in normalized:
        if patched.count(old) != 1:
            return {
                "status": "REJECTED",
                "reason": (
                    "An earlier edit changed the target of a later edit; "
                    "submit non-overlapping exact snippets."
                ),
                "code": code,
                "edits": [],
            }
        patched = patched.replace(old, new, 1)
        records.append(
            {
                "old_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                "new_sha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
                "old_characters": len(old),
                "new_characters": len(new),
            }
        )
    return {
        "status": "APPLIED",
        "reason": str(payload.get("reason") or "Bounded exact-edit patch applied.")[:1000],
        "code": patched,
        "edits": records,
        "edit_count": len(records),
        "changed_characters": total_old + total_new,
    }
