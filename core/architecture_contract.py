"""Auditable contract for ASTRA's compact three-model production topology."""
from __future__ import annotations

import os
import shutil
import importlib.util
from pathlib import Path
from typing import Any, Mapping

from core.architecture_configs import architecture_roles


ARCHITECTURE_ID = "astra-compact-three-agent-v2"
QUOTA_ARCHITECTURE_ID = "astra-quota-optimized-v1"
MUSE_TRIAL_ARCHITECTURE_ID = "astra-muse-trial-v1"
QUOTA_RELIEF_ARCHITECTURE_ID = "astra-quota-relief-v1"
MUSE_TRIAL_MODEL = "muse-spark-1.3"
# 7 (2026-09-09): the cycle cache payload gained inputs / input_policy /
# resume_checkpoint (core/input_request.py); bumped so the invalidation of
# every earlier entry is documented, not silent (same precedent as 4->5, 5->6).
CACHE_SCHEMA_VERSION = "7"

EXPECTED_PRIMARY_MODELS = {
    "codex_cli": "gpt-5.6-sol",
    "claude_cli": "claude-opus-4-8",
    "agy_cli": "gemini-3.1-pro-high",
}

_ROOT = Path(__file__).resolve().parent.parent
_DEV_ROOT = _ROOT.parent


def _value(env: Mapping[str, str], key: str, default: str = "") -> str:
    return str(env.get(key, default) or "").strip().strip("'\"")


def _csv(env: Mapping[str, str], key: str, default: str = "") -> list[str]:
    return [
        item.strip().lower()
        for item in _value(env, key, default).split(",")
        if item.strip()
    ]


def _enabled(env: Mapping[str, str], key: str, default: str = "1") -> bool:
    return _value(env, key, default).lower() not in {"0", "off", "false", "no"}


def _translator_strict_contract(env: Mapping[str, str]) -> bool:
    # Local import: agents.translator has no import of core.architecture_contract
    # (checked), so this is safe at call time; kept local rather than at module
    # top to match this file's existing deferred-import style for agent modules.
    from agents.translator import parse_strict_flag

    return parse_strict_flag(_value(env, "ASTRA_TRANSLATOR_STRICT_CONTRACT", "0"))


