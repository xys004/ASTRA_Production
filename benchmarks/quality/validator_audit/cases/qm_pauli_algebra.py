"""The Pauli matrices close the su(2) commutator algebra exactly.

CLAIM: for the standard Pauli matrices, [s_i, s_j] = 2i eps_ijk s_k and
{s_i, s_j} = 2 delta_ij I. Together these give s_i s_j = delta_ij I + i eps_ijk s_k,
so the algebra is fixed with no free parameter.

Legs:
  1. exact     -- every one of the 9 ordered pairs is checked as an exact matrix
                  identity over the Gaussian rationals, not to a tolerance;
  2. structure -- hermiticity, tracelessness, unit determinant magnitude and
                  involutivity, which are what force the algebra;
  3. invariant -- the Casimir sum s_x^2 + s_y^2 + s_z^2 = 3I is basis independent
                  and is rechecked after a fixed nontrivial unitary change of basis;
  4. falsifier -- the same test applied to a deliberately wrong s_y rejects it.
"""
import itertools

import sympy as sp

I2 = sp.eye(2)
SX = sp.Matrix([[0, 1], [1, 0]])
SY = sp.Matrix([[0, -sp.I], [sp.I, 0]])
SZ = sp.Matrix([[1, 0], [0, -1]])
SIGMA = {"x": SX, "y": SY, "z": SZ}
ORDER = ("x", "y", "z")

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def levi_civita(a, b, c):
    """Sign of the permutation (a, b, c) of ('x','y','z'), zero if repeated."""
    if len({a, b, c}) < 3:
        return 0
    perm = [ORDER.index(x) for x in (a, b, c)]
    swaps = 0
    for i in range(3):
        for j in range(i + 1, 3):
            if perm[i] > perm[j]:
                swaps += 1
    return 1 if swaps % 2 == 0 else -1


def commutator(a, b):
    return a * b - b * a


def anticommutator(a, b):
    return a * b + b * a


# ---------------------------------------------------------------- leg 1
commutator_ok = True
worst_pair = ""
for a, b in itertools.product(ORDER, repeat=2):
    lhs = commutator(SIGMA[a], SIGMA[b])
    rhs = sp.zeros(2, 2)
    for k in ORDER:
        eps = levi_civita(a, b, k)
        if eps:
            rhs += 2 * sp.I * eps * SIGMA[k]
    residual = sp.simplify(lhs - rhs)
    if residual != sp.zeros(2, 2):
        commutator_ok = False
        worst_pair = f"[{a},{b}] residual={residual.tolist()}"
        break
check("commutator_all_nine_pairs", commutator_ok,
      worst_pair or "exact over Q(i) for every ordered pair")

anticommutator_ok = True
for a, b in itertools.product(ORDER, repeat=2):
    lhs = anticommutator(SIGMA[a], SIGMA[b])
    rhs = 2 * (1 if a == b else 0) * I2
    if sp.simplify(lhs - rhs) != sp.zeros(2, 2):
        anticommutator_ok = False
        worst_pair = f"{{{a},{b}}}"
        break
check("anticommutator_all_nine_pairs", anticommutator_ok,
      worst_pair if not anticommutator_ok else "2*delta_ij*I exactly")

# The product rule is the two identities combined and must follow from them.
product_ok = True
for a, b in itertools.product(ORDER, repeat=2):
    rhs = (1 if a == b else 0) * I2
    for k in ORDER:
        eps = levi_civita(a, b, k)
        if eps:
            rhs += sp.I * eps * SIGMA[k]
    if sp.simplify(SIGMA[a] * SIGMA[b] - rhs) != sp.zeros(2, 2):
        product_ok = False
        break
check("product_rule_follows", product_ok, "s_i s_j = d_ij I + i eps_ijk s_k")


# ---------------------------------------------------------------- leg 2
structure_ok = True
details = []
for name, matrix in SIGMA.items():
    hermitian = sp.simplify(matrix - matrix.conjugate().T) == sp.zeros(2, 2)
    traceless = sp.simplify(sp.trace(matrix)) == 0
    involutive = sp.simplify(matrix * matrix - I2) == sp.zeros(2, 2)
    determinant = sp.simplify(matrix.det())
    if not (hermitian and traceless and involutive and determinant == -1):
        structure_ok = False
        details.append(f"{name} failed")
check("hermitian_traceless_involutive", structure_ok,
      "; ".join(details) or "all three, det = -1 for each")


# ---------------------------------------------------------------- leg 3
casimir = sp.simplify(SX**2 + SY**2 + SZ**2)
check("casimir_is_three_identity", casimir == 3 * I2, f"sum = {casimir.tolist()}")

# Basis independence: conjugating by a fixed nontrivial unitary must preserve
# both the Casimir and the commutator structure.
theta = sp.Rational(1, 3)
U = sp.Matrix([
    [sp.cos(theta), -sp.sin(theta)],
    [sp.sin(theta), sp.cos(theta)],
])
unitary = sp.simplify(U * U.conjugate().T - I2) == sp.zeros(2, 2)
rotated = {k: sp.simplify(U * m * U.conjugate().T) for k, m in SIGMA.items()}
rotated_casimir = sp.simplify(sum((rotated[k] ** 2 for k in ORDER), sp.zeros(2, 2)))
check("casimir_basis_independent", unitary and rotated_casimir == 3 * I2,
      f"unitary={unitary}, rotated Casimir = {rotated_casimir.tolist()}")

rotated_commutator_ok = True
for a, b in itertools.product(ORDER, repeat=2):
    lhs = commutator(rotated[a], rotated[b])
    rhs = sp.zeros(2, 2)
    for k in ORDER:
        eps = levi_civita(a, b, k)
        if eps:
            rhs += 2 * sp.I * eps * rotated[k]
    if sp.simplify(lhs - rhs) != sp.zeros(2, 2):
        rotated_commutator_ok = False
        break
check("algebra_survives_change_of_basis", rotated_commutator_ok,
      "structure constants are invariant as they must be")


# ---------------------------------------------------------------- leg 4
# A wrong s_y must be rejected, otherwise the test proves nothing.
WRONG_SY = sp.Matrix([[0, sp.I], [-sp.I, 0]])   # sign flipped
wrong_lhs = commutator(SX, WRONG_SY)
wrong_rhs = 2 * sp.I * SZ
detected = sp.simplify(wrong_lhs - wrong_rhs) != sp.zeros(2, 2)
check("falsifier_rejects_sign_flipped_sy", detected,
      "the commutator test detects a flipped sign in s_y")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
