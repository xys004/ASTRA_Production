"""Auditable contract for ASTRA's compact three-model production topology."""
from __future__ import annotations

import os
import shutil
import importlib.util
from pathlib import Path
from typing import Any, Mapping

from core.architecture_configs import architecture_roles


ARCHITECTURE_ID = "astra-compact-three-agent-v2"
CACHE_SCHEMA_VERSION = "3"

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


def production_manifest(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the non-secret configuration that determines one ASTRA cycle."""
    source = os.environ if env is None else env
    full = architecture_roles("full")
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
            full["proposers"][-1],
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
        "architecture_id": ARCHITECTURE_ID,
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
            "required_local_engines": _csv(
                source,
                "ASTRA_REQUIRED_LOCAL_ENGINES",
            ),
        },
        "topology": [
            "parallel_proposals",
            "cross_critique",
            "codex_consensus",
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
    expected = architecture_roles("full")
    expected_roles = {
        "proposers": expected["proposers"],
        "synthesizer": expected["synthesizer"],
        "author": expected["author"],
        "reviewer": expected["reviewer"],
        "analyst": expected["reviewer"],
        "navigator": expected["proposers"][-1],
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
        "production_role_map",
        manifest["roles"] == expected_roles,
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
    expected_effective = {
        "codex_proposer": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "agy_proposer": EXPECTED_PRIMARY_MODELS["agy_cli"],
        "synthesizer": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "author": EXPECTED_PRIMARY_MODELS["claude_cli"],
        "reviewer": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "analyst": EXPECTED_PRIMARY_MODELS["codex_cli"],
        "navigator": EXPECTED_PRIMARY_MODELS["agy_cli"],
    }
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
    add(
        "independent_code_review",
        manifest["controls"]["independent_code_review"],
        manifest["controls"]["independent_code_review"],
        True,
    )
    add(
        "post_cycle_navigation",
        manifest["controls"]["post_cycle_navigation"],
        manifest["controls"]["post_cycle_navigation"],
        True,
    )
    add(
        "validator_repair_vnext",
        manifest["controls"]["validator_repair_vnext"],
        manifest["controls"]["validator_repair_vnext"],
        True,
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
