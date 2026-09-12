"""Hermitian matrices have real spectra and an orthonormal eigenbasis.

CLAIM: for a Hermitian matrix the eigenvalues are real, eigenvectors belonging
to distinct eigenvalues are orthogonal, and the matrix is unitarily
diagonalizable so that A = U D U^dagger with D real diagonal.

Legs:
  1. symbolic  -- a Hermitian matrix with symbolic real entries has a
                  characteristic polynomial with real roots, shown through the
                  discriminant rather than by inspecting numbers;
  2. concrete  -- an explicit complex Hermitian matrix is diagonalized exactly
                  and the reconstruction A - U D U^dagger is the zero matrix;
  3. orthogonal -- eigenvectors for distinct eigenvalues have vanishing inner
                  product, checked exactly over the Gaussian rationals;
  4. falsifier -- a non-Hermitian matrix with complex eigenvalues is rejected by
                  the same reality test, so the test has power.
"""
import itertools

import sympy as sp

FAILURES = []


def check(name, ok, detail=""):
    if ok is True:
        print(f"CHECK {name}: OK {detail}".rstrip())
        return True
    FAILURES.append(name)
    print(f"CHECK {name}: FAIL {detail}".rstrip())
    return False


def is_hermitian(matrix):
    return sp.simplify(matrix - matrix.conjugate().T) == sp.zeros(*matrix.shape)


# ---------------------------------------------------------------- leg 1
a, d = sp.symbols("a d", real=True)
b_re, b_im = sp.symbols("b_re b_im", real=True)
b = b_re + sp.I * b_im
symbolic = sp.Matrix([[a, b], [sp.conjugate(b), d]])

check("symbolic_matrix_is_hermitian", is_hermitian(symbolic),
      "A = A^dagger with symbolic real diagonal and complex off-diagonal")

lam = sp.Symbol("lambda")
characteristic = sp.simplify(sp.expand((symbolic - lam * sp.eye(2)).det()))

# The discriminant is EXTRACTED from the characteristic polynomial of the matrix
# under test, not written out by hand. Writing it independently would leave leg 1
# disconnected from `symbolic`: it would then certify "a sum of squares" even for
# a matrix whose eigenvalues are complex, since nothing would tie the algebra to
# the object.
quad_a, quad_b, quad_c = sp.Poly(characteristic, lam).all_coeffs()
discriminant = sp.simplify(sp.expand(quad_b**2 - 4 * quad_a * quad_c))

# For a Hermitian 2x2 that discriminant equals (a - d)^2 + 4|b|^2, a sum of
# three real squares, so it cannot be negative and both roots are real.
certificate = (a - d) ** 2 + (2 * b_re) ** 2 + (2 * b_im) ** 2
check("discriminant_of_the_matrix_is_a_sum_of_squares",
      sp.simplify(sp.expand(discriminant - certificate)) == 0,
      f"discriminant = {sp.factor(sp.expand(discriminant))}")

# Independent numeric confirmation, evaluated on the DISCRIMINANT taken from the
# matrix, so a certificate that is algebraically tidy but attached to the wrong
# object would show up here as a negative value.
import random as _random
_random.seed(20260911)
worst = None
for _ in range(3000):
    subs = {sym: _random.uniform(-50, 50) for sym in (a, d, b_re, b_im)}
    value = float(discriminant.subs(subs))
    worst = value if worst is None else min(worst, value)
check("discriminant_nonnegative_on_random_reals", worst >= 0,
      f"minimum over 3000 random real assignments = {worst:.6f}")

# And the roots really are real for those same assignments.
roots_real = True
for _ in range(200):
    subs = {sym: _random.uniform(-50, 50) for sym in (a, d, b_re, b_im)}
    for root in sp.Poly(characteristic.subs(subs), lam).all_roots():
        if abs(complex(sp.N(root)).imag) > 1e-9:
            roots_real = False
            break
check("roots_of_the_characteristic_polynomial_are_real", roots_real,
      "200 random Hermitian instances, every root real to 1e-9")


# ---------------------------------------------------------------- leg 2
# Entries chosen so the spectrum is {1, 4, 5}: distinct and rational, which
# keeps the eigenvectors exact instead of burying the result in nested radicals
# that only simplify() could compare. The claim is about Hermitian matrices in
# general; leg 1 carries the symbolic case, and this one carries exactness.
A = sp.Matrix([
    [2, 1 - sp.I, 0],
    [1 + sp.I, 3, 0],
    [0, 0, 5],
])
check("concrete_matrix_is_hermitian", is_hermitian(A), "A = A^dagger exactly")

eigen = A.eigenvals()
all_real = all(bool(sp.simplify(sp.im(value)) == 0) for value in eigen)
check("concrete_eigenvalues_are_real", all_real,
      f"{len(eigen)} distinct eigenvalues, all with zero imaginary part")

# Reconstruct from the spectral decomposition. Vectors are normalised with the
# Hermitian inner product, so U is unitary by construction and the check is on A.
vectors = []
values = []
for value, _multiplicity, basis in A.eigenvects():
    for vector in basis:
        norm = sp.sqrt(sp.simplify((vector.conjugate().T * vector)[0, 0]))
        vectors.append(sp.simplify(vector / norm))
        values.append(sp.simplify(value))

U = sp.Matrix.hstack(*vectors)
D = sp.diag(*values)
unitary_gap = sp.simplify(U * U.conjugate().T - sp.eye(3))
check("eigenbasis_is_unitary", unitary_gap == sp.zeros(3, 3),
      "U U^dagger = I exactly")

reconstruction = sp.simplify(A - U * D * U.conjugate().T)
check("spectral_reconstruction_exact",
      reconstruction == sp.zeros(3, 3),
      f"A - U D U^dagger = {reconstruction.tolist()}")


# ---------------------------------------------------------------- leg 3
orthogonal_ok = True
pairs = 0
for i, j in itertools.combinations(range(len(vectors)), 2):
    if sp.simplify(values[i] - values[j]) == 0:
        continue
    pairs += 1
    inner = sp.simplify((vectors[i].conjugate().T * vectors[j])[0, 0])
    if inner != 0:
        orthogonal_ok = False
        break
check("distinct_eigenvalues_give_orthogonal_vectors", orthogonal_ok,
      f"{pairs} pairs with distinct eigenvalues, all inner products zero")


# ---------------------------------------------------------------- leg 4
# A non-Hermitian matrix with genuinely complex eigenvalues must be rejected by
# the same reality test, otherwise leg 2 would pass for any matrix.
rotation = sp.Matrix([[0, -1], [1, 0]])
check("falsifier_matrix_is_not_hermitian", not is_hermitian(rotation),
      "the rotation generator is real antisymmetric, not Hermitian")

rotation_values = rotation.eigenvals()
has_complex = any(bool(sp.simplify(sp.im(value)) != 0) for value in rotation_values)
check("falsifier_rejects_complex_spectrum", has_complex,
      f"eigenvalues {list(rotation_values)} are not real, and the test sees it")


print()
print(f"legs_failed={len(FAILURES)} {FAILURES}")
if FAILURES:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
