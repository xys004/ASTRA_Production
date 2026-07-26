"""Deterministic pre-review checks for generated scientific validators.

The preflight does not decide scientific truth. It catches code patterns that
make the distinction between a refuted conjecture and a broken validator
ambiguous before an expensive model reviewer is called.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import asdict, dataclass
from typing import Any

from core.engine_router import detect_engine


@dataclass(frozen=True)
class PreflightFinding:
    label: str
    severity: str
    message: str
    line: int | None = None
    autofixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _exception_name(handler: ast.ExceptHandler) -> str:
    node = handler.type
    if node is None:
        return "bare"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Tuple):
        return ",".join(
            item.id for item in node.elts if isinstance(item, ast.Name)
        )
    return ast.unparse(node) if hasattr(ast, "unparse") else "unknown"


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    # A leading raise is unambiguous on every handler path. A raise hidden
    # behind a conditional or after a possible return is not sufficient.
    return bool(handler.body and isinstance(handler.body[0], ast.Raise))


def _contains_verdict(node: ast.AST, verdict: str | None = None) -> bool:
    needle = f"VERDICT: {verdict}".upper() if verdict else "VERDICT:"
    return any(
        isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and needle in item.value.upper()
        for item in ast.walk(node)
    )


def _enclosing_scope(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.AST | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(
            current,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
        ):
            return current
        current = parents.get(current)
    return None


def _handler_can_contaminate_verdict(
    handler: ast.ExceptHandler,
    *,
    parents: dict[ast.AST, ast.AST],
    verdict_fail_present: bool,
) -> bool:
    """Conservatively identify exception-to-verdict conversion.

    A module-level broad handler can affect any later verdict, so it remains a
    release blocker. Inside a helper, ordinary retry/skip handlers are allowed;
    only a direct verdict emission or a boolean/sentinel return is blocking.
    This avoids forcing expensive model repairs for legitimate bootstrap
    non-convergence loops while preserving the security regression cases.
    """
    if not verdict_fail_present:
        return False
    if _contains_verdict(handler):
        return True
    if _enclosing_scope(handler, parents) is None:
        return True
    for node in ast.walk(handler):
        if isinstance(node, ast.Return):
            value = node.value
            if value is None:
                return True
            if isinstance(value, ast.Constant) and value.value in {
                None,
                True,
                False,
                0,
                1,
            }:
                return True
    return False


def _unknown_as_nonzero(node: ast.Compare) -> bool:
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left = node.left
    right = node.comparators[0]
    if not isinstance(left, ast.Attribute) or left.attr != "is_zero":
        return False
    is_true = isinstance(right, ast.Constant) and right.value is True
    return is_true and isinstance(node.ops[0], (ast.IsNot, ast.NotEq))


def audit_validation_code(code: str) -> dict[str, Any]:
    findings: list[PreflightFinding] = []
    engine = detect_engine(code or "")
    if engine != "python":
        return {
            "status": "APPROVED",
            "engine": engine,
            "findings": [],
            "critical_count": 0,
            "warning_count": 0,
        }
    try:
        tree = ast.parse(code or "")
    except SyntaxError as exc:
        finding = PreflightFinding(
            label="syntax_error",
            severity="critical",
            message=f"Python syntax error: {exc.msg}",
            line=exc.lineno,
            autofixable=False,
        )
        return {
            "status": "REVISE",
            "engine": engine,
            "findings": [finding.to_dict()],
            "critical_count": 1,
            "warning_count": 0,
        }

    verdict_fail_present = "VERDICT: FAIL" in (code or "").upper()
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            name = _exception_name(node)
            broad = name in {"bare", "Exception", "BaseException"} or any(
                item in {"Exception", "BaseException"}
                for item in name.split(",")
            )
            if (
                broad
                and not _handler_reraises(node)
                and _handler_can_contaminate_verdict(
                    node,
                    parents=parents,
                    verdict_fail_present=verdict_fail_present,
                )
            ):
                findings.append(
                    PreflightFinding(
                        label="swallowed_exception",
                        severity="critical",
                        line=getattr(node, "lineno", None),
                        autofixable=bool(
                            node.body
                            and getattr(node.body[0], "lineno", node.lineno)
                            > node.lineno
                        ),
                        message=(
                            f"{name} is caught without re-raising while the script "
                            "can emit VERDICT: FAIL. Dependency/API failure could be "
                            "misreported as scientific refutation."
                        ),
                    )
                )
        elif isinstance(node, ast.Compare) and _unknown_as_nonzero(node):
            findings.append(
                PreflightFinding(
                    label="unknown_as_pass",
                    severity="critical",
                    line=getattr(node, "lineno", None),
                    autofixable=True,
                    message=(
                        "`.is_zero is not True` treats an indeterminate symbolic "
                        "result as proof of nonzeroness. Require an exact expression "
                        "or an explicit domain-aware nonzero check."
                    ),
                )
            )

    # Stable de-duplication keeps repair prompts compact.
    unique: dict[tuple[str, int | None, str], PreflightFinding] = {}
    for finding in findings:
        unique[(finding.label, finding.line, finding.message)] = finding
    ordered = sorted(
        unique.values(),
        key=lambda item: (item.line is None, item.line or 0, item.label),
    )
    critical = sum(item.severity == "critical" for item in ordered)
    warnings = len(ordered) - critical
    return {
        "status": "REVISE" if critical else "APPROVED",
        "engine": engine,
        "findings": [item.to_dict() for item in ordered],
        "critical_count": critical,
        "warning_count": warnings,
    }


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for match in re.finditer(r"\n", text):
        offsets.append(match.end())
    return offsets


def _absolute_offset(
    offsets: list[int],
    line: int,
    column: int,
    text_length: int,
) -> int:
    if line <= 0 or line > len(offsets):
        return text_length
    return min(offsets[line - 1] + column, text_length)


def repair_validation_code(
    code: str,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply only semantics-preserving, deterministic validator repairs.

    The function never invents scientific checks. It changes an indeterminate
    SymPy predicate into an explicit ``is False`` test and makes a dangerous
    broad exception operational by re-raising it. Edits are source-local so
    comments, formatting, and unrelated validation legs remain intact.
    """
    audit = audit or audit_validation_code(code)
    if audit.get("engine", "python") != "python":
        return {"code": code, "changed": False, "repairs": []}
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return {"code": code, "changed": False, "repairs": []}

    target_lines = {
        (str(item.get("label") or ""), item.get("line"))
        for item in audit.get("findings") or []
        if item.get("autofixable")
    }
    offsets = _line_offsets(code)
    edits: list[tuple[int, int, str, dict[str, Any]]] = []

    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if isinstance(node, ast.Compare) and ("unknown_as_pass", line) in target_lines:
            start = _absolute_offset(offsets, node.lineno, node.col_offset, len(code))
            end = _absolute_offset(
                offsets,
                node.end_lineno,
                node.end_col_offset,
                len(code),
            )
            original = code[start:end]
            replacement = re.sub(
                r"\.is_zero\s+(?:is\s+not|!=)\s+True\b",
                ".is_zero is False",
                original,
                count=1,
            )
            if replacement != original:
                edits.append(
                    (
                        start,
                        end,
                        replacement,
                        {
                            "label": "unknown_as_pass",
                            "line": line,
                            "description": (
                                "Require an explicit SymPy false result; "
                                "indeterminate None no longer passes."
                            ),
                        },
                    )
                )
        elif (
            isinstance(node, ast.ExceptHandler)
            and ("swallowed_exception", line) in target_lines
            and node.body
            and node.body[0].lineno > node.lineno
        ):
            first = node.body[0]
            insertion = _absolute_offset(
                offsets,
                first.lineno,
                0,
                len(code),
            )
            source_line = code.splitlines(keepends=True)[first.lineno - 1]
            indent = source_line[: len(source_line) - len(source_line.lstrip())]
            edits.append(
                (
                    insertion,
                    insertion,
                    f"{indent}raise  # ASTRA vNext.1: operational failure\n",
                    {
                        "label": "swallowed_exception",
                        "line": line,
                        "description": (
                            "Re-raise the operational exception before it can "
                            "alter the scientific verdict."
                        ),
                    },
                )
            )

    repaired = code
    repairs: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, replacement, record in sorted(
        edits,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    ):
        if any(not (end <= low or start >= high) for low, high in occupied):
            continue
        repaired = repaired[:start] + replacement + repaired[end:]
        occupied.append((start, end))
        repairs.append(record)
    repairs.reverse()
    return {
        "code": repaired,
        "changed": repaired != code,
        "repairs": repairs,
    }


