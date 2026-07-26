"""Shared ASTRA architecture configurations for fair ablation studies."""
from __future__ import annotations

import os
from typing import Any


ARCHITECTURE_ROLES: dict[str, dict[str, Any]] = {
    "full": {
        "proposers": ["codex_cli", "agy_cli"],
        "synthesizer": "codex_cli",
        "author": "claude_cli",
        "reviewer": "codex_cli",
        "repairer": "claude_cli",
    },
    "codex-only": {
        "proposers": ["codex_cli", "codex_cli"],
        "synthesizer": "codex_cli",
        "author": "codex_cli",
        "reviewer": "codex_cli",
        "repairer": "codex_cli",
    },
    # Matched control for the diversity experiment. It differs from ``full``
    # only in proposal 2: a second Codex replaces AGY/Gemini. All downstream
    # roles and the number/order of calls stay identical.
    "homogeneous-proposers": {
        "proposers": ["codex_cli", "codex_cli"],
        "synthesizer": "codex_cli",
        "author": "claude_cli",
        "reviewer": "codex_cli",
        "repairer": "claude_cli",
    },
    "claude-only": {
        "proposers": ["claude_cli", "claude_cli"],
        "synthesizer": "claude_cli",
        "author": "claude_cli",
        "reviewer": "claude_cli",
        "repairer": "claude_cli",
    },
    "agy-only": {
        "proposers": ["agy_cli", "agy_cli"],
        "synthesizer": "agy_cli",
        "author": "agy_cli",
        "reviewer": "agy_cli",
        "repairer": "agy_cli",
    },
    "no-review": {
        "proposers": ["codex_cli", "agy_cli"],
        "synthesizer": "codex_cli",
        "author": "claude_cli",
        "reviewer": "codex_cli",
        "repairer": "claude_cli",
    },
    "no-ensemble": {
        "proposers": ["codex_cli"],
        "synthesizer": "codex_cli",
        "author": "claude_cli",
        "reviewer": "codex_cli",
        "repairer": "claude_cli",
    },
}


def architecture_roles(name: str) -> dict[str, Any]:
    """Return a defensive copy of the named public-comparison role map."""
    key = name.strip().lower()
    if key not in ARCHITECTURE_ROLES:
        raise ValueError(f"Unknown architecture configuration: {name}")
    roles = ARCHITECTURE_ROLES[key]
    return {
        **roles,
        "proposers": list(roles["proposers"]),
    }


def architecture_environment(
    name: str,
    *,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build an isolated environment with a phase topology matching ``name``.

    Single-agent baselines intentionally receive two independent proposal calls.
    This preserves the proposal/synthesis topology and model-call count used by
    the compact full architecture; only the identity of the agent changes.
    """
    key = name.strip().lower()
    roles = architecture_roles(key)
    env = dict(base if base is not None else os.environ)
    # Phase-specific model lists from the production role map can belong to a
    # different provider (for example, Claude models for the translator). They
    # must not leak into a single-agent ablation after its provider is changed.
    for phase in (
        "CONJECTURE",
        "TRANSLATOR",
        "REVIEWER",
        "ANALYST",
        "NAVIGATOR",
        "SYNTH",
    ):
        # Keep explicit empty values in the child environment. Removing the
        # keys would let load_dotenv() restore production phase-model lists.
        env[f"ASTRA_{phase}_MODEL"] = ""
        env[f"ASTRA_{phase}_MODELS"] = ""
    env.update(
        {
            "ASTRA_CONJECTURE_PROVIDER": ",".join(roles["proposers"]),
            "ASTRA_TRANSLATOR_PROVIDER": roles["author"],
            "ASTRA_REVIEWER_PROVIDER": roles["reviewer"],
            "ASTRA_ANALYST_PROVIDER": roles["reviewer"],
            "ASTRA_NAVIGATOR_PROVIDER": roles["proposers"][-1],
            "ASTRA_SYNTH_PROVIDER": roles["synthesizer"],
            "ASTRA_CYCLE_CACHE": "0",
        }
    )
    if key == "no-review":
        env["ASTRA_CODE_REVIEW"] = "0"
    else:
        env.pop("ASTRA_CODE_REVIEW", None)
    return env
