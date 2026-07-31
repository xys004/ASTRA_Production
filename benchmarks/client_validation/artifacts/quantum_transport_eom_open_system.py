import json
import os
import subprocess
from pathlib import Path


project = Path(
    os.environ["ASTRA_QUANTUM_TRANSPORT_EOM_ROOT"]
).resolve()
python = Path(
    os.environ["ASTRA_QUANTUM_TRANSPORT_EOM_PYTHON"]
).resolve()

inner_code = r"""
import json
from importlib import metadata

import numpy as np
import quantum_transport
from quantum_transport import LeadSelfEnergy, MatrixDevice


grid = np.linspace(-12.0, 12.0, 4001)
eps, gamma_left, gamma_right = 0.35, 0.4, 0.7
single = MatrixDevice(
    hamiltonian=np.array([[eps]], dtype=complex),
    basis_labels=["dot"],
)
left = LeadSelfEnergy.wide_band(
    np.array([[gamma_left]], dtype=complex),
    mu=0.0,
)
right = LeadSelfEnergy.wide_band(
    np.array([[gamma_right]], dtype=complex),
    mu=0.0,
)
view = single.transport(left, right)
transmission = view.transmission_values(grid)
analytic = (
    gamma_left
    * gamma_right
    / (
        (grid - eps) ** 2
        + ((gamma_left + gamma_right) / 2.0) ** 2
    )
)
lorentzian_error = float(
    np.max(np.abs(transmission - analytic))
)
equilibrium_current = abs(
    float(view.meir_wingreen_current(grid, lead="left"))
)

biased_device = MatrixDevice(
    hamiltonian=np.array(
        [[0.2, 1.0], [1.0, -0.3]],
        dtype=complex,
    ),
    basis_labels=["a", "b"],
)
biased_left = LeadSelfEnergy.wide_band(
    np.diag([0.6, 0.0]).astype(complex),
    mu=0.8,
    temperature=0.05,
)
biased_right = LeadSelfEnergy.wide_band(
    np.diag([0.0, 0.4]).astype(complex),
    mu=-0.8,
    temperature=0.05,
)
biased = biased_device.transport(biased_left, biased_right)
current_left = biased.meir_wingreen_current(grid, lead="left")
current_right = biased.meir_wingreen_current(grid, lead="right")
conservation_error = abs(float(current_left + current_right))

fdt_grid = np.linspace(-4.0, 4.0, 41)
fdt_device = MatrixDevice(
    hamiltonian=np.array([[0.2]], dtype=complex),
    basis_labels=["dot"],
)
fdt_left = LeadSelfEnergy.wide_band(
    np.array([[0.4]], dtype=complex),
    mu=0.1,
    temperature=0.3,
)
fdt_right = LeadSelfEnergy.wide_band(
    np.array([[0.4]], dtype=complex),
    mu=0.1,
    temperature=0.3,
)
fdt_view = fdt_device.transport(fdt_left, fdt_right)
lesser = fdt_view.lesser_values(fdt_grid)[:, 0, 0]
retarded = fdt_view.retarded_values(fdt_grid)[:, 0, 0]
occupation = 1.0 / (
    np.exp((fdt_grid - 0.1) / 0.3) + 1.0
)
fdt_expected = -occupation * (
    retarded - np.conjugate(retarded)
)
fdt_error = float(np.max(np.abs(lesser - fdt_expected)))

print(json.dumps({
    "package_version": metadata.version(
        "quantum-transport-eom"
    ),
    "module_path": str(quantum_transport.__file__),
    "lorentzian_max_abs_error": lorentzian_error,
    "equilibrium_current_abs": equilibrium_current,
    "current_conservation_error": conservation_error,
    "fdt_max_abs_error": fdt_error,
}, sort_keys=True))
"""

environment = os.environ.copy()
source_path = str(project / "src")
environment["PYTHONPATH"] = (
    source_path
    + os.pathsep
    + environment.get("PYTHONPATH", "")
)
result = subprocess.run(
    [str(python), "-c", inner_code],
    cwd=str(project),
    env=environment,
    capture_output=True,
    text=True,
    timeout=120,
)
if result.returncode != 0:
    raise RuntimeError(result.stderr or result.stdout)
lines = [line for line in result.stdout.splitlines() if line.strip()]
evidence = json.loads(lines[-1])
commit = subprocess.run(
    ["git", "-C", str(project), "rev-parse", "HEAD"],
    capture_output=True,
    text=True,
    timeout=10,
).stdout.strip()
evidence["quantum_transport_commit"] = commit
passed = (
    evidence["package_version"] == "0.3.0"
    and evidence["lorentzian_max_abs_error"] < 1e-11
    and evidence["equilibrium_current_abs"] < 1e-12
    and evidence["current_conservation_error"] < 1e-8
    and evidence["fdt_max_abs_error"] < 1e-11
    and bool(commit)
)
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("VALIDATED" if passed else "REFUTED"))
print("VERDICT: " + ("PASS" if passed else "FAIL"))
