import json

import z3


workload_a = z3.Int("workload_a")
workload_b = z3.Int("workload_b")
solver = z3.Solver()
solver.add(workload_a >= 6, workload_b >= 5, workload_a + workload_b <= 10)
result = solver.check()
refuted = result == z3.unsat
evidence = {
    "solver_result": str(result),
    "minimum_required": 11,
    "available_capacity": 10,
    "z3_version": z3.get_version_string(),
}
print("ASTRA_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))
print("CLAIM_VERDICT: " + ("REFUTED" if refuted else "VALIDATED"))
print("VERDICT: " + ("PASS" if refuted else "FAIL"))
