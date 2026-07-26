import json

import pint


units = pint.UnitRegistry()
viscosity = 1.0e-3 * units.pascal * units.second
length = 10.0 * units.meter
velocity = 0.2 * units.meter / units.second
radius = 0.05 * units.meter


def pressure_drop(r):
    return 8 * viscosity * length * velocity / r**2


base = pressure_drop(radius).to(units.pascal)
doubled = pressure_drop(2 * radius).to(units.pascal)
ratio = float((doubled / base).to_base_units().magnitude)
dimension_ok = base.dimensionality == units.pascal.dimensionality
passed = dimension_ok and abs(ratio - 0.25) < 1e-12
evidence = {
    "pressure_pa": float(base.magnitude),
    "double_radius_ratio": ratio,
    "dimensionality": str(base.dimensionality),
    "pint_version": pint.__version__,
}
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("VALIDATED" if passed else "REFUTED"))
print("VERDICT: " + ("PASS" if passed else "FAIL"))