def smoke_validation_code(code: str) -> dict[str, Any]:
    """Cheap, non-executing compile and dependency-availability smoke check."""
    engine = detect_engine(code or "")
    if engine != "python":
        return {
            "status": "APPROVED",
            "engine": engine,
            "compiled": None,
            "missing_modules": [],
            "runtime_checks": [
                f"{engine} syntax and dependencies must be checked by its oracle."
            ],
        }
    try:
        tree = ast.parse(code or "")
        compile(tree, "<astra-validator>", "exec")
    except SyntaxError as exc:
        return {
            "status": "REVISE",
            "engine": engine,
            "compiled": False,
            "missing_modules": [],
            "runtime_checks": [],
            "reason": f"Python compile failed at line {exc.lineno}: {exc.msg}",
        }

    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.append(node.module.split(".", 1)[0])
    missing: list[str] = []
    for root in dict.fromkeys(roots):
        try:
            if importlib.util.find_spec(root) is None:
                missing.append(root)
        except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
            missing.append(root)
    return {
        "status": "APPROVED",
        "engine": engine,
        "compiled": True,
        "missing_modules": missing,
        "runtime_checks": [
            (
                f"Module `{module}` was not discoverable in the review environment; "
                "the selected local/remote oracle must confirm availability."
            )
            for module in missing
        ],
        "line_count": len((code or "").splitlines()),
        "character_count": len(code or ""),
    }


def preflight_as_review(audit: dict[str, Any]) -> dict[str, Any]:
    findings = list(audit.get("findings") or [])
    messages = [
        (
            f"line {item.get('line')}: {item.get('message')}"
            if item.get("line")
            else str(item.get("message") or "")
        )
        for item in findings
    ]
    labels = list(
        dict.fromkeys(str(item.get("label") or "") for item in findings)
    )
    return {
        "status": "REVISE",
        "reasoning": "Deterministic validator preflight found blocking defects.",
        "revision_instructions": (
            "Patch only the listed defects while preserving all sound validation "
            "legs. Operational failures must raise or exit nonzero and must never "
            "be converted to VERDICT: FAIL.\n- "
            + "\n- ".join(messages)
        )[:3000],
        "coverage": [],
        "defect_labels": labels,
        "source": "deterministic_preflight",
        "runtime_checks": [],
    }
