"""Client-facing validator routing and auditable evidence bundles."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
CLIENT_CASE_ROOT = ROOT / "benchmarks" / "client_validation"
_EVIDENCE_LINE = re.compile(r"(?m)^ASTRA_EVIDENCE_JSON=(\{.*\})\s*$")
_CLAIM_LINE = re.compile(
    r"(?m)^CLAIM_VERDICT:\s*(VALIDATED|REFUTED|INCONCLUSIVE)\s*$",
    re.IGNORECASE,
)
_EXECUTION_LINE = re.compile(r"(?m)^VERDICT:\s*(PASS|FAIL)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatorRoute:
    primary: str
    alternatives: tuple[str, ...]
    rationale: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "alternatives": list(self.alternatives),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ClientValidationCase:
    id: str
    application: str
    demonstration: str
    objective: str
    claim: str
    expected_claim_verdict: str
    artifact_kind: str
    artifact_path: Path
    supported_oracles: tuple[str, ...]
    preferred_validators: tuple[str, ...]
    required_evidence: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    adapter: str
    optional: bool
    path: Path

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "application": self.application,
            "demonstration": self.demonstration,
            "objective": self.objective,
            "claim": self.claim,
            "expected_claim_verdict": self.expected_claim_verdict,
            "artifact_kind": self.artifact_kind,
            "artifact_path": str(self.artifact_path.relative_to(ROOT)),
            "supported_oracles": list(self.supported_oracles),
            "preferred_validators": list(self.preferred_validators),
            "required_evidence": list(self.required_evidence),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "adapter": self.adapter or None,
            "optional": self.optional,
        }


def route_validator(case: ClientValidationCase) -> ValidatorRoute:
    mapping = {
        "formal_proof": (
            "lean4",
            ("manual_formal_review",),
            "A kernel-checked proof is the decisive validator for a formal invariant.",
        ),
        "logical_constraints": (
            "z3_python",
            ("lean4", "manual_policy_review"),
            "SMT satisfiability gives a deterministic feasibility or counterexample certificate.",
        ),
        "symbolic_algebra": (
            "sympy_python",
            ("wolfram_bridge", "sage"),
            "Exact symbolic residual reduction is primary; an independent CAS is a useful cross-check.",
        ),
        "numerical_simulation": (
            "scipy_python",
            ("wolfram_bridge", "domain_simulator"),
            "A numerical residual, tolerance and invariant checks are required together.",
        ),
        "dimensional_analysis": (
            "pint_python",
            ("wolfram_bridge", "manual_units_audit"),
            "Unit dimensionality and scaling ratios are checked independently of prose.",
        ),
        "project_package": (
            "project_python",
            ("sympy_python", "wolfram_bridge"),
            "The package is exercised through its public scientific functions and audited by invariants.",
        ),
    }
    try:
        primary, alternatives, rationale = mapping[case.artifact_kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported client artifact kind: {case.artifact_kind}") from exc
    return ValidatorRoute(primary, alternatives, rationale)


def _read_case(path: Path) -> ClientValidationCase:
    data = json.loads(path.read_text(encoding="utf-8"))
    artifact = (path.parent / data["artifact_path"]).resolve()
    allowed_root = CLIENT_CASE_ROOT.resolve()
    if artifact != allowed_root and allowed_root not in artifact.parents:
        raise ValueError(f"Artifact escapes client benchmark root: {artifact}")
    if not artifact.is_file():
        raise ValueError(f"Missing client validation artifact: {artifact}")
    expected = str(data["expected_claim_verdict"]).upper()
    if expected not in {"VALIDATED", "REFUTED", "INCONCLUSIVE"}:
        raise ValueError(f"Invalid expected claim verdict in {path}: {expected}")
    supported = tuple(str(item).lower() for item in data["supported_oracles"])
    if not supported or any(item not in {"local", "astrum"} for item in supported):
        raise ValueError(f"Invalid supported_oracles in {path}")
    return ClientValidationCase(
        id=data["id"],
        application=data["application"],
        demonstration=data.get("demonstration", ""),
        objective=data["objective"],
        claim=data["claim"],
        expected_claim_verdict=expected,
        artifact_kind=data["artifact_kind"],
        artifact_path=artifact,
        supported_oracles=supported,
        preferred_validators=tuple(data.get("preferred_validators") or []),
        required_evidence=tuple(data.get("required_evidence") or []),
        assumptions=tuple(data.get("assumptions") or []),
        limitations=tuple(data.get("limitations") or []),
        adapter=data.get("adapter", ""),
        optional=bool(data.get("optional", False)),
        path=path,
    )


def load_client_validation_cases(
    root: Path = CLIENT_CASE_ROOT,
    *,
    include_optional: bool = False,
) -> list[ClientValidationCase]:
    cases = [_read_case(path) for path in sorted(root.glob("*.json"))]
    if not include_optional:
        cases = [case for case in cases if not case.optional]
    ids = [case.id for case in cases]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"Duplicate client validation case ids: {duplicates}")
    return cases


def select_oracles(case: ClientValidationCase, requested: str) -> list[str]:
    requested = requested.lower()
    if requested == "both":
        return list(case.supported_oracles)
    if requested == "auto":
        return ["astrum" if "astrum" in case.supported_oracles else case.supported_oracles[0]]
    if requested not in {"local", "astrum"}:
        raise ValueError(f"Unknown client validation oracle: {requested}")
    return [requested] if requested in case.supported_oracles else []


def _git_commit(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _resolve_adapter(name: str) -> dict[str, Any]:
    if not name:
        return {}
    if name == "gr_python":
        configured = os.environ.get("ASTRA_GR_PYTHON_ROOT", "").strip()
        path = Path(configured).expanduser() if configured else ROOT.parent / "gr" / "GR_python"
        path = path.resolve()
        return {
            "name": "gr_python",
            "ready": path.is_dir(),
            "path": str(path),
            "git_commit": _git_commit(path) if path.is_dir() else "",
            "env_var": "ASTRA_GR_PYTHON_ROOT",
        }
    if name == "quantum_transport_eom":
        configured = os.environ.get(
            "ASTRA_QUANTUM_TRANSPORT_EOM_ROOT", ""
        ).strip()
        path = (
            Path(configured).expanduser()
            if configured
            else ROOT.parent / "quantum" / "QuantumTransportEOM"
        ).resolve()
        configured_python = os.environ.get(
            "ASTRA_QUANTUM_TRANSPORT_EOM_PYTHON", ""
        ).strip()
        python_candidates = []
        if configured_python:
            python_candidates.append(
                Path(configured_python).expanduser()
            )
        if sys.version_info >= (3, 10):
            python_candidates.append(Path(sys.executable))
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            python_root = Path(local_app_data) / "Programs" / "Python"
            if python_root.is_dir():
                python_candidates.extend(
                    sorted(
                        python_root.glob("Python3*/python.exe"),
                        reverse=True,
                    )
                )
        python_path = next(
            (
                candidate.resolve()
                for candidate in python_candidates
                if candidate.is_file()
            ),
            None,
        )
        ready = (
            path.is_dir()
            and (path / "src" / "quantum_transport").is_dir()
            and python_path is not None
        )
        return {
            "name": "quantum_transport_eom",
            "ready": ready,
            "path": str(path),
            "python": str(python_path) if python_path else "",
            "git_commit": _git_commit(path) if path.is_dir() else "",
            "env_var": "ASTRA_QUANTUM_TRANSPORT_EOM_ROOT",
            "python_env_var": "ASTRA_QUANTUM_TRANSPORT_EOM_PYTHON",
            "error": (
                ""
                if ready
                else "QuantumTransportEOM or a Python >=3.10 interpreter is unavailable"
            ),
        }
    return {"name": name, "ready": False, "error": "Unknown project adapter"}


@contextmanager
def _execution_environment(oracle: str, adapter: dict[str, Any]) -> Iterator[None]:
    updates = {"ASTRA_ORACLE_MODE": "remote" if oracle == "astrum" else "local"}
    if adapter.get("name") == "gr_python" and adapter.get("ready"):
        updates["ASTRA_GR_PYTHON_ROOT"] = adapter["path"]
    if (
        adapter.get("name") == "quantum_transport_eom"
        and adapter.get("ready")
    ):
        updates["ASTRA_QUANTUM_TRANSPORT_EOM_ROOT"] = adapter["path"]
        updates["ASTRA_QUANTUM_TRANSPORT_EOM_PYTHON"] = adapter["python"]
    previous = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _parse_execution(stdout: str) -> tuple[str, str, dict[str, Any], list[str]]:
    errors = []
    execution_match = _EXECUTION_LINE.search(stdout or "")
    claim_match = _CLAIM_LINE.search(stdout or "")
    evidence_match = _EVIDENCE_LINE.search(stdout or "")
    execution_verdict = execution_match.group(1).upper() if execution_match else "MISSING"
    claim_verdict = claim_match.group(1).upper() if claim_match else "INCONCLUSIVE"
    evidence: dict[str, Any] = {}
    if not execution_match:
        errors.append("Missing VERDICT: PASS|FAIL line")
    if not claim_match:
        errors.append("Missing CLAIM_VERDICT line")
    if evidence_match:
        try:
            evidence = json.loads(evidence_match.group(1))
        except json.JSONDecodeError:
            errors.append("ASTRA_EVIDENCE_JSON is not valid JSON")
    else:
        errors.append("Missing ASTRA_EVIDENCE_JSON line")
    return execution_verdict, claim_verdict, evidence, errors


async def run_client_validation_case(
    case: ClientValidationCase,
    *,
    oracle: str,
    timeout: int = 300,
) -> dict[str, Any]:
    route = route_validator(case)
    artifact = case.artifact_path.read_text(encoding="utf-8")
    artifact_hash = hashlib.sha256(artifact.encode("utf-8")).hexdigest()
    adapter = _resolve_adapter(case.adapter)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()

    if adapter and not adapter.get("ready"):
        raw = {
            "status": "UNAVAILABLE",
            "stdout": "",
            "stderr": adapter.get("error") or f"Missing project adapter: {adapter.get('path')}",
            "exit_code": -2,
            "engine": route.primary,
            "oracle": oracle,
        }
    elif route.primary == "lean4":
        from core.formal_validators import evaluate_lean4_source

        raw = await evaluate_lean4_source(artifact, oracle=oracle, timeout=timeout)
    else:
        from core.executor import execute_python_code

        with _execution_environment(oracle, adapter):
            raw = await execute_python_code(
                artifact,
                workspace_dir=str(ROOT / "workspace" / "client_validation"),
                timeout=timeout,
            )
        raw.setdefault("status", "PASS" if int(raw.get("exit_code", -1)) == 0 else "FAIL")
        raw.setdefault("engine", route.primary)
        raw.setdefault("oracle", oracle)

    stdout = str(raw.get("stdout") or "")
    if route.primary == "lean4":
        execution_verdict = "PASS" if raw.get("status") == "PASS" else "FAIL"
        claim_verdict = "VALIDATED" if raw.get("status") == "PASS" else "INCONCLUSIVE"
        evidence = {
            "kernel_checked": raw.get("status") == "PASS",
            "lean_version": raw.get("lean_version"),
            "mathlib_commit": raw.get("mathlib_commit"),
            "theorem_source_sha256": artifact_hash,
        }
        parse_errors: list[str] = []
    else:
        execution_verdict, claim_verdict, evidence, parse_errors = _parse_execution(stdout)

    missing_evidence = sorted(
        key for key in case.required_evidence if key not in evidence
    )
    if missing_evidence:
        parse_errors.append("Missing evidence keys: " + ", ".join(missing_evidence))

    executable_ok = (
        raw.get("status") == "PASS"
        and int(raw.get("exit_code", -1)) == 0
        and execution_verdict == "PASS"
        and not parse_errors
    )
    expected_match = claim_verdict == case.expected_claim_verdict
    validation_status = (
        "PASS" if executable_ok and expected_match
        else "UNAVAILABLE" if raw.get("status") == "UNAVAILABLE"
        else "FAIL"
    )
    duration = round(time.perf_counter() - started, 6)
    command_oracle = "astrum" if oracle == "astrum" else "local"

    return {
        "schema_version": "1.0",
        "bundle_id": f"{case.id}:{oracle}:{artifact_hash[:12]}",
        "created_at": started_at,
        "case": case.public_dict(),
        "route": route.public_dict(),
        "artifact": {
            "path": str(case.artifact_path.relative_to(ROOT)),
            "sha256": artifact_hash,
            "bytes": len(artifact.encode("utf-8")),
        },
        "adapter": adapter or None,
        "validation": {
            "status": validation_status,
            "execution_verdict": execution_verdict,
            "claim_verdict": claim_verdict,
            "expected_claim_verdict": case.expected_claim_verdict,
            "expected_match": expected_match,
            "oracle": oracle,
            "duration_s": duration,
            "errors": parse_errors,
        },
        "evidence": evidence,
        "raw": {
            key: value
            for key, value in raw.items()
            if key not in {"stdout", "stderr"}
        },
        "stdout": stdout[-12000:],
        "stderr": str(raw.get("stderr") or "")[-8000:],
        "provenance": {
            "astra_git_commit": _git_commit(ROOT),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "reproduce": (
                f"python scripts/run_client_validation.py --only {case.id} "
                f"--oracle {command_oracle}"
            ),
        },
    }
