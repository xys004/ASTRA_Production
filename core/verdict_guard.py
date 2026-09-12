"""
Guardas DETERMINISTAS sobre el veredicto — cero LLM, cero cuota.

El modo de fallo clasico de un traductor debil es el PASS trivial:
`print("VERDICT: PASS")` incondicional al final de un script que no puede
fallar. Este auditor examina el AST del script + su stdout y decide si un
PASS es CREIBLE. La filosofia de ASTRA: la confianza no viene del modelo,
viene de la estructura; este modulo es esa estructura para el veredicto.

Criterios de sospecha (solo se audita cuando el stdout dice VERDICT: PASS):
  * el script no contiene NINGUNA constante de texto con "FAIL"
    -> no existe camino que imprima un fallo: el PASS era inevitable;
  * cero `assert` y cero comparaciones en el AST
    -> no se verifico nada antes de declarar PASS;
  * el protocolo de sub-checks (lineas `CHECK <nombre>: OK|FAIL`) muestra
    algun FAIL pero el veredicto final dice PASS -> contradiccion.

Scripts de motores externos (sage/maxima/cadabra) no son Python parseable:
se les salta la auditoria de AST (el conteo de CHECKs del stdout si aplica).
"""
from __future__ import annotations

import ast
import re

# Acepta anotacion tras el marcador: "CHECK nombre: OK  (residuo=1e-14)" —
# los traductores anaden evidencia al final de la linea (visto en produccion).
_CHECK_LINE = re.compile(r"(?im)^\s*CHECK\b[^\n]*?:\s*(OK|PASS|FAIL)\b")


def _string_constants(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def assess_verdict(code: str, exec_result: dict) -> dict:
    """Audita un resultado de ejecucion. Devuelve un dict con
    verdict_suspect (bool), reasons (list[str]) y metricas informativas."""
    stdout = (exec_result or {}).get("stdout") or ""
    up = stdout.upper()
    marks = [m.upper() for m in _CHECK_LINE.findall(stdout)]
    n_ok = sum(1 for m in marks if m in ("OK", "PASS"))
    n_fail = len(marks) - n_ok
    out = {
        "verdict_suspect": False,
        "reasons": [],
        "checks_total": len(marks),
        "checks_ok": n_ok,
        "checks_fail": n_fail,
        "asserts": 0,
        "comparisons": 0,
    }

    if "VERDICT: PASS" not in up:
        return out          # FAIL/NONE ya son resultados honestos: nada que auditar

    if n_fail:
        out["verdict_suspect"] = True
        out["reasons"].append(
            f"contradiccion: {n_fail} CHECK en FAIL pero el veredicto final dice PASS")

    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return out          # sage/maxima/cadabra: sin auditoria de AST

    out["asserts"] = sum(isinstance(n, ast.Assert) for n in ast.walk(tree))
    out["comparisons"] = sum(isinstance(n, ast.Compare) for n in ast.walk(tree))

    if not any("FAIL" in s for s in _string_constants(tree)):
        out["verdict_suspect"] = True
        out["reasons"].append(
            "el script no contiene ningun camino que imprima FAIL "
            "(PASS incondicional: no podia fallar)")

    if out["asserts"] == 0 and out["comparisons"] == 0:
        out["verdict_suspect"] = True
        out["reasons"].append(
            "cero asserts y cero comparaciones en el AST: "
            "no se verifico nada antes de declarar PASS")

    return out
