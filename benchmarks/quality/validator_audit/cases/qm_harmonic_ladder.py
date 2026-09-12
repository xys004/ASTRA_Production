"""Ladder operators generate the harmonic-oscillator spectrum E_n = (n + 1/2).

CLAIM: with [a, a_dagger] = 1 and H = a_dagger a + 1/2 in units hbar = omega = 1,
the eigenvalues of H are n + 1/2 for n = 0, 1, 2, ..., a_dagger raises n by one
and a lowers it, and a annihilates the ground state.

The computation is done in a finite Fock truncation, which is exact on the lower
levels and wrong on the last one. That truncation artefact is measured and
reported rather than hidden, and every conclusion is restricted to the levels
where it does not act.

Legs:
  1. algebra   -- [a, a_dagger] equals the identity on all but the top level,
                  and the defect at the top is exactly -N as theory predicts;
  2. spectrum  -- H is diagonal with entries n + 1/2 on the safe levels;
  3. ladder    -- a_dagger|n> = sqrt(n+1)|n+1> and a|0> = 0, checked exactly;
  4. continuum -- the ground-state wavefunction satisfies the differential
                  equation, which is independent of the truncation entirely;
  5. falsifier -- a spectrum of n rather than n + 1/2 is rejected.
"""
import sympy as sp

FAILURES = []

N = 8          # Fock truncation: levels 0 .. N-1
SAFE = N - 1   # conclusions are restricted to levels below the top one


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


# Lowering operator in the truncated Fock basis: a|n> = sqrt(n)|n-1>.
a = sp.zeros(N, N)
for n in range(1, N):
    a[n - 1, n] = sp.sqrt(n)
a_dag = a.conjugate().T


# ---------------------------------------------------------------- leg 1
commutator = sp.simplify(a * a_dag - a_dag * a)
identity_part = sp.eye(N)
defect = sp.simplify(commutator - identity_part)

# The defect must be confined to the top level and equal exactly -N there.
off_top = [defect[i, j] for i in range(N) for j in range(N)
           if not (i == N - 1 and j == N - 1)]
check("commutator_is_identity_below_the_top_level",
      all(sp.simplify(entry) == 0 for entry in off_top),
      f"[a, a_dag] - I vanishes on all {N * N - 1} entries except the top one")

check("truncation_defect_is_exactly_minus_N",
      sp.simplify(defect[N - 1, N - 1] + N) == 0,
      f"defect at the top level = {defect[N - 1, N - 1]}, as the truncation predicts")


# ---------------------------------------------------------------- leg 2
H = sp.simplify(a_dag * a + sp.Rational(1, 2) * sp.eye(N))
diagonal_ok = all(
    sp.simplify(H[i, j]) == 0
    for i in range(N) for j in range(N) if i != j
)
check("hamiltonian_is_diagonal_in_the_fock_basis", diagonal_ok,
      "every off-diagonal entry of a_dag a vanishes")

spectrum_ok = all(
    sp.simplify(H[n, n] - (n + sp.Rational(1, 2))) == 0
    for n in range(SAFE)
)
check("spectrum_is_n_plus_one_half_on_safe_levels", spectrum_ok,
      f"E_n = n + 1/2 for n = 0..{SAFE - 1}, checked exactly")

# The top level is not claimed, and saying so is part of the result.
check("top_level_excluded_from_the_claim",
      sp.simplify(H[N - 1, N - 1] - (N - 1 + sp.Rational(1, 2))) == 0,
      "a_dag a is still correct at the top; only the commutator is not")


# ---------------------------------------------------------------- leg 3
ladder_ok = True
ladder_detail = ""
for n in range(SAFE - 1):
    ket = sp.zeros(N, 1)
    ket[n, 0] = 1
    raised = sp.simplify(a_dag * ket)
    expected = sp.zeros(N, 1)
    expected[n + 1, 0] = sp.sqrt(n + 1)
    if sp.simplify(raised - expected) != sp.zeros(N, 1):
        ladder_ok = False
        ladder_detail = f"raising failed at n={n}"
        break
check("raising_operator_acts_as_sqrt_n_plus_one", ladder_ok,
      ladder_detail or f"a_dag|n> = sqrt(n+1)|n+1> for n = 0..{SAFE - 2}")

ground = sp.zeros(N, 1)
ground[0, 0] = 1
check("lowering_annihilates_the_ground_state",
      sp.simplify(a * ground) == sp.zeros(N, 1),
      "a|0> = 0 exactly")


# ---------------------------------------------------------------- leg 4
# Independent of the truncation: the ground-state wavefunction of the
# continuum problem must satisfy -psi''/2 + x^2 psi/2 = E psi with E = 1/2.
x = sp.Symbol("x", real=True)
psi0 = sp.exp(-(x**2) / 2) / sp.pi ** sp.Rational(1, 4)
residual = sp.simplify(
    -sp.diff(psi0, x, 2) / 2 + x**2 * psi0 / 2 - sp.Rational(1, 2) * psi0
)
check("continuum_ground_state_satisfies_the_equation", residual == 0,
      f"residual = {residual}, with E = 1/2 and no truncation involved")

norm = sp.simplify(sp.integrate(psi0**2, (x, -sp.oo, sp.oo)))
check("continuum_ground_state_is_normalised", sp.simplify(norm - 1) == 0,
      f"integral of psi0^2 = {norm}")


# ---------------------------------------------------------------- leg 5
# A spectrum of n rather than n + 1/2 must be rejected: the zero-point energy
# is exactly what distinguishes them, and the continuum residual sees it.
wrong_energy = sp.Integer(0)
wrong_residual = sp.simplify(
    -sp.diff(psi0, x, 2) / 2 + x**2 * psi0 / 2 - wrong_energy * psi0
)
check("falsifier_rejects_zero_point_free_spectrum",
      sp.simplify(wrong_residual) != 0,
      "E = 0 leaves a nonzero residual, so the half is not optional")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
