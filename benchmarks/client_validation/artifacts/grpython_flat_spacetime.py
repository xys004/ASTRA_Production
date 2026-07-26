import json
import os
import subprocess
import sys
from pathlib import Path

import sympy as sp


project = Path(os.environ["ASTRA_GR_PYTHON_ROOT"]).resolve()
sys.path.insert(0, str(project))
from gr_tensors import (  # noqa: E402
    compute_christoffel,
    compute_ricci,
    compute_ricci_scalar,
    compute_riemann,
)


t, r, theta, phi = sp.symbols("t r theta phi", real=True)
coordinates = [t, r, theta, phi]
metric = sp.diag(-1, 1, r**2, r**2 * sp.sin(theta)**2)
inverse = sp.simplify(metric.inv())
christoffel = compute_christoffel(metric, inverse, coordinates)
riemann = compute_riemann(christoffel, coordinates)
ricci = compute_ricci(riemann)
ricci_scalar = sp.simplify(compute_ricci_scalar(ricci, inverse))

nonzero_christoffel = sum(
    sp.simplify(christoffel[a][b][c]) != 0
    for a in range(4)
    for b in range(4)
    for c in range(4)
)
nonzero_riemann = sum(
    sp.simplify(riemann[a][b][c][d]) != 0
    for a in range(4)
    for b in range(4)
    for c in range(4)
    for d in range(4)
)
nonzero_ricci = sum(
    sp.simplify(ricci[a, b]) != 0
    for a in range(4)
    for b in range(4)
)
commit = subprocess.run(
    ["git", "-C", str(project), "rev-parse", "HEAD"],
    capture_output=True,
    text=True,
    timeout=10,
).stdout.strip()
passed = (
    nonzero_christoffel > 0
    and nonzero_riemann == 0
    and nonzero_ricci == 0
    and ricci_scalar == 0
)
evidence = {
    "nonzero_christoffel": nonzero_christoffel,
    "nonzero_riemann": nonzero_riemann,
    "nonzero_ricci": nonzero_ricci,
    "ricci_scalar": str(ricci_scalar),
    "gr_python_commit": commit,
}
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("VALIDATED" if passed else "REFUTED"))
print("VERDICT: " + ("PASS" if passed else "FAIL"))
