import json

import numpy as np
import scipy
from scipy.integrate import solve_ivp


tau = 2.0
times = np.linspace(0.0, 10.0, 201)
solution = solve_ivp(
    lambda _t, y: [(1.0 - y[0]) / tau],
    (times[0], times[-1]),
    [0.0],
    t_eval=times,
    rtol=1e-11,
    atol=1e-13,
)
numeric = solution.y[0]
analytic = 1.0 - np.exp(-times / tau)
max_abs_error = float(np.max(np.abs(numeric - analytic)))
analytic_derivative = np.exp(-times / tau) / tau
ode_residual = float(
    np.max(np.abs(analytic_derivative - (1.0 - analytic) / tau))
)
monotone = bool(np.all(np.diff(numeric) >= -1e-12))
bounded = bool(np.all((numeric >= -1e-12) & (numeric <= 1.0 + 1e-12)))
passed = (
    solution.success
    and max_abs_error < 1e-8
    and ode_residual < 1e-12
    and monotone
    and bounded
)
evidence = {
    "max_abs_error": max_abs_error,
    "ode_residual": ode_residual,
    "monotone": monotone,
    "bounded": bounded,
    "scipy_version": scipy.__version__,
}
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("VALIDATED" if passed else "REFUTED"))
print("VERDICT: " + ("PASS" if passed else "FAIL"))
