import json

import sympy
from sympy import symbols


x, y = symbols("x y")
implemented = x**3 + 3*x**2*y + 3*x*y**2 + y**3
reference = (x + y)**3
residual = sympy.expand(implemented - reference)
passed = residual == 0
evidence = {
    "residual": str(residual),
    "operation_count": int(sympy.count_ops(implemented)),
    "sympy_version": sympy.__version__,
}
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("VALIDATED" if passed else "REFUTED"))
print("VERDICT: " + ("PASS" if passed else "FAIL"))