def _integer(
    env: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    try:
        return int(_value(env, key, str(default)))
    except ValueError:
        return default


def production_manifest(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the non-secret configuration that determines one ASTRA cycle."""
    source = os.environ if env is None else env
    profile = _value(source, "ASTRA_ARCHITECTURE_PROFILE", "full").lower()
    role_profile = (
        "no-ensemble"
        if profile == "quota-optimized"
        else "muse-trial"
        if profile == "muse-trial"
        else "quota-relief"
        if profile == "quota-relief"
        else "full"
    )
    full = architecture_roles(role_profile)
    author = _value(
        source,
        "ASTRA_TRANSLATOR_PROVIDER",
        full["author"],
    ).lower()
    roles = {
        "proposers": _csv(
            source,
            "ASTRA_CONJECTURE_PROVIDER",
            ",".join(full["proposers"]),
        ),
        "synthesizer": _value(
            source,
            "ASTRA_SYNTH_PROVIDER",
            full["synthesizer"],
        ).lower(),
        "author": author,
        "reviewer": _value(
            source,
            "ASTRA_REVIEWER_PROVIDER",
            full["reviewer"],
        ).lower(),
        "analyst": _value(
            source,
            "ASTRA_ANALYST_PROVIDER",
            full["reviewer"],
        ).lower(),
        "navigator": _value(
            source,
            "ASTRA_NAVIGATOR_PROVIDER",
            full.get("navigator", full["proposers"][-1]),
        ).lower(),
        "repairer": author,
    }
    provider_models = {
        "codex_cli": _csv(
            source,
            "ASTRA_CODEX_MODELS",
            EXPECTED_PRIMARY_MODELS["codex_cli"],
        ),
        "claude_cli": _csv(
            source,
            "ASTRA_CLAUDE_MODELS",
            EXPECTED_PRIMARY_MODELS["claude_cli"],
        ),
        "agy_cli": _csv(
            source,
            "ASTRA_AGY_MODELS",
            EXPECTED_PRIMARY_MODELS["agy_cli"],
        ),
        "muse_cli": _csv(source, "ASTRA_MUSE_MODELS", MUSE_TRIAL_MODEL),
    }
    phase_overrides = {
        phase.lower(): _csv(source, f"ASTRA_{phase}_MODELS")
        or _csv(source, f"ASTRA_{phase}_MODEL")
        for phase in (
            "CONJECTURE",
            "SYNTH",
            "TRANSLATOR",
            "REVIEWER",
            "ANALYST",
            "NAVIGATOR",
        )
    }

    def effective(phase: str, provider: str) -> list[str]:
        return phase_overrides.get(phase, []) or provider_models.get(provider, [])

    return {
        "architecture_id": (
            QUOTA_ARCHITECTURE_ID
            if profile == "quota-optimized"
            else MUSE_TRIAL_ARCHITECTURE_ID
            if profile == "muse-trial"
            else QUOTA_RELIEF_ARCHITECTURE_ID
            if profile == "quota-relief"
            else ARCHITECTURE_ID
        ),
        "profile": profile,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "roles": roles,
        "models": {
            **provider_models,
            "translator": _csv(source, "ASTRA_TRANSLATOR_MODELS"),
            "phase_overrides": phase_overrides,
            "effective": {
                # Heterogeneous proposal calls use each CLI's provider ladder.
                "codex_proposer": provider_models["codex_cli"],
                "agy_proposer": provider_models["agy_cli"],
                "muse_proposer": provider_models["muse_cli"],
                "synthesizer": effective("synth", roles["synthesizer"]),
                "author": effective("translator", roles["author"]),
                "reviewer": effective("reviewer", roles["reviewer"]),
                "analyst": effective("analyst", roles["analyst"]),
                "navigator": effective("navigator", roles["navigator"]),
            },
        },
        "effort": {
            "codex": _value(source, "ASTRA_CODEX_REASONING", "xhigh").lower(),
            "agy": _value(source, "ASTRA_AGY_EFFORT", "high").lower(),
            "muse": _value(source, "ASTRA_MUSE_REASONING", "high").lower(),
        },
        "controls": {
            "cross_critique": len(roles["proposers"]) >= 2,
            "independent_code_review": _enabled(
                source,
                "ASTRA_CODE_REVIEW",
            ),
            "post_cycle_navigation": _enabled(
                source,
                "ASTRA_NAVIGATE_AFTER_CYCLE",
            ),
            "validator_repair_vnext": _enabled(
                source,
                "ASTRA_VALIDATOR_REPAIR_VNEXT",
            ),
            "validator_repair_strategy": _value(
                source,
                "ASTRA_VALIDATOR_REPAIR_STRATEGY",
                "local-patch",
            ).lower(),
            # Opt-in strict certification contract for the translator/repairer
            # (docs/architecture/CYCLE_ROBUSTNESS_SPEC.md, C0). Stamped here so
            # (a) the cycle cache key -- which embeds this manifest -- changes
            # when the overlay flips, so a strict re-run never replays a cached
            # non-strict verdict, and (b) every result/checkpoint records which
            # translator contract produced it (spec 'Transversal: procedencia').
            # Adding this field bumped CACHE_SCHEMA_VERSION 4->5 (same precedent
            # as the earlier 'profile' addition): every existing workspace/
            # cycle_cache entry is invalidated intentionally and once, not
            # silently -- the version bump documents it.
            #
            # Parsed with agents.translator.parse_strict_flag, NOT the generic
            # _enabled() below: _enabled()'s deny-list convention (truthy unless
            # "off") would stamp translator_strict_contract=true for a stray
            # value the translator itself reads as false (e.g. "" or a typo),
            # so provenance and the cache key would disagree with what the
            # cycle actually ran.
            "translator_strict_contract": _translator_strict_contract(source),
            # C2 (cycle-robustness spec): the stuck-review detector, on by
            # default; ASTRA_REVIEW_STUCK_DETECTOR=0 restores the blind loop.
            # Stamped for provenance and the cycle cache key exactly like the
            # strict contract; adding it bumped CACHE_SCHEMA_VERSION 5->6.
            "review_stuck_detector": _enabled(
                source,
                "ASTRA_REVIEW_STUCK_DETECTOR",
            ),
            "required_local_engines": _csv(
                source,
                "ASTRA_REQUIRED_LOCAL_ENGINES",
            ),
            "max_concurrent_cycles": _integer(
                source,
                "ASTRA_MAX_CONCURRENT_CYCLES",
                1,
            ),
        },
        "topology": [
            *(
                ["parallel_proposals", "cross_critique", "codex_consensus"]
                if len(roles["proposers"]) >= 2
                else ["single_frontier_proposal"]
            ),
            "claude_validator_authoring",
            "deterministic_preflight",
            "codex_independent_review",
            "oracle_execution",
            "codex_evidence_audit",
            "agy_research_navigation",
        ],
    }


def _integration_path(
    env: Mapping[str, str],
    key: str,
    fallback: Path,
) -> Path:
    configured = _value(env, key)
    return (
        Path(configured).expanduser()
        if configured
        else fallback
    ).resolve()


def audit_production_architecture(
    env: Mapping[str, str] | None = None,
    *,
    check_binaries: bool = True,
) -> dict[str, Any]:
    """Fail closed on required role/model/gate drift; report optional tools."""
    source = os.environ if env is None else env
    manifest = production_manifest(source)
    profile = manifest["profile"]
    known_profile = profile in {"full", "quota-optimized", "muse-trial", "quota-relief"}
    expected = architecture_roles(
        "no-ensemble"
        if profile == "quota-optimized"
        else "muse-trial"
        if profile == "muse-trial"
        else "quota-relief"
        if profile == "quota-relief"
        else "full"
    )
    expected_roles = {
        "proposers": expected["proposers"],
        "synthesizer": expected["synthesizer"],
        "author": expected["author"],
        "reviewer": expected["reviewer"],
        "analyst": expected["reviewer"],
        "navigator": expected.get("navigator", "agy_cli"),
        "repairer": expected["repairer"],
    }
    checks: list[dict[str, Any]] = []

    def add(
        check_id: str,
        passed: bool,
        actual: Any,
        expected_value: Any,
        *,
        required: bool = True,
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "passed": bool(passed),
                "required": required,
                "actual": actual,
                "expected": expected_value,
            }
        )

    add(
        "architecture_profile",
        known_profile,
        profile,
        "full, quota-optimized, muse-trial, or quota-relief",
    )
    add(
        "production_role_map",
        known_profile and manifest["roles"] == expected_roles,
        manifest["roles"],
        expected_roles,
    )
    for provider, primary in EXPECTED_PRIMARY_MODELS.items():
        ladder = manifest["models"][provider]
        add(
            f"{provider}_primary_model",
            bool(ladder) and ladder[0] == primary,
            ladder[0] if ladder else "",
            primary,
        )
    if profile == "muse-trial":
        muse_ladder = manifest["models"]["muse_cli"]
        add(
            "muse_trial_model",
            muse_ladder == [MUSE_TRIAL_MODEL],
            muse_ladder,
            [MUSE_TRIAL_MODEL],
        )
    expected_effective = {
        "codex_proposer": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "agy_proposer": EXPECTED_PRIMARY_MODELS["agy_cli"],
        "synthesizer": (
            EXPECTED_PRIMARY_MODELS["agy_cli"]
            if profile == "quota-relief"
            else EXPECTED_PRIMARY_MODELS["codex_cli"]
        ),
        "author": (
            "sonnet"
            if profile == "quota-optimized"
            else EXPECTED_PRIMARY_MODELS["claude_cli"]
        ),
        "reviewer": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "analyst": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "navigator": EXPECTED_PRIMARY_MODELS["agy_cli"],
    }
    if profile == "muse-trial":
        expected_effective["muse_proposer"] = MUSE_TRIAL_MODEL
    for role, primary in expected_effective.items():
        ladder = manifest["models"]["effective"][role]
        add(
            f"{role}_effective_model",
            bool(ladder) and ladder[0] == primary,
            ladder[0] if ladder else "",
            primary,
        )
    add(
        "codex_reasoning",
        manifest["effort"]["codex"] == "xhigh",
        manifest["effort"]["codex"],
        "xhigh",
    )
    add(
        "agy_effort",
        manifest["effort"]["agy"] == "high",
        manifest["effort"]["agy"],
        "high",
    )
    if profile == "muse-trial":
        add(
            "muse_reasoning",
            manifest["effort"]["muse"] == "high",
            manifest["effort"]["muse"],
            "high",
        )
    add(
        "independent_code_review",
        manifest["controls"]["independent_code_review"],
        manifest["controls"]["independent_code_review"],
        True,
    )
    expected_navigation = profile != "quota-optimized"
    add(
        "post_cycle_navigation",
        manifest["controls"]["post_cycle_navigation"] == expected_navigation,
        manifest["controls"]["post_cycle_navigation"],
        expected_navigation,
    )
    add(
        "validator_repair_vnext",
        manifest["controls"]["validator_repair_vnext"],
        manifest["controls"]["validator_repair_vnext"],
        True,
    )
    add(
        "deliberative_cycle_serialization",
        manifest["controls"]["max_concurrent_cycles"] == 1,
        manifest["controls"]["max_concurrent_cycles"],
        1,
    )

    if check_binaries:
        for provider, binary in (
            ("codex_cli", "codex"),
            ("claude_cli", "claude"),
            ("agy_cli", "agy"),
        ):
            location = shutil.which(binary)
            add(
                f"{provider}_binary",
                location is not None,
                location or "",
                f"{binary} available on PATH",
            )
        if profile == "muse-trial":
            wsl_location = shutil.which("wsl.exe")
            add(
                "muse_cli_wsl_bridge",
                wsl_location is not None,
                wsl_location or "",
                "wsl.exe available on PATH; astra_doctor also verifies Muse in WSL",
            )

    scientific_engines: dict[str, dict[str, Any]] = {}
    if check_binaries:
        from core.engine_router import available_cas

        cas = available_cas()
        required_engines = set(
            manifest["controls"]["required_local_engines"]
        )
        known_engines = {
            "z3",
            "sagemath",
            "maxima",
            "cadabra",
            "lean4_local",
        }
        for unknown in sorted(required_engines - known_engines):
            add(
                f"scientific_engine_unknown_{unknown}",
                False,
                unknown,
                f"one of {sorted(known_engines)}",
            )
        z3_available = importlib.util.find_spec("z3") is not None
        scientific_engines = {
            "z3": {
                "available": z3_available,
                "route": "local Python module",
            },
            "sagemath": {
                "available": cas["sage"] is not None,
                "route": cas["sage"] or "not available",
            },
            "maxima": {
                "available": cas["maxima"] is not None,
                "route": cas["maxima"] or "not available",
            },
            "cadabra": {
                "available": cas["cadabra"] is not None,
                "route": cas["cadabra"] or "not available",
            },
        }
        for name, detail in scientific_engines.items():
            add(
                f"scientific_engine_{name}",
                detail["available"],
                detail["route"],
                "available to the local oracle",
                required=name in required_engines,
            )

        local_lean_root_raw = _value(source, "ASTRA_LOCAL_LEAN4_ROOT")
        local_lean_root = (
            Path(local_lean_root_raw).expanduser().resolve()
            if local_lean_root_raw
            else None
        )
        local_lake = (
            _value(source, "ASTRA_LOCAL_LAKE_BIN")
            or shutil.which("lake")
            or ""
        )
        native_lean_available = bool(
            local_lean_root
            and local_lean_root.is_dir()
            and local_lake
        )
        wsl_lean_root = _value(source, "ASTRA_LOCAL_LEAN4_WSL_ROOT")
        wsl_lean_lake = _value(
            source,
            "ASTRA_LOCAL_LEAN4_WSL_LAKE_BIN",
        )
        wsl_lean_available = bool(
            wsl_lean_root
            and wsl_lean_lake
            and cas["lean4"]
        )
        local_lean_available = native_lean_available or wsl_lean_available
        remote_lean_configured = bool(
            _value(source, "ASTRA_REMOTE_HOST")
        )
        scientific_engines["lean4_local"] = {
            "available": local_lean_available,
            "route": (
                cas["lean4"]
                if wsl_lean_available
                else f"{local_lake} @ {local_lean_root}"
                if native_lean_available
                else "pinned local project/lake not configured"
            ),
        }
        scientific_engines["lean4_remote"] = {
            "available": remote_lean_configured,
            "route": (
                "ASTRUM SSH route configured"
                if remote_lean_configured
                else "remote oracle not configured"
            ),
        }
        add(
            "scientific_engine_lean4_local",
            local_lean_available,
            scientific_engines["lean4_local"]["route"],
            "pinned Lean 4 project and Lake available locally",
            required="lean4_local" in required_engines,
        )
        add(
            "scientific_engine_lean4_remote_route",
            remote_lean_configured,
            scientific_engines["lean4_remote"]["route"],
            "ASTRUM SSH route configured",
            required=False,
        )

    integrations = {
        "gr_python": _integration_path(
            source,
            "ASTRA_GR_PYTHON_ROOT",
            _DEV_ROOT / "gr" / "GR_python",
        ),
        "pywarpfactory": _integration_path(
            source,
            "ASTRA_PYWARPFACTORY_ROOT",
            _DEV_ROOT / "warp" / "pyWarpFactory_push",
        ),
        "warp_bubble_optimization": _integration_path(
            source,
            "ASTRA_WARPBUBBLE_OPT_ROOT",
            _DEV_ROOT / "warp" / "warp_bubble_optimization",
        ),
        "mathematica_bridge": _integration_path(
            source,
            "ASTRA_MATHEMATICA_BRIDGE_ROOT",
            _DEV_ROOT / "tools" / "mathematica-agent-bridge",
        ),
    }
    for name, path in integrations.items():
        add(
            f"integration_{name}",
            path.is_dir(),
            str(path),
            "existing directory",
            required=False,
        )

    required_failures = [
        check["id"]
        for check in checks
        if check["required"] and not check["passed"]
    ]
    return {
        "status": "PASS" if not required_failures else "FAIL",
        "manifest": manifest,
        "checks": checks,
        "required_failures": required_failures,
        "optional_integrations": {
            name: {"path": str(path), "available": path.is_dir()}
            for name, path in integrations.items()
        },
        "scientific_engines": scientific_engines,
    }
