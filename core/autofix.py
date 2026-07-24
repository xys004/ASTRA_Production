"""
Arreglos MECANICOS deterministas para los errores tipicos de scripts generados
por LLMs — gratis (cero llamadas a modelo, cero cuota).

La economia del retry: cuando el error es mecanico (falta un import, backend
grafico, unicode de la consola Windows), pedirle la correccion a un modelo
quema una llamada entera para anadir una linea obvia. Este modulo resuelve
esos casos en microsegundos; el traductor solo se paga cuando el error es
matematico de verdad.
"""
from __future__ import annotations

import re

# alias/modulo -> import que lo repara (solo librerias YA presentes en el venv)
_ALIAS_IMPORTS = {
    "sp": "import sympy as sp",
    "sym": "import sympy as sym",
    "np": "import numpy as np",
    "plt": "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt",
    "sympy": "import sympy",
    "numpy": "import numpy",
    "scipy": "import scipy",
    "z3": "import z3",
    "math": "import math",
    "cmath": "import cmath",
    "random": "import random",
    "itertools": "import itertools",
    "json": "import json",
    "re": "import re",
}


def try_autofix(code: str, stderr: str):
    """Devuelve el codigo con el arreglo mecanico prepende-ado, o None si el
    error no es de los reparables (y toca pagar una correccion del traductor)."""
    if not code or not stderr:
        return None
    fixes = []

    m = re.search(r"NameError: name '(\w+)' is not defined", stderr)
    if m and m.group(1) in _ALIAS_IMPORTS:
        imp = _ALIAS_IMPORTS[m.group(1)]
        if imp.splitlines()[-1] not in code:
            fixes.append(imp)

    if "UnicodeEncodeError" in stderr and "reconfigure" not in code:
        fixes.append(
            "import sys\n"
            "try:\n"
            "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
            "except Exception:\n"
            "    pass")

    if (re.search(r"_tkinter|no display|TclError|Matplotlib is currently using", stderr, re.I)
            and "matplotlib" in code and "matplotlib.use" not in code):
        fixes.append("import matplotlib\nmatplotlib.use('Agg')")

    if not fixes:
        return None
    return "\n".join(fixes) + "\n" + code
