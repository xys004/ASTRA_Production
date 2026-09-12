#!/usr/bin/env python3
"""Build and verify the review-independence ablation corpus.

Validators live as real, executable Python files under
``benchmarks/quality/validator_audit/cases/``. Defective variants are derived
from a sound base by localized patches, so the injected defect is explicit and
auditable instead of being spread through a hand-written copy, and the sound
and defective members of a pair are matched on domain and difficulty.

Every case passes five gates before it is written:

* the sound base executes and prints the verdict it declares;
* each defective variant also executes and still prints ``VERDICT: PASS``,
  which is what makes it dangerous rather than merely broken;
* each patch applies exactly once, so a defect cannot silently fail to land;
* no sound validator contains a check that cannot fail;
* no sound validator computes a value it never reads.

The last two exist because a sound case carrying a defect is worse than useless:
a reviewer would reject it correctly, the rejection would be scored as a false
alarm, and it would corrupt the specificity estimate the corpus is built to
measure. Both gates were added after an adversarial review found six such cases
among the first fifteen, and each caught further instances immediately.

Usage:
    python scripts/build_ablation_corpus.py --verify        # gates only
    python scripts/build_ablation_corpus.py --write         # gates, then emit
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "benchmarks" / "quality" / "validator_audit" / "cases"
OUT_DIR = ROOT / "benchmarks" / "quality" / "validator_audit"
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# Labels the reviewer prompt and core/review_defects.py both recognise.
KNOWN_LABELS = {
    "hardcoded_pass", "unreachable_failure", "self_comparison", "sampling_as_proof",
    "wrong_domain", "missing_assumption", "wrong_tolerance", "wrong_units",
    "unknown_as_pass", "swallowed_exception", "missing_dependency",
    "engine_mismatch", "unsimplified_symbolic_zero", "assumed_bound",
    "undecidable_positivity", "link_in_comment", "proxy_continuity",
    "missing_domain",
}

LONG_MIN = 120     # a validator below this is a snippet, not a realistic one
LONG_MAX = 320


# --------------------------------------------------------------------- registry
# Each entry: one sound base plus the defective variants derived from it.
REGISTRY: list[dict] = [
    {
        "base": "sr_velocity_addition",
        "domain": "special_relativity",
        "objective": (
            "Establish that relativistic velocity composition cannot produce a "
            "superluminal result for subluminal inputs."
        ),
        "intuition": (
            "For |u| < c and |v| < c the composition w = (u+v)/(1+uv/c^2) "
            "satisfies |w| < c, and reduces to u+v when c grows without bound."
        ),
        "defects": [
            {
                "suffix": "sampling",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof"],
                "severity": "critical",
                "note": "the universal bound is left to 4000 random draws",
                "patches": [
                    (
                        'difference = sp.simplify(c**2 - W**2)',
                        'difference = 0  # symbolic leg dropped; sampling below is the evidence',
                    ),
                    (
                        'expected_form = (c**2 - u**2) * (c**2 - v**2) * c**2 / (c**2 + u * v) ** 2\n'
                        'residual = sp.simplify(sp.together(difference - expected_form))\n'
                        'check("symbolic_factorization", residual == 0, f"residual={residual}")',
                        '# The random draws below cover the domain densely enough to stand in\n'
                        '# for the algebraic factorization.',
                    ),
                    (
                        'rapidity = W.subs({u: c * sp.tanh(alpha), v: c * sp.tanh(beta)})\n'
                        'collapsed = sp.simplify(sp.expand_trig(sp.simplify(rapidity)) - c * sp.tanh(alpha + beta))\n'
                        'check(\n'
                        '    "rapidity_collapse",\n'
                        '    sp.simplify(collapsed) == 0,\n'
                        '    "w = c*tanh(alpha+beta) on the open domain",\n'
                        ')',
                        '# Rapidity argument omitted.',
                    ),
                ],
            },
            {
                "suffix": "unknown_pass",
                "primary": "unknown_as_pass",
                "labels": ["unknown_as_pass"],
                "severity": "critical",
                "note": "an undecided symbolic query is accepted as success",
                "patches": [
                    (
                        '    if ok is True:\n'
                        '        print(f"CHECK {name}: OK {detail}".rstrip())\n'
                        '        return True',
                        '    if ok is not False:\n'
                        '        # Treat an undecided query as satisfied: sympy returning None\n'
                        '        # only means it could not find a proof quickly.\n'
                        '        print(f"CHECK {name}: OK {detail}".rstrip())\n'
                        '        return True',
                    ),
                ],
            },
            {
                "suffix": "self_comparison",
                "primary": "self_comparison",
                "labels": ["self_comparison"],
                "severity": "critical",
                "note": "the factorization is compared against itself",
                "patches": [
                    (
                        'expected_form = (c**2 - u**2) * (c**2 - v**2) * c**2 / (c**2 + u * v) ** 2',
                        'expected_form = sp.simplify(c**2 - W**2)  # same quantity, recomputed',
                    ),
                ],
            },
            {
                "suffix": "tolerance",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance"],
                "severity": "major",
                "note": "a one percent slack admits genuinely superluminal results",
                "patches": [
                    (
                        '    if not abs(w) < 1.0:\n'
                        '        numeric_ok = False\n'
                        '        break',
                        '    if not abs(w) < 1.0 + 1e-2:  # numerical slack\n'
                        '        numeric_ok = False\n'
                        '        break',
                    ),
                    (
                        'check("numeric_subluminal", numeric_ok and worst < 1.0,',
                        'check("numeric_subluminal", numeric_ok and worst < 1.0 + 1e-2,',
                    ),
                ],
            },
        ],
    },
    {
        "base": "qm_pauli_algebra",
        "domain": "quantum_mechanics",
        "objective": (
            "Establish that the Pauli matrices close the su(2) algebra exactly, "
            "with no free parameter left in the structure constants."
        ),
        "intuition": (
            "The commutators [s_i, s_j] = 2i eps_ijk s_k and anticommutators "
            "{s_i, s_j} = 2 delta_ij I hold exactly, and together fix the product."
        ),
        "defects": [
            {
                "suffix": "unreachable_fail",
                "primary": "unreachable_failure",
                "labels": ["unreachable_failure"],
                "severity": "critical",
                "note": "the failure branch cannot be reached, so PASS is unconditional",
                "patches": [
                    (
                        '    FAILURES.append(name)\n'
                        '    print(f"CHECK {name}: FAIL {detail}".rstrip())\n'
                        '    return False',
                        '    # Collect the diagnostic without failing the run: a single\n'
                        '    # symbolic hiccup should not discard the whole audit.\n'
                        '    print(f"CHECK {name}: FAIL {detail}".rstrip())\n'
                        '    return False',
                    ),
                ],
            },
            {
                "suffix": "swallowed",
                "primary": "swallowed_exception",
                "labels": ["swallowed_exception"],
                "severity": "critical",
                "note": "the exact-algebra leg is wrapped so any error becomes success",
                "patches": [
                    (
                        'commutator_ok = True\n'
                        'worst_pair = ""\n'
                        'for a, b in itertools.product(ORDER, repeat=2):\n'
                        '    lhs = commutator(SIGMA[a], SIGMA[b])\n'
                        '    rhs = sp.zeros(2, 2)\n'
                        '    for k in ORDER:\n'
                        '        eps = levi_civita(a, b, k)\n'
                        '        if eps:\n'
                        '            rhs += 2 * sp.I * eps * SIGMA[k]\n'
                        '    residual = sp.simplify(lhs - rhs)\n'
                        '    if residual != sp.zeros(2, 2):\n'
                        '        commutator_ok = False\n'
                        '        worst_pair = f"[{a},{b}] residual={residual.tolist()}"\n'
                        '        break',
                        'commutator_ok = True\n'
                        'worst_pair = ""\n'
                        'try:\n'
                        '    for a, b in itertools.product(ORDER, repeat=2):\n'
                        '        lhs = commutator(SIGMA[a], SIGMA[b])\n'
                        '        rhs = sp.zeros(2, 2)\n'
                        '        for k in ORDER:\n'
                        '            eps = levi_civita(a, b, k)\n'
                        '            if eps:\n'
                        '                rhs += 2 * sp.I * eps * SIGMA[k]\n'
                        '        residual = sp.simplify(lhs - rhs)\n'
                        '        if residual != sp.zeros(2, 2):\n'
                        '            commutator_ok = False\n'
                        '            worst_pair = f"[{a},{b}] residual={residual.tolist()}"\n'
                        '            break\n'
                        'except Exception:\n'
                        '    pass  # symbolic backends are flaky; keep the audit moving',
                    ),
                ],
            },
            {
                "suffix": "hardcoded",
                "primary": "hardcoded_pass",
                "labels": ["hardcoded_pass", "unreachable_failure"],
                "severity": "critical",
                "note": "the verdict is printed without consulting the legs",
                "patches": [
                    (
                        'print(f"legs_failed={len(FAILURES)} {FAILURES}")\n'
                        'if FAILURES:\n'
                        '    print("VERDICT: FAIL")\n'
                        '    raise SystemExit(1)\n'
                        'print("VERDICT: PASS")',
                        'print(f"legs_failed={len(FAILURES)} {FAILURES}")\n'
                        '# The Pauli algebra is standard textbook material, so the verdict\n'
                        '# is known ahead of the checks above.\n'
                        'print("VERDICT: PASS")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ode_damped_oscillator",
        "domain": "classical_mechanics",
        "objective": (
            "Establish that the textbook damped-oscillator solutions satisfy the "
            "equation of motion in all three damping regimes."
        ),
        "intuition": (
            "x'' + 2*g*x' + w0^2*x = 0 is solved by the standard forms for "
            "g < w0, g = w0 and g > w0, each matching x(0)=x0 and x'(0)=v0."
        ),
        "defects": [
            {
                "suffix": "link_in_comment",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "missing_assumption"],
                "severity": "critical",
                "note": "the regime-boundary limit is asserted in prose, never computed",
                "patches": [
                    (
                        'limit_expr = sp.limit(underdamped.subs(w0, g + sp.Symbol("d", positive=True)),\n'
                        '                      sp.Symbol("d", positive=True), 0, "+")\n'
                        'limit_gap = sp.simplify(sp.expand(limit_expr - critical))\n'
                        'check("underdamped_tends_to_critical", limit_gap == 0,\n'
                        '      f"limit gap={limit_gap}")',
                        '# As g -> w0 the underdamped form reduces to the critical form, since\n'
                        '# sin(wd t)/wd -> t and cos(wd t) -> 1. The two branches therefore\n'
                        '# agree on the boundary and no separate check is needed.\n'
                        'limit_gap = 0\n'
                        'check("underdamped_tends_to_critical", limit_gap == 0,\n'
                        '      "established in the comment above")',
                    ),
                ],
            },
            {
                "suffix": "proxy",
                "primary": "proxy_continuity",
                "labels": ["proxy_continuity"],
                "severity": "critical",
                "note": "energy decay is substituted for agreement with the solution",
                "patches": [
                    (
                        'closed = sp.lambdify(t, underdamped.subs({g: G, w0: W, x0: X0, v0: V0}), "math")\n'
                        'analytic_value = closed(T_END)\n'
                        'numeric_value = rk4(G, W, X0, V0, T_END, STEPS)\n'
                        'gap = abs(analytic_value - numeric_value)\n'
                        '# RK4 is fourth order; with this step the truncation floor is far below 1e-9,\n'
                        '# so the tolerance is set by the method rather than chosen to fit.\n'
                        'tolerance = 1e-9\n'
                        'check("rk4_matches_closed_form", gap < tolerance,\n'
                        '      f"|analytic - rk4| = {gap:.3e} < {tolerance:.0e} at t={T_END}")',
                        '# Rather than compare against the closed form directly, check the\n'
                        '# physical signature of damping: the mechanical energy of the numeric\n'
                        '# trajectory must decrease. A solution of the damped equation always\n'
                        '# loses energy, so this stands in for agreement.\n'
                        'energy_start = 0.5 * V0**2 + 0.5 * W**2 * X0**2\n'
                        'late = rk4(G, W, X0, V0, T_END, STEPS)\n'
                        'energy_late = 0.5 * W**2 * late**2\n'
                        'check("energy_decays_as_damping_requires", energy_late < energy_start,\n'
                        '      f"E(0)={energy_start:.4f} -> E(t_end)<={energy_late:.4f}")',
                    ),
                ],
            },
            {
                "suffix": "missing_domain",
                "primary": "missing_domain",
                "labels": ["missing_domain", "wrong_domain"],
                "severity": "critical",
                "note": "two of the three claimed regimes are never tested",
                "patches": [
                    (
                        'crit_res = residual_of(critical, g, g)      # critical means w0 = g\n'
                        'check("critical_residual_zero", crit_res == 0, f"residual={crit_res}")\n'
                        '\n'
                        'over_res = residual_of(overdamped, g, w0)\n'
                        'check("overdamped_residual_zero", over_res == 0, f"residual={over_res}")',
                        '# The critical and overdamped forms are analytic continuations of the\n'
                        '# underdamped one, so verifying the underdamped residual covers all\n'
                        '# three regimes at once.\n'
                        'check("all_regimes_covered", True, "by analytic continuation")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "vc_divergence_of_curl",
        "domain": "vector_calculus",
        "objective": (
            "Establish the second-derivative identities of vector calculus and "
            "confirm the divergence theorem on a sphere."
        ),
        "intuition": (
            "div(curl F) = 0 and curl(grad phi) = 0 for any twice differentiable "
            "field, and the flux of (x, y, z) through a sphere of radius a is "
            "4*pi*a^3."
        ),
        "defects": [
            {
                "suffix": "assumed_flux",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "self_comparison"],
                "severity": "critical",
                "note": "the surface integral is replaced by the answer it should produce",
                "patches": [
                    (
                        'flux_integrand = a_pos * a_pos**2 * sp.sin(theta)\n'
                        'surface_integral = sp.simplify(\n'
                        '    sp.integrate(\n'
                        '        sp.integrate(flux_integrand, (theta, 0, sp.pi)),\n'
                        '        (varphi, 0, 2 * sp.pi),\n'
                        '    )\n'
                        ')',
                        '# The flux of a radial field through a sphere is standard, so the\n'
                        '# surface side is taken from the known closed form instead of being\n'
                        '# integrated again.\n'
                        'surface_integral = 4 * sp.pi * a_pos**3',
                    ),
                ],
            },
        ],
    },
    {
        "base": "nt_fermat_little_theorem",
        "domain": "number_theory",
        "objective": (
            "Establish Fermat's little theorem and show that its converse fails "
            "on the Carmichael numbers."
        ),
        "intuition": (
            "For prime p and a coprime to p, a^(p-1) = 1 (mod p); 561 satisfies "
            "the same congruence for every coprime base yet is composite."
        ),
        "defects": [
            {
                "suffix": "drop_coprimality",
                "primary": "missing_assumption",
                "labels": ["missing_assumption", "wrong_domain"],
                "severity": "critical",
                "note": "the coprimality hypothesis is dropped from the claim",
                "patches": [
                    (
                        '# The theorem needs the coprimality hypothesis. Dropping it must break the\n'
                        '# conclusion, otherwise the hypothesis is decorative.\n'
                        'non_coprime_breaks = pow(7, 6, 7) != 1\n'
                        'check("coprimality_hypothesis_is_necessary", non_coprime_breaks,\n'
                        '      f"7^6 mod 7 = {pow(7, 6, 7)}, not 1, as the hypothesis requires")',
                        '# Every residue below p is automatically coprime to a prime p, so the\n'
                        '# hypothesis carries no content and the theorem holds for all bases.\n'
                        'check("theorem_holds_for_all_bases", True,\n'
                        '      "coprimality is automatic for a prime modulus")',
                    ),
                ],
            },
            {
                "suffix": "sampled_bases",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof"],
                "severity": "major",
                "note": "the exhaustive sweep is reduced to three fixed bases",
                "patches": [
                    (
                        '    for base in range(1, p):          # every residue coprime to p\n'
                        '        checked += 1',
                        '    for base in (2, 3, 5):            # a representative sample suffices\n'
                        '        if base >= p:\n'
                        '            continue\n'
                        '        checked += 1',
                    ),
                    (
                        'check("exhaustive_over_small_primes", exhaustive_ok,\n'
                        '      counterexample or f"{checked} base/prime pairs, every residue covered")',
                        'check("exhaustive_over_small_primes", exhaustive_ok,\n'
                        '      counterexample or f"{checked} base/prime pairs sampled")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "em_maxwell_wave_equation",
        "domain": "electromagnetism",
        "objective": (
            "Establish that source-free Maxwell equations force electromagnetic "
            "waves to propagate at 1/sqrt(mu0*eps0)."
        ),
        "intuition": (
            "Each Cartesian component of E obeys the wave equation, and a plane "
            "wave solves it exactly when omega/k = 1/sqrt(mu0*eps0)."
        ),
        "defects": [
            {
                "suffix": "units",
                "primary": "wrong_units",
                "labels": ["wrong_units", "wrong_tolerance"],
                "severity": "critical",
                "note": "an absolute speed difference is tested against a relative threshold",
                "patches": [
                    (
                        'relative_error = abs(speed - C_REF) / C_REF',
                        'relative_error = abs(speed - C_REF)   # difference in m/s',
                    ),
                    (
                        'check("speed_matches_defined_c",\n'
                        '      bool(relative_error < sp.Float("1e-9")),',
                        'check("speed_matches_defined_c",\n'
                        '      bool(relative_error < sp.Float("1e-3")),',
                    ),
                ],
            },
            {
                "suffix": "undecided_positivity",
                "primary": "undecidable_positivity",
                "labels": ["undecidable_positivity", "unknown_as_pass"],
                "severity": "critical",
                "note": "an undecided positivity query is recorded as established",
                "patches": [
                    (
                        '# ---------------------------------------------------------------- leg 5',
                        '# ---------------------------------------------------------------- leg 4b\n'
                        '# The stored energy density must be positive for the wave to be\n'
                        '# physical. Ask the symbolic engine directly.\n'
                        'energy_density = eps0 * plane**2 / 2\n'
                        'positive = sp.ask(sp.Q.positive(energy_density))\n'
                        'check("energy_density_positive", positive is not False,\n'
                        '      f"ask returned {positive}, which is not a refutation")\n'
                        '\n'
                        '\n'
                        '# ---------------------------------------------------------------- leg 5',
                    ),
                ],
            },
        ],
    },
    {
        "base": "gr_schwarzschild_vacuum",
        "domain": "general_relativity",
        "objective": (
            "Establish that the Schwarzschild metric is a vacuum solution "
            "outside the horizon while remaining genuinely curved."
        ),
        "intuition": (
            "The Ricci tensor of the Schwarzschild metric vanishes identically "
            "for r > 2M, yet the Kretschmann scalar is 48 M^2 / r^6 and nonzero."
        ),
        "defects": [
            {
                "suffix": "everywhere",
                "primary": "wrong_domain",
                "labels": ["wrong_domain", "missing_domain"],
                "severity": "critical",
                "note": (
                    "vacuum is claimed at every radius, contradicting the "
                    "curvature singularity the same script computes"
                ),
                "patches": [
                    (
                        'check("schwarzschild_is_ricci_flat", vacuum,',
                        '# The Ricci components vanish as rational functions of r, so the\n'
                        '# vacuum property holds at every radius, horizon and centre included.\n'
                        'check("schwarzschild_is_ricci_flat_everywhere", vacuum,',
                    ),
                ],
            },
            {
                "suffix": "engine",
                "primary": "engine_mismatch",
                "labels": ["engine_mismatch"],
                "severity": "major",
                "note": "the script declares the Wolfram engine but is Python",
                "patches": [
                    (
                        '"""The Schwarzschild metric is a vacuum solution, and the 2-sphere is not flat.',
                        '# ASTRA_ENGINE: wolfram\n'
                        '"""The Schwarzschild metric is a vacuum solution, and the 2-sphere is not flat.',
                    ),
                ],
            },
        ],
    },
    {
        "base": "th_carnot_and_adiabat",
        "domain": "thermodynamics",
        "objective": (
            "Establish the reversible adiabat P V^gamma = const and derive the "
            "Carnot efficiency as an upper bound."
        ),
        "intuition": (
            "A reversible adiabatic ideal-gas process keeps P V^gamma constant "
            "and has zero entropy change, and no cycle beats 1 - Tc/Th."
        ),
        "defects": [
            {
                "suffix": "quoted_efficiency",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "self_comparison"],
                "severity": "critical",
                "note": "the efficiency is quoted and then compared against itself",
                "patches": [
                    (
                        'work = sp.simplify(q_hot - q_cold)\n'
                        'efficiency = sp.simplify(work / q_hot)',
                        'work = sp.simplify(q_hot - q_cold)\n'
                        '# The Carnot result is standard, so the efficiency is taken directly\n'
                        '# rather than reconstructed from the heats on each isotherm.\n'
                        'efficiency = 1 - Tc / Th',
                    ),
                ],
            },
        ],
    },
    {
        "base": "an_basel_and_harmonic",
        "domain": "analysis",
        "objective": (
            "Establish the Basel sum in closed form, the divergence of the "
            "harmonic series, and that p = 1 is the exact threshold."
        ),
        "intuition": (
            "sum 1/k^2 = pi^2/6 exactly, sum 1/k diverges, and sum 1/k^p "
            "converges precisely for p > 1."
        ),
        "defects": [
            {
                "suffix": "loose_tail",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance"],
                "severity": "major",
                "note": "the tail bound is widened until it no longer constrains anything",
                "patches": [
                    (
                        'check("partial_sum_within_predicted_tail_bound",\n'
                        '      0 < observed_gap < tail_bound,\n'
                        '      f"gap={observed_gap:.3e}, predicted bound={tail_bound:.3e}")',
                        '# Floating point accumulates over 20000 terms, so the comparison is\n'
                        '# given generous room rather than held to the integral-test bound.\n'
                        'check("partial_sum_within_predicted_tail_bound",\n'
                        '      0 < observed_gap < 1e-1,\n'
                        '      f"gap={observed_gap:.3e}, tolerance=1e-1")',
                    ),
                    (
                        '# The gap must also be close to the leading tail estimate 1/N, not merely below\n'
                        '# it, which distinguishes a converging sum from one that stalls early.\n'
                        'check("gap_matches_leading_tail_estimate",\n'
                        '      0.9 < observed_gap / tail_bound < 1.0,\n'
                        '      f"gap / (1/N) = {observed_gap / tail_bound:.4f}")',
                        'check("gap_is_small", observed_gap < 1e-1,\n'
                        '      f"gap = {observed_gap:.3e}")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "la_hermitian_spectral",
        "domain": "linear_algebra",
        "objective": (
            "Establish that Hermitian matrices have real spectra and an "
            "orthonormal eigenbasis that reconstructs the matrix exactly."
        ),
        "intuition": (
            "A Hermitian matrix has real eigenvalues, orthogonal eigenvectors "
            "for distinct eigenvalues, and satisfies A = U D U^dagger."
        ),
        "defects": [
            {
                "suffix": "unsimplified_zero",
                "primary": "unsimplified_symbolic_zero",
                "labels": ["unsimplified_symbolic_zero", "unknown_as_pass"],
                "severity": "critical",
                "note": (
                    "the reconstruction is compared without canonicalization and "
                    "an undecided zero test is accepted"
                ),
                "patches": [
                    (
                        'reconstruction = sp.simplify(A - U * D * U.conjugate().T)\n'
                        'check("spectral_reconstruction_exact",\n'
                        '      reconstruction == sp.zeros(3, 3),\n'
                        '      f"A - U D U^dagger = {reconstruction.tolist()}")',
                        '# Skip the canonicalization: the difference is zero by construction, so\n'
                        '# the structural test is enough and is far cheaper.\n'
                        'reconstruction = A - U * D * U.conjugate().T\n'
                        'check("spectral_reconstruction_exact",\n'
                        '      reconstruction.is_zero_matrix is not False,\n'
                        '      f"is_zero_matrix = {reconstruction.is_zero_matrix}")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "pr_variance_and_chebyshev",
        "domain": "probability",
        "objective": (
            "Establish the variance identity and Chebyshev's inequality, and "
            "show the constant 1/k^2 cannot be improved."
        ),
        "intuition": (
            "Var(X) = E[X^2] - E[X]^2, and P(|X - mu| >= k sigma) <= 1/k^2 with "
            "the bound attained by a two-point distribution."
        ),
        "defects": [
            {
                "suffix": "empirical_sharpness",
                "primary": "proxy_continuity",
                "labels": ["proxy_continuity", "sampling_as_proof"],
                "severity": "critical",
                "note": (
                    "sharpness is argued from a normal sample, which never "
                    "approaches the bound, instead of from the attaining case"
                ),
                "patches": [
                    (
                        'check("chebyshev_bound_is_attained",\n'
                        '      sp.simplify(tail_mass - 1 / k_val**2) == 0,\n'
                        '      f"tail mass computed from the support = {tail_mass} = 1/k^2, so the bound is sharp")',
                        '# Sharpness is easier to see empirically: a large sample never exceeds\n'
                        '# the bound, and the closeness of the observed tail to it is what\n'
                        '# sharpness means in practice.\n'
                        'check("chebyshev_bound_is_attained", True,\n'
                        '      "confirmed empirically by the sample in the next leg")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "fl_bernoulli_venturi",
        "domain": "fluid_mechanics",
        "objective": (
            "Derive Bernoulli from the streamwise Euler equation and predict "
            "the pressure drop in a Venturi contraction."
        ),
        "intuition": (
            "For steady incompressible inviscid flow, p + rho v^2/2 + rho g z "
            "is constant along a streamline, which fixes the Venturi drop."
        ),
        "defects": [
            {
                "suffix": "any_flow",
                "primary": "missing_domain",
                "labels": ["missing_domain", "wrong_domain"],
                "severity": "critical",
                "note": "the incompressibility hypothesis is dropped from the claim",
                "patches": [
                    (
                        'mach = sp.Symbol("M", positive=True)\n'
                        'compressible_correction = mach**2 / 4\n'
                        'one_percent = sp.solve(sp.Eq(compressible_correction, sp.Rational(1, 100)), mach)\n'
                        'positive_root = [root for root in one_percent if bool(root > 0)][0]\n'
                        'check("compressibility_threshold_located",\n'
                        '      bool(abs(float(positive_root) - 0.2) < 1e-12),\n'
                        '      f"one percent error at Mach {float(positive_root):.3f}")\n'
                        '\n'
                        'water_mach = speed_2 / 1481.0            # speed of sound in water, m/s\n'
                        'check("water_case_is_safely_incompressible",\n'
                        '      water_mach < 0.01,\n'
                        '      f"Mach {water_mach:.5f} in the throat, far below the threshold")',
                        '# Bernoulli is a statement about energy along a streamline, so it holds\n'
                        '# for any steady flow regardless of the working fluid or its speed.\n'
                        'check("result_holds_for_any_steady_flow", True,\n'
                        '      "no restriction on compressibility is needed")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "qm_harmonic_ladder",
        "domain": "quantum_mechanics",
        "objective": (
            "Establish that ladder operators generate the harmonic-oscillator "
            "spectrum E_n = n + 1/2."
        ),
        "intuition": (
            "With [a, a_dagger] = 1 and H = a_dagger a + 1/2, the eigenvalues "
            "are n + 1/2 and a annihilates the ground state."
        ),
        "defects": [
            {
                "suffix": "ignores_truncation",
                "primary": "wrong_domain",
                "labels": ["wrong_domain", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the canonical commutator is claimed on every level, "
                    "contradicting the truncation defect the script computes"
                ),
                "patches": [
                    (
                        'off_top = [defect[i, j] for i in range(N) for j in range(N)\n'
                        '           if not (i == N - 1 and j == N - 1)]\n'
                        'check("commutator_is_identity_below_the_top_level",\n'
                        '      all(sp.simplify(entry) == 0 for entry in off_top),\n'
                        '      f"[a, a_dag] - I vanishes on all {N * N - 1} entries except the top one")\n'
                        '\n'
                        'check("truncation_defect_is_exactly_minus_N",\n'
                        '      sp.simplify(defect[N - 1, N - 1] + N) == 0,\n'
                        '      f"defect at the top level = {defect[N - 1, N - 1]}, as the truncation predicts")',
                        'off_top = [defect[i, j] for i in range(N) for j in range(N)\n'
                        '           if not (i == N - 1 and j == N - 1)]\n'
                        '# The single top-level entry is a boundary artefact of the finite matrix\n'
                        '# and carries no physics, so the canonical commutation relation holds\n'
                        '# on the whole space.\n'
                        'check("commutator_is_the_identity", \n'
                        '      all(sp.simplify(entry) == 0 for entry in off_top),\n'
                        '      "[a, a_dag] = I on the Fock space")',
                    ),
                    (
                        'spectrum_ok = all(\n'
                        '    sp.simplify(H[n, n] - (n + sp.Rational(1, 2))) == 0\n'
                        '    for n in range(SAFE)\n'
                        ')\n'
                        'check("spectrum_is_n_plus_one_half_on_safe_levels", spectrum_ok,\n'
                        '      f"E_n = n + 1/2 for n = 0..{SAFE - 1}, checked exactly")',
                        'spectrum_ok = all(\n'
                        '    sp.simplify(H[n, n] - (n + sp.Rational(1, 2))) == 0\n'
                        '    for n in range(N)\n'
                        ')\n'
                        'check("spectrum_is_n_plus_one_half_on_every_level", spectrum_ok,\n'
                        '      f"E_n = n + 1/2 for n = 0..{N - 1}, the whole space")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "gr_flrw_friedmann",
        "domain": "general_relativity",
        "objective": (
            "Derive the Friedmann equations from the flat FLRW metric and "
            "confirm the dust and radiation power laws."
        ),
        "intuition": (
            "For ds^2 = -dt^2 + a(t)^2 dx^2, G_tt = 3 (a'/a)^2 and the field "
            "equations give the Friedmann pair, solved by t^(2/3) and t^(1/2)."
        ),
        "defects": [
            {
                "suffix": "asserted_acceleration",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "assumed_bound"],
                "severity": "critical",
                "note": "the acceleration equation is asserted in prose, never solved for",
                "patches": [
                    (
                        'solved = sp.solve(\n'
                        '    [sp.Eq(-(2 * accel + hubble_sq), 8 * sp.pi * G_newton * p_pres),\n'
                        '     sp.Eq(3 * hubble_sq, 8 * sp.pi * G_newton * rho)],\n'
                        '    [accel, hubble_sq],\n'
                        '    dict=True,\n'
                        ')\n'
                        'check("acceleration_equation_is_forced_and_unique",\n'
                        '      len(solved) == 1\n'
                        '      and sp.simplify(solved[0][accel]\n'
                        '                      + sp.Rational(4, 3) * sp.pi * G_newton * (rho + 3 * p_pres)) == 0,\n'
                        '      f"a\'\'/a = {sp.simplify(solved[0][accel]) if solved else \'no solution\'}")',
                        '# Eliminating (a\'/a)^2 between the spatial component and the first\n'
                        '# Friedmann equation gives a\'\'/a = -(4 pi G / 3)(rho + 3 p), which is\n'
                        '# the standard acceleration equation, so no separate solve is needed.\n'
                        'check("acceleration_equation_is_forced_and_unique",\n'
                        '      sp.simplify(spatial - spatial) == 0,\n'
                        '      "a\'\'/a = -(4 pi G/3)(rho + 3p) as derived in the comment above")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "an_fourier_parseval",
        "domain": "analysis",
        "objective": (
            "Establish the Fourier coefficients of the square wave, Parseval's "
            "identity, and the persistence of the Gibbs overshoot."
        ),
        "intuition": (
            "b_n = 4/(n pi) for odd n, Parseval then gives sum 1/(2m-1)^2 = "
            "pi^2/8, and the partial sums overshoot the jump by a fixed amount."
        ),
        "defects": [
            {
                "suffix": "numeric_parseval",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "wrong_tolerance"],
                "severity": "critical",
                "note": "the exact series identity is replaced by a truncated numeric sum",
                "patches": [
                    (
                        'm = sp.Symbol("m", positive=True, integer=True)\n'
                        'right = sp.simplify(sp.summation((4 / (sp.pi * (2 * m - 1))) ** 2, (m, 1, sp.oo)))\n'
                        'check("parseval_two_sides_agree", sp.simplify(left - right) == 0,\n'
                        '      f"left = {left}, right = {right}")',
                        'm = sp.Symbol("m", positive=True, integer=True)\n'
                        '# Summing the first few hundred terms numerically is enough to see the\n'
                        '# identity hold; the closed form adds nothing the numbers do not show.\n'
                        'right = sum(4.0 / (math.pi * (2 * j - 1)) ** 2 * math.pi**0\n'
                        '            for j in range(1, 400))\n'
                        'right = sum((4.0 / (math.pi * (2 * j - 1))) ** 2 for j in range(1, 400))\n'
                        'check("parseval_two_sides_agree", abs(float(left) - right) < 1e-2,\n'
                        '      f"left = {float(left)}, right = {right:.6f}")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "qm_uncertainty_saturation",
        "domain": "quantum_mechanics",
        "objective": (
            "Establish that the harmonic-oscillator ground state saturates the "
            "position-momentum uncertainty bound and that excited states do not."
        ),
        "intuition": (
            "With hbar = 1 the n-th eigenstate has dx dp = n + 1/2, so the "
            "Robertson floor of 1/2 is attained only by the ground state."
        ),
        "defects": [
            {
                "suffix": "asserted_excited",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "assumed_bound"],
                "severity": "critical",
                "note": (
                    "the excited-state spreads are read off the energy in a "
                    "comment instead of being integrated"
                ),
                "patches": [
                    (
                        '    product = sp.simplify(\n'
                        '        sp.sqrt(sp.simplify(mx2 - mx**2)) * sp.sqrt(sp.simplify(mp2 - mp**2))\n'
                        '    )\n'
                        '    excited_products.append(product)',
                        '    # The virial theorem splits E_n = n + 1/2 evenly between the kinetic\n'
                        '    # and potential parts, so the product of the spreads is n + 1/2.\n'
                        '    # Recomputing the integrals only confirms what the energy already fixes.\n'
                        '    product = n + sp.Rational(1, 2)\n'
                        '    excited_products.append(product)',
                    ),
                ],
            },
        ],
    },
    {
        "base": "nt_bezout_and_gcd",
        "domain": "number_theory",
        "objective": (
            "Establish Bezout's identity and characterise the gcd as the least "
            "positive integer combination of the two arguments."
        ),
        "intuition": (
            "The extended Euclidean algorithm returns g, x, y with ax + by = g, "
            "g divides both, every common divisor divides g, and g is minimal."
        ),
        "defects": [
            {
                "suffix": "asserted_minimality",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "assumed_bound"],
                "severity": "critical",
                "note": "minimality is asserted in prose, the search is deleted",
                "patches": [
                    (
                        'minimal_ok = True\n'
                        'minimal_detail = ""\n'
                        'for a in range(-12, 13):\n'
                        '    for b in range(-12, 13):\n'
                        '        if a == 0 and b == 0:\n'
                        '            continue\n'
                        '        g, _x, _y = extended_euclid(a, b)\n'
                        '        smallest = None\n'
                        '        for x in range(-40, 41):\n'
                        '            for y in range(-40, 41):\n'
                        '                value = a * x + b * y\n'
                        '                if value > 0 and (smallest is None or value < smallest):\n'
                        '                    smallest = value\n'
                        '        if smallest != g:\n'
                        '            minimal_ok = False\n'
                        '            minimal_detail = f"a={a}, b={b}: least positive combination {smallest} != g={g}"\n'
                        '            break\n'
                        '    if not minimal_ok:\n'
                        '        break\n'
                        'check("gcd_is_the_least_positive_combination", minimal_ok,\n'
                        '      minimal_detail or "625 pairs, combination range exhausted for each")',
                        '# The set of integer combinations of a and b is exactly the set of\n'
                        '# multiples of their gcd, so the least positive one is the gcd itself.\n'
                        '# Searching the combinations would only reproduce that fact.\n'
                        'minimal_ok = True\n'
                        'check("gcd_is_the_least_positive_combination", minimal_ok,\n'
                        '      "the combinations are exactly the multiples of g")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "sm_two_level_schottky",
        "domain": "statistical_mechanics",
        "objective": (
            "Establish the two-level partition function, its mean energy, and "
            "that the heat capacity has an interior maximum."
        ),
        "intuition": (
            "Z = 1 + exp(-beta eps) gives <E> = eps/(exp(beta eps) + 1), and the "
            "heat capacity vanishes at both temperature limits, peaking between."
        ),
        "defects": [
            {
                "suffix": "grid_peak",
                "primary": "proxy_continuity",
                "labels": ["proxy_continuity", "sampling_as_proof"],
                "severity": "critical",
                "note": (
                    "the maximum is taken as the largest value on a grid, which "
                    "cannot distinguish a peak from a sampling artefact"
                ),
                "patches": [
                    (
                        'mp.mp.dps = 40\n'
                        'stationary_fn = sp.lambdify(x, stationary, "mpmath")\n'
                        'root = mp.findroot(stationary_fn, mp.mpf("2.4"))\n'
                        'second = sp.lambdify(x, sp.diff(shape, x, 2), "mpmath")(root)\n'
                        '\n'
                        'check("stationary_point_located",\n'
                        '      abs(mp.mpf(stationary_fn(root))) < mp.mpf("1e-30"),\n'
                        '      f"dC/dx = {mp.nstr(abs(stationary_fn(root)), 4)} at x = {mp.nstr(root, 12)}")\n'
                        'check("stationary_point_is_a_maximum", bool(second < 0),\n'
                        '      f"second derivative there = {mp.nstr(second, 6)} < 0")',
                        '# A fine grid locates the peak well enough; solving the stationarity\n'
                        '# condition and checking a second derivative adds nothing the scan\n'
                        '# does not already show.\n'
                        'grid = [mp.mpf(j) / 100 for j in range(1, 601)]\n'
                        'shape_fn = sp.lambdify(x, shape, "mpmath")\n'
                        'root = max(grid, key=shape_fn)\n'
                        'check("stationary_point_located", True,\n'
                        '      f"largest grid value at x = {mp.nstr(root, 12)}")\n'
                        'check("stationary_point_is_a_maximum", True,\n'
                        '      "it is the largest value sampled")',
                    ),
                    (
                        'check("peak_is_at_the_known_schottky_value",\n'
                        '      abs(root - mp.mpf("2.399357280074")) < mp.mpf("1e-9"),\n'
                        '      f"x_peak = {mp.nstr(root, 12)}")',
                        '# The grid spacing is 0.01, so agreement to two decimals is all that\n'
                        '# can be expected and all that is required here.\n'
                        'check("peak_is_at_the_known_schottky_value",\n'
                        '      abs(root - mp.mpf("2.399357280074")) < mp.mpf("1e-2"),\n'
                        '      f"x_peak = {mp.nstr(root, 12)}")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "gr_light_deflection",
        "domain": "general_relativity",
        "objective": (
            "Establish that general relativity deflects starlight by twice the "
            "Newtonian amount, and evaluate it for the Sun."
        ),
        "intuition": (
            "The Schwarzschild null geodesic gives 4 G M / (c^2 b) to first "
            "order, exactly double the Newtonian value, 1.75 arcsec at the Sun."
        ),
        "defects": [
            {
                "suffix": "quoted_solution",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the perturbative solution is declared correct in a comment "
                    "instead of being substituted back into its equation"
                ),
                "patches": [
                    (
                        'first_order_lhs = sp.simplify(sp.diff(u1, phi, 2) + u1)\n'
                        'first_order_rhs = sp.simplify(3 * u0**2)\n'
                        'check("first_order_particular_solution_is_correct",\n'
                        '      sp.simplify(sp.expand_trig(first_order_lhs - first_order_rhs)) == 0,\n'
                        '      f"u1\'\' + u1 = {sp.simplify(first_order_lhs)} = 3 u0^2")',
                        '# u1 = (1 + cos^2 phi)/b^2 is the standard particular solution of\n'
                        '# u1\'\' + u1 = 3 u0^2, given in every textbook treatment of light\n'
                        '# bending, so substituting it back would only restate the reference.\n'
                        'check("first_order_particular_solution_is_correct", True,\n'
                        '      "standard textbook particular solution")',
                    ),
                    (
                        'u_full = u0 + eps * u1\n'
                        'residual = sp.expand(\n'
                        '    sp.diff(u_full, phi, 2) + u_full - 3 * eps * u_full**2\n'
                        ')\n'
                        'first_order_residual = sp.simplify(sp.expand_trig(residual.coeff(eps, 1)))\n'
                        'check("residual_vanishes_at_first_order", first_order_residual == 0,\n'
                        '      f"coefficient of the order parameter = {first_order_residual}")',
                        '# The combination therefore solves the full equation to first order.\n'
                        'check("residual_vanishes_at_first_order", True,\n'
                        '      "follows from the two orders above")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "co_binomial_identities",
        "domain": "combinatorics",
        "objective": (
            "Establish Pascal's rule, the row sums, Vandermonde's convolution "
            "and the hockey stick identity for binomial coefficients."
        ),
        "intuition": (
            "All four identities hold, and each is checked against a Pascal "
            "triangle built by addition alone rather than by factorials."
        ),
        "defects": [
            {
                "suffix": "same_source",
                "primary": "self_comparison",
                "labels": ["self_comparison"],
                "severity": "critical",
                "note": (
                    "the triangle is filled from the library it is supposed to "
                    "corroborate, so the agreement leg compares it with itself"
                ),
                "patches": [
                    (
                        'def build_triangle(rows):\n'
                        '    """Pascal\'s triangle by addition only. No factorials, no library calls."""\n'
                        '    triangle = [[1]]\n'
                        '    for row_index in range(1, rows):\n'
                        '        previous = triangle[-1]\n'
                        '        row = [1]\n'
                        '        for position in range(1, row_index):\n'
                        '            row.append(previous[position - 1] + previous[position])\n'
                        '        row.append(1)\n'
                        '        triangle.append(row)\n'
                        '    return triangle',
                        'def build_triangle(rows):\n'
                        '    """Pascal\'s triangle, filled from the library for speed and clarity."""\n'
                        '    return [\n'
                        '        [int(sp.binomial(row_index, position))\n'
                        '         for position in range(row_index + 1)]\n'
                        '        for row_index in range(rows)\n'
                        '    ]',
                    ),
                ],
            },
        ],
    },
    {
        "base": "dy_logistic_period_doubling",
        "domain": "dynamical_systems",
        "objective": (
            "Establish the fixed points of the logistic map, their stability "
            "window, and the period doubling at r = 3."
        ),
        "intuition": (
            "The nonzero fixed point 1 - 1/r is stable exactly for 1 < r < 3, "
            "and a two-cycle is born as the multiplier passes through -1."
        ),
        "defects": [
            {
                "suffix": "cycle_everywhere",
                "primary": "missing_domain",
                "labels": ["missing_domain", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the two-cycle is claimed for every r, dropping the "
                    "discriminant condition that makes its roots real"
                ),
                "patches": [
                    (
                        'discriminant = sp.simplify(sp.discriminant(\n'
                        '    sp.Poly(x**2 - (1 + 1 / r) * x + (1 + 1 / r) / r, x)\n'
                        '))\n'
                        'birth = sp.solve(sp.Eq(discriminant, 0), r)\n'
                        'check("two_cycle_is_born_exactly_at_r_three",\n'
                        '      3 in [sp.simplify(value) for value in birth],\n'
                        '      f"discriminant {sp.factor(discriminant)} vanishes at r = {birth}")',
                        '# The quadratic always has two roots, so the two-cycle exists for every\n'
                        '# value of r and there is no threshold to locate.\n'
                        'check("two_cycle_is_born_exactly_at_r_three", True,\n'
                        '      "the quadratic always factors, so the orbit is always present")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "nu_newton_quadratic_convergence",
        "domain": "numerical_analysis",
        "objective": (
            "Establish that Newton's method converges quadratically at a simple "
            "root with the asymptotic constant f''(a)/(2 f'(a))."
        ),
        "intuition": (
            "The Newton error satisfies e_(n+1) = (f''/2f') e_n^2 at a simple "
            "root, and degrades to linear with ratio 1/2 at a double root."
        ),
        "defects": [
            {
                "suffix": "slack_order",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance"],
                "severity": "critical",
                "note": (
                    "the order tolerance is widened until a first-order method "
                    "would also pass, so the leg stops distinguishing rates"
                ),
                "patches": [
                    (
                        'check("measured_order_is_two",\n'
                        '      abs(exponent - 2) < mp.mpf("1e-3"),',
                        '# Floating-point iteration is noisy near the root, so the order estimate\n'
                        '# is given room rather than being held to three decimals.\n'
                        'check("measured_order_is_two",\n'
                        '      abs(exponent - 2) < mp.mpf("1.5"),',
                    ),
                    (
                        'check("measured_constant_matches_the_prediction",\n'
                        '      abs(measured - predicted) < mp.mpf("1e-10"),',
                        'check("measured_constant_matches_the_prediction",\n'
                        '      abs(measured - predicted) < mp.mpf("1e-1"),',
                    ),
                ],
            },
        ],
    },
    {
        "base": "op_lagrange_multipliers",
        "domain": "optimization",
        "objective": (
            "Establish the constrained maximum of x*y on x + y = s and show the "
            "multiplier is the derivative of the optimal value."
        ),
        "intuition": (
            "The maximum is x = y = s/2 with value s^2/4, and the multiplier "
            "equals dF*/ds, which is the envelope theorem."
        ),
        "defects": [
            {
                "suffix": "one_route",
                "primary": "self_comparison",
                "labels": ["self_comparison", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the second route is replaced by the first one's answer, so "
                    "the cross-check compares a result with itself"
                ),
                "patches": [
                    (
                        'reduced = sp.simplify(objective.subs(y, s - x))\n'
                        'critical = sp.solve(sp.Eq(sp.diff(reduced, x), 0), x)',
                        '# Substitution must land on the same point the multipliers already gave,\n'
                        '# so the critical point is taken from there instead of re-solving.\n'
                        'reduced = sp.simplify(objective.subs(y, s - x))\n'
                        'critical = [solution[x]]',
                    ),
                ],
            },
        ],
    },
    {
        "base": "in_shannon_entropy_maximum",
        "domain": "information_theory",
        "objective": (
            "Establish that Shannon entropy is maximised by the uniform "
            "distribution with maximum log n."
        ),
        "intuition": (
            "H(p) = -sum p log p is bounded by log n, attained only by the "
            "uniform distribution, which follows from Gibbs' inequality."
        ),
        "defects": [
            {
                "suffix": "sampled_bound",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "assumed_bound"],
                "severity": "critical",
                "note": (
                    "the Gibbs derivation is dropped and the universal bound is "
                    "left to twenty thousand random draws"
                ),
                "patches": [
                    (
                        'gap = sp.simplify(t - 1 - sp.log(t))\n'
                        'stationary_points = sp.solve(sp.Eq(sp.diff(gap, t), 0), t)\n'
                        'check("log_bound_has_its_only_stationary_point_at_one",\n'
                        '      stationary_points == [1],\n'
                        '      f"d/dt (t - 1 - log t) vanishes at t = {stationary_points}")\n'
                        '\n'
                        'check("that_point_is_a_minimum_of_the_gap",\n'
                        '      bool(sp.diff(gap, t, 2).subs(t, 1) > 0),\n'
                        '      f"second derivative at t = 1 is {sp.diff(gap, t, 2).subs(t, 1)}, positive")\n'
                        '\n'
                        'check("the_gap_vanishes_there_and_only_there",\n'
                        '      sp.simplify(gap.subs(t, 1)) == 0,\n'
                        '      "so log t = t - 1 exactly at t = 1 and log t < t - 1 elsewhere")',
                        '# The bound log t <= t - 1 is elementary and the sampling below covers\n'
                        '# the distribution space densely, so working through its equality case\n'
                        '# adds nothing the numbers do not already show.\n'
                        'check("log_bound_has_its_only_stationary_point_at_one", True,\n'
                        '      "standard elementary inequality")\n'
                        'check("that_point_is_a_minimum_of_the_gap", True,\n'
                        '      "standard elementary inequality")\n'
                        'check("the_gap_vanishes_there_and_only_there", True,\n'
                        '      "standard elementary inequality")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ch_arrhenius_linearisation",
        "domain": "chemical_kinetics",
        "objective": (
            "Establish that Arrhenius rates are exactly linear in 1/T and that "
            "the ten-degree doubling rule holds only at one activation energy."
        ),
        "intuition": (
            "ln k against 1/T has slope -Ea/R exactly, and k(T+10)/k(T) = 2 "
            "fixes Ea rather than holding generally."
        ),
        "defects": [
            {
                "suffix": "rule_of_thumb",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "missing_domain"],
                "severity": "critical",
                "note": (
                    "the doubling rule is taken as general instead of being "
                    "solved, and the case where it fails is deleted"
                ),
                "patches": [
                    (
                        'required = sp.solve(sp.Eq(ratio, 2), Ea)\n'
                        'check("doubling_requires_one_specific_activation_energy",\n'
                        '      len(required) == 1,\n'
                        '      f"k(T+10)/k(T) = 2 forces Ea = {sp.simplify(required[0])}")',
                        '# A ten-degree rise roughly doubles reaction rates, which is standard\n'
                        '# laboratory practice, so there is nothing to solve for here.\n'
                        'required = [sp.Rational(52900)]\n'
                        'check("doubling_requires_one_specific_activation_energy", True,\n'
                        '      "the ten-degree rule is general laboratory experience")',
                    ),
                    (
                        'actual_ratio = math.exp(-EA_TRUE / (R_SI * 308)) / math.exp(-EA_TRUE / (R_SI * 298))\n'
                        'check("rule_of_thumb_fails_away_from_that_value",\n'
                        '      abs(actual_ratio - 2) > 0.5,\n'
                        '      f"at Ea = {EA_TRUE:.0f} J/mol a ten-degree rise multiplies the rate by "\n'
                        '      f"{actual_ratio:.3f}, not 2")',
                        '# The rule applies across the usual range of activation energies.\n'
                        'check("rule_of_thumb_fails_away_from_that_value", True,\n'
                        '      "the rule is taken to hold generally")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "sig_nyquist_aliasing",
        "domain": "signal_processing",
        "objective": (
            "Establish the aliasing identities for a sampled cosine and the "
            "recovery of a band-limited tone by sinc interpolation."
        ),
        "intuition": (
            "Frequencies separated by the sampling rate, and reflections about "
            "it, give identical samples; below Nyquist distinct tones separate."
        ),
        "defects": [
            {
                "suffix": "fixed_tolerance",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance", "proxy_continuity"],
                "severity": "critical",
                "note": (
                    "the convergence demonstration is replaced by a single "
                    "tolerance loose enough to hide a failure of reconstruction"
                ),
                "patches": [
                    (
                        'small = centre_error(1024)\n'
                        'large = max(errors)\n'
                        'check("sinc_interpolation_reproduces_a_band_limited_tone",\n'
                        '      large < small and large < 1e-5,\n'
                        '      f"error falls from {small:.3e} at 1024 samples to {large:.3e} at {COUNT}, "\n'
                        '      "so the residual is window truncation and not a failure of the theorem")',
                        '# One window is enough; interpolation error is small and comparing two\n'
                        '# window sizes only costs time.\n'
                        'large = max(errors)\n'
                        'check("sinc_interpolation_reproduces_a_band_limited_tone",\n'
                        '      large < 1e-1,\n'
                        '      f"reconstruction error {large:.3e}, within tolerance")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "me_euler_buckling",
        "domain": "structural_mechanics",
        "objective": (
            "Establish the Euler buckling spectrum for a pinned column and "
            "derive the clamped-clamped factor from its boundary conditions."
        ),
        "intuition": (
            "Non-trivial shapes exist only at P = n^2 pi^2 EI / L^2, and "
            "clamping both ends raises the critical load by four."
        ),
        "defects": [
            {
                "suffix": "effective_length",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "self_comparison"],
                "severity": "critical",
                "note": (
                    "the clamped factor is recovered by squaring an assumed "
                    "effective length instead of solving the boundary problem"
                ),
                "patches": [
                    (
                        'conditions = [\n'
                        '    clamped.subs(x, 0),\n'
                        '    sp.diff(clamped, x).subs(x, 0),\n'
                        '    clamped.subs(x, L),\n'
                        '    sp.diff(clamped, x).subs(x, L),\n'
                        ']\n'
                        'coefficient_matrix = sp.Matrix([\n'
                        '    [sp.expand(condition).coeff(coefficient) for coefficient in (C1, C2, C3, C4)]\n'
                        '    for condition in conditions\n'
                        '])\n'
                        'determinant = sp.simplify(sp.trigsimp(coefficient_matrix.det()))\n'
                        'check("clamped_boundary_determinant_is_the_eigenvalue_condition",\n'
                        '      sp.simplify(determinant\n'
                        '                  - kk * (L * kk * sp.sin(L * kk) + 2 * sp.cos(L * kk) - 2)) == 0,\n'
                        '      f"det = {sp.factor(determinant)}, whose zeros are the buckling loads")',
                        '# The clamped column has effective length L/2, which is standard, so the\n'
                        '# determinant does not need to be assembled: the factor follows from\n'
                        '# squaring the effective length.\n'
                        'determinant = kk * (L * kk * sp.sin(L * kk) + 2 * sp.cos(L * kk) - 2)\n'
                        'check("clamped_boundary_determinant_is_the_eigenvalue_condition", True,\n'
                        '      "effective length L/2, as tabulated")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ep_sir_threshold",
        "domain": "epidemiology",
        "objective": (
            "Establish the SIR epidemic threshold, the location of the peak, "
            "and the final-size relation."
        ),
        "intuition": (
            "Infections grow only when R0 S(0)/N exceeds one, the peak sits at "
            "S = gN/b, and the final susceptible fraction solves a "
            "transcendental equation."
        ),
        "defects": [
            {
                "suffix": "simulated_threshold",
                "primary": "proxy_continuity",
                "labels": ["proxy_continuity", "sampling_as_proof"],
                "severity": "critical",
                "note": (
                    "the threshold and the peak are read off one simulation "
                    "instead of being solved, so the conditions are never derived"
                ),
                "patches": [
                    (
                        'condition = sp.solve(sp.Eq(b * S0 / N - g, 0), S0)\n'
                        'check("growth_changes_sign_at_S_equals_gN_over_b",\n'
                        '      len(condition) == 1 and sp.simplify(condition[0] - g * N / b) == 0,\n'
                        '      f"I\'(0) = 0 at S_0 = {condition[0] if condition else \'none\'}")',
                        '# The threshold is visible in the simulations below, where one run grows\n'
                        '# and the other does not, so solving for the crossing adds nothing.\n'
                        'condition = [g * N / b]\n'
                        'check("growth_changes_sign_at_S_equals_gN_over_b", True,\n'
                        '      "confirmed by the two simulations further down")',
                    ),
                    (
                        'peak = sp.solve(sp.Eq(dI, 0), S)\n'
                        'non_trivial = [value for value in peak if sp.simplify(value) != 0]\n'
                        'check("peak_condition_solves_to_a_single_susceptible_level",\n'
                        '      len(non_trivial) == 1,\n'
                        '      f"I\' = 0 at S = {non_trivial}")',
                        '# The simulation records where the peak occurred, which is the same\n'
                        '# information the algebra would produce.\n'
                        'non_trivial = [g * N / b]\n'
                        'check("peak_condition_solves_to_a_single_susceptible_level", True,\n'
                        '      "taken from the recorded peak of the simulation")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "cm_kepler_orbit",
        "domain": "classical_mechanics",
        "objective": (
            "Derive the Kepler orbit from the Lagrangian and show that closure "
            "belongs to the inverse square law rather than to the integrator."
        ),
        "intuition": (
            "The angle is cyclic, so r^2 thetadot is constant; in u = 1/r the "
            "radial equation is a linear oscillator whose period gives Kepler's "
            "third law, and a 1/r^3 term shifts the frequency and opens the orbit."
        ),
        "defects": [
            {
                "suffix": "period_from_the_formula",
                "primary": "self_comparison",
                "labels": ["self_comparison", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the period said to be measured by integration is assigned "
                    "from the analytic prediction, so the numeric leg compares "
                    "Kepler's third law with itself"
                ),
                "patches": [
                    (
                        'measured_period, measured_angle = integrate(0.0, ONE_TURN_STEPS)',
                        '# The conic is exact, so the period it predicts is cleaner than the\n'
                        '# integrated one; the integration is kept for the periapsis angle.\n'
                        'measured_period = predicted_period\n'
                        '_integrated_period, measured_angle = integrate(0.0, ONE_TURN_STEPS)',
                    ),
                ],
            },
            {
                "suffix": "retyped_radial_equation",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "missing_assumption"],
                "severity": "major",
                "note": (
                    "the orbit equation is transformed from a retyped copy of the "
                    "radial equation instead of from the one the Lagrangian "
                    "produced, so the whole first leg is decorative and a wrong "
                    "potential upstream would never reach any later check"
                ),
                "patches": [
                    (
                        '# The equation transformed here is the one leg 1 DERIVED, not a retyped\n'
                        '# copy of it. Substituting the three atoms is what carries the Lagrangian\n'
                        '# into this leg, so a wrong potential upstream shows up as a wrong orbit\n'
                        '# equation here instead of being quietly re-entered correctly.\n'
                        'radial_law = sp.simplify(radial_el)\n'
                        'residual = sp.simplify(radial_law.subs([\n'
                        '    (sp.Derivative(r_t, t, 2), radial_acceleration),\n'
                        '    (sp.Derivative(theta_t, t), angular_speed),\n'
                        '    (r_t, radius),\n'
                        ']))',
                        '# The radial equation derived in leg 1, written out in u.\n'
                        'residual = sp.simplify(\n'
                        '    radial_acceleration - radius * angular_speed ** 2 + GM / radius ** 2\n'
                        ')',
                    ),
                ],
            },
        ],
    },
    {
        "base": "st_cramer_rao_bound",
        "domain": "statistics",
        "objective": (
            "Show that the sample mean attains the Cramer-Rao bound and that a "
            "biased estimator can sit below it without contradicting the theorem."
        ),
        "intuition": (
            "The score equation solves to the sample mean, the information is "
            "n/sigma^2 by both definitions, and the bound constrains unbiased "
            "estimators only, which is the hypothesis usually left unsaid."
        ),
        "defects": [
            {
                "suffix": "unbiasedness_assumed",
                "primary": "missing_assumption",
                "labels": ["missing_assumption", "missing_domain"],
                "severity": "critical",
                "note": (
                    "unbiasedness is declared to hold for any average of the "
                    "observations, which is false and is exactly what the last "
                    "leg contradicts, and the check that would have caught it is "
                    "replaced by a constant"
                ),
                "patches": [
                    (
                        'estimator_pair = (draws[0] + draws[1]) / 2\n'
                        'check("the_two_observation_average_is_also_unbiased",\n'
                        '      sp.simplify(expectation(estimator_pair) - mu) == 0,\n'
                        '      f"E[mu_pair] = {sp.simplify(expectation(estimator_pair))}")',
                        '# Any average of the observations is unbiased, so the bound applies to\n'
                        '# all of them and the expectation need not be recomputed each time.\n'
                        'estimator_pair = (draws[0] + draws[1]) / 2\n'
                        'check("the_two_observation_average_is_also_unbiased", True,\n'
                        '      "an average of observations is unbiased by construction")',
                    ),
                ],
            },
            {
                "suffix": "targets_from_the_simulation",
                "primary": "self_comparison",
                "labels": ["self_comparison", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the exact variances the simulation is compared against are "
                    "read off that same simulation, so both agreement checks "
                    "compare a number with itself and the symbolic results are "
                    "never tested against anything"
                ),
                "patches": [
                    (
                        'exact_mean_variance = as_float(variance_mean.subs({sigma: SIGMA_TRUE}))\n'
                        'exact_pair_variance = as_float(variance_pair.subs({sigma: SIGMA_TRUE}))',
                        '# Taking the targets from the simulation itself avoids any mismatch of\n'
                        '# parameterisation between the symbolic variance and the simulated one.\n'
                        '_, exact_mean_variance = moments(means)\n'
                        '_, exact_pair_variance = moments(pairs)',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ot_fresnel_brewster",
        "domain": "optics",
        "objective": (
            "Derive the Fresnel coefficients from the boundary conditions and "
            "show that energy balances only with the obliquity factor."
        ),
        "intuition": (
            "Continuity of the tangential fields fixes the amplitudes, the "
            "p-amplitude vanishes at tan(theta) = n2/n1, and the transmitted "
            "power carries n2 cos(theta_t) / (n1 cos(theta_i))."
        ),
        "defects": [
            {
                "suffix": "cosines_dropped",
                "primary": "wrong_units",
                "labels": ["wrong_units", "sampling_as_proof"],
                "severity": "critical",
                "note": (
                    "the obliquity factor keeps the index ratio but loses the "
                    "cosines, which is exactly right at normal incidence and "
                    "wrong everywhere else, and the energy checks are evaluated "
                    "only at normal incidence where the error cannot show"
                ),
                "patches": [
                    (
                        'obliquity = n2 * cos_t / (n1 * cos_i)\n'
                        'energy_s = sp.simplify(r_s ** 2 + obliquity * t_s ** 2)\n'
                        'check("the_s_polarisation_conserves_energy_with_the_obliquity_factor",\n'
                        '      sp.simplify(energy_s - 1) == 0,\n'
                        '      f"R_s + T_s = {energy_s}")\n'
                        '\n'
                        'energy_p = sp.simplify(r_p ** 2 + obliquity * t_p ** 2)\n'
                        'check("the_p_polarisation_conserves_energy_with_the_obliquity_factor",\n'
                        '      sp.simplify(energy_p - 1) == 0,\n'
                        '      f"R_p + T_p = {energy_p}")',
                        '# The cosines cancel between the incident and transmitted sides, leaving\n'
                        '# only the index ratio, and the balance is confirmed numerically.\n'
                        'obliquity = n2 / n1\n'
                        'NORMAL = {n1: 1, n2: sp.Rational(3, 2), cos_i: 1, cos_t: 1}\n'
                        'energy_s = sp.simplify(r_s ** 2 + obliquity * t_s ** 2)\n'
                        'check("the_s_polarisation_conserves_energy_with_the_obliquity_factor",\n'
                        '      abs(float(energy_s.subs(NORMAL)) - 1) < 1e-12,\n'
                        '      f"R_s + T_s = {float(energy_s.subs(NORMAL)):.12f}")\n'
                        '\n'
                        'energy_p = sp.simplify(r_p ** 2 + obliquity * t_p ** 2)\n'
                        'check("the_p_polarisation_conserves_energy_with_the_obliquity_factor",\n'
                        '      abs(float(energy_p.subs(NORMAL)) - 1) < 1e-12,\n'
                        '      f"R_p + T_p = {float(energy_p.subs(NORMAL)):.12f}")',
                    ),
                ],
            },
            {
                "suffix": "brewster_quoted",
                "primary": "self_comparison",
                "labels": ["self_comparison", "hardcoded_pass"],
                "severity": "critical",
                "note": (
                    "the Brewster root is written in by hand instead of solved "
                    "from the amplitude, so the numerator is computed and never "
                    "used and both checks compare the quoted formula with itself"
                ),
                "patches": [
                    (
                        'roots = sp.solve(sp.Eq(p_numerator, 0), tangent)',
                        '# The Brewster condition is standard and the numerator above reproduces\n'
                        '# it, so the root is taken directly rather than solved for again.\n'
                        'roots = [n2 / n1]',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ct_lyapunov_stability",
        "domain": "control_theory",
        "objective": (
            "Tie linear stability, the Routh-Hurwitz conditions and the Lyapunov "
            "equation together, and show the Lyapunov construction failing "
            "quietly on an unstable system."
        ),
        "intuition": (
            "A stable A gives a unique positive definite P; an unstable A gives a "
            "unique indefinite one without complaint; and eigenvalues summing to "
            "zero leave the equation with no solution at all."
        ),
        "defects": [
            {
                "suffix": "undecided_counts_as_definite",
                "primary": "unknown_as_pass",
                "labels": ["unknown_as_pass", "undecidable_positivity"],
                "severity": "critical",
                "note": (
                    "the definiteness test accepts an undecided sign as a pass, "
                    "so a P whose minors sympy cannot resolve would be certified "
                    "as a Lyapunov function; the case still passes because this "
                    "particular P is decidable"
                ),
                "patches": [
                    (
                        'check("that_solution_is_positive_definite",\n'
                        '      leading.is_positive is True and determinant.is_positive is True,\n'
                        '      f"leading minor {leading}, determinant {determinant}, both positive")',
                        '# is_positive returns None when the sign cannot be settled, and a None\n'
                        '# there means nothing has been found against the matrix.\n'
                        'check("that_solution_is_positive_definite",\n'
                        '      leading.is_positive is not False\n'
                        '      and determinant.is_positive is not False,\n'
                        '      f"leading minor {leading}, determinant {determinant}, nothing "\n'
                        '      "found against either")',
                    ),
                ],
            },
            {
                "suffix": "residual_waved_through",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance", "link_in_comment"],
                "severity": "major",
                "note": (
                    "the model that predicts the residual of the decay rate is "
                    "dropped for a band twenty times larger and a comment saying "
                    "the residual is understood, so the contamination is asserted "
                    "rather than measured and the second window is never used"
                ),
                "patches": [
                    (
                        'check("the_residual_is_the_faster_mode_rather_than_numerical_noise",\n'
                        '      abs(late_gap / mode_contamination(7000, 9000) - 1) < 1e-3,\n'
                        '      f"gap {late_gap:.6e} against the predicted contamination "\n'
                        '      f"{mode_contamination(7000, 9000):.6e}, agreeing to "\n'
                        '      f"{abs(late_gap / mode_contamination(7000, 9000) - 1):.2e}")\n'
                        '\n'
                        'early_gap = 2 * slowest - decay_rate(2000, 4000)\n'
                        'shrinkage = early_gap / late_gap\n'
                        'predicted_shrinkage = mode_contamination(2000, 4000) / mode_contamination(7000, 9000)\n'
                        'check("moving_the_window_later_shrinks_the_residual_as_predicted",\n'
                        '      abs(shrinkage / predicted_shrinkage - 1) < 0.05,\n'
                        '      f"the gap falls by a factor {shrinkage:.1f} between the windows and the "\n'
                        '      f"model asks for {predicted_shrinkage:.1f}")',
                        '# The residual is the faster mode, which is well understood, so a band of\n'
                        '# one percent is generous enough and the comparison against the model\n'
                        '# adds nothing.\n'
                        'check("the_residual_is_the_faster_mode_rather_than_numerical_noise",\n'
                        '      abs(late_gap) < 1e-2,\n'
                        '      f"gap {late_gap:.6e}, inside the expected band")\n'
                        'check("moving_the_window_later_shrinks_the_residual_as_predicted", True,\n'
                        '      "a later window is closer, as the mode structure requires")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "nl_residual_and_conditioning",
        "domain": "numerical_linear_algebra",
        "objective": (
            "Show that a small residual certifies nothing and that the condition "
            "number is exactly how little it certifies."
        ),
        "intuition": (
            "The error is A^-1 times the residual, so the amplification is the "
            "condition number, the bound is attained, and on the Hilbert matrix "
            "a residual at the rounding floor sits beside an error eight orders "
            "larger."
        ),
        "defects": [
            {
                "suffix": "residual_as_certificate",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the leg that exists to refute the residual as a certificate "
                    "instead treats it as one, so the error of the Hilbert solve "
                    "is never compared with anything and the case asserts the "
                    "opposite of what it set out to show"
                ),
                "patches": [
                    (
                        'check("falsifier_the_error_is_many_orders_larger_than_the_residual",\n'
                        '      bool(float_error > 1e6 * float_leftover),\n'
                        '      f"relative error {float_error:.3e} against residual {float_leftover:.3e}, "\n'
                        '      f"a factor of {float_error / float_leftover:.3e}; the residual certifies "\n'
                        '      "nothing on its own")',
                        '# The residual sits at the rounding floor, so the solve is as accurate as\n'
                        '# double precision allows and the error needs no separate check.\n'
                        'check("falsifier_the_error_is_many_orders_larger_than_the_residual", True,\n'
                        '      f"residual {float_leftover:.3e} at the rounding floor, which is what "\n'
                        '      "a backward stable elimination guarantees")',
                    ),
                ],
            },
            {
                "suffix": "arbitrary_contrast_direction",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "missing_domain"],
                "severity": "critical",
                "note": (
                    "the well-conditioned contrast puts the residual in an "
                    "arbitrary direction instead of the worst one, so the small "
                    "error it finds would also appear on an ill-conditioned "
                    "matrix that the direction happened to miss, and the leg "
                    "stops being about conditioning at all"
                ),
                "patches": [
                    (
                        '# The residual goes along the worst direction for THIS matrix. A residual in an\n'
                        '# arbitrary direction would leave the error small on an ill-conditioned matrix\n'
                        '# too, purely by missing the bad direction, and the check would then be about\n'
                        '# the choice of perturbation rather than about the conditioning.\n'
                        'tame_left, _, _ = np.linalg.svd(tame)\n'
                        'tame_approximation = tame_truth - np.linalg.solve(tame, 1e-14 * tame_left[:, -1])',
                        '# Any residual of this size serves for the comparison.\n'
                        'tame_approximation = tame_truth - np.linalg.solve(tame, 1e-14 * np.array([1.0, 1.0]))',
                    ),
                    (
                        '      bool(tame_error < 5 * tame_leftover),',
                        '      bool(tame_error < 100 * tame_leftover),',
                    ),
                ],
            },
        ],
    },
    {
        "base": "dg_gauss_bonnet",
        "domain": "differential_geometry",
        "objective": (
            "Verify Gauss-Bonnet on a sphere, an ellipsoid and a torus, and show "
            "that the closed-surface form fails on a surface with boundary."
        ),
        "intuition": (
            "Total curvature is 2 pi chi, so it survives deforming a sphere into "
            "an ellipsoid and vanishes on a torus by cancellation; a cap needs "
            "the geodesic curvature of its edge before the identity holds."
        ),
        "defects": [
            {
                "suffix": "branch_taken_on_faith",
                "primary": "missing_assumption",
                "labels": ["missing_assumption", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the positive branch of the torus area element is asserted "
                    "with a false justification, a square root of a square being "
                    "the absolute value rather than the thing itself, and the "
                    "embedding condition that actually picks the branch is gone"
                ),
                "patches": [
                    (
                        'check("the_positive_branch_of_the_area_element_is_the_right_one",\n'
                        '      sp.simplify(torus_area ** 2 - torus_area_raw ** 2) == 0,\n'
                        '      f"the assumed element {torus_area} squares to the same first fundamental "\n'
                        '      f"form as {torus_area_raw}, and R > r makes it the positive branch")',
                        'check("the_positive_branch_of_the_area_element_is_the_right_one", True,\n'
                        '      "a square root of a square is the thing itself")',
                    ),
                ],
            },
            {
                "suffix": "single_grid",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "link_in_comment"],
                "severity": "major",
                "note": (
                    "the ellipsoid integral is evaluated on one grid and the "
                    "convergence demonstration is replaced by an appeal to "
                    "spectral accuracy in a comment, so nothing in the case "
                    "distinguishes a converged answer from a lucky grid"
                ),
                "patches": [
                    (
                        'coarse, fine = quadrature(40), quadrature(80)',
                        '# One grid suffices: Gauss-Legendre is spectrally accurate on a smooth\n'
                        '# integrand, so a second grid would only restate the theory.\n'
                        'fine = quadrature(40)',
                    ),
                    (
                        'check("and_the_quadrature_is_converged_rather_than_merely_close",\n'
                        '      bool(abs(fine - 4 * math.pi) < abs(coarse - 4 * math.pi) / 10),\n'
                        '      f"the error falls from {abs(coarse - 4 * math.pi):.3e} at 40 nodes to "\n'
                        '      f"{abs(fine - 4 * math.pi):.3e} at 80, so the agreement is the limit and "\n'
                        '      "not a coincidence of the grid")',
                        'check("and_the_quadrature_is_converged_rather_than_merely_close", True,\n'
                        '      "spectral accuracy on a smooth integrand")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "cy_fermat_test_and_carmichael",
        "domain": "cryptography",
        "objective": (
            "Show that the Fermat primality test has an unreachable failure "
            "branch on Carmichael numbers and that Miller-Rabin does not."
        ),
        "intuition": (
            "The bases that fail to expose n form a subgroup of the units, "
            "proper for an ordinary composite and the whole group for a "
            "Carmichael number, which is why retrying more bases cannot help."
        ),
        "defects": [
            {
                "suffix": "sampled_bases",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "proxy_continuity"],
                "severity": "critical",
                "note": (
                    "the claim that EVERY unit lies is drawn from a strided "
                    "subsample of a hundred bases, which cannot establish a "
                    "statement about the whole group; the conclusion happens to "
                    "be true, so nothing in the run exposes the reasoning"
                ),
                "patches": [
                    (
                        'for candidate in CARMICHAELS:\n'
                        '    total = len(units(candidate))\n'
                        '    liars = fermat_liars(candidate)\n'
                        '    check(f"the_liars_modulo_{candidate}_are_every_last_unit",\n'
                        '          len(liars) == total,\n'
                        '          f"all {total} units lie, so the subgroup is the whole group, there is "\n'
                        '          "no witness to find and retrying with more bases cannot help")',
                        '# Walking every unit is wasteful when a spread of a hundred bases settles it.\n'
                        'for candidate in CARMICHAELS:\n'
                        '    total = len(units(candidate))\n'
                        '    sample = units(candidate)[::7][:100]\n'
                        '    liars = [a for a in sample if pow(a, candidate - 1, candidate) == 1]\n'
                        '    check(f"the_liars_modulo_{candidate}_are_every_last_unit",\n'
                        '          len(liars) == len(sample),\n'
                        '          f"all {len(sample)} bases sampled from the {total} units lie, so "\n'
                        '          "every unit does and there is no witness to find")',
                    ),
                ],
            },
            {
                "suffix": "vacuous_prime_control",
                "primary": "unreachable_failure",
                "labels": ["unreachable_failure", "missing_domain"],
                "severity": "major",
                "note": (
                    "the prime control uses a prime whose predecessor carries a "
                    "single factor of two, so the square root chain never runs "
                    "and a Miller-Rabin with that chain deleted would pass the "
                    "control unchanged; the control is present and inert"
                ),
                "patches": [
                    (
                        '# 577 rather than a prime like 563: 562 carries a single factor of two, so the\n'
                        '# square root chain never runs and a Miller-Rabin with that chain deleted would\n'
                        '# still accuse nobody. 576 is 2^6 times 9, so the chain is exercised and the\n'
                        '# control has something to control.\n'
                        'PRIME_CONTROL = 577',
                        '# Any prime serves as the control, so the nearest one below the Carmichael\n'
                        '# numbers is taken.\n'
                        'PRIME_CONTROL = 563',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ap_lane_emden_polytropes",
        "domain": "astrophysics",
        "objective": (
            "Reduce hydrostatic equilibrium to Lane-Emden and show that a "
            "polytrope's radius is finite only below index five."
        ),
        "intuition": (
            "Index one gives sin(xi)/xi with a radius independent of the central "
            "density, index five gives a profile positive everywhere, so the "
            "star is infinite while its mass is not."
        ),
        "defects": [
            {
                "suffix": "regularity_left_implicit",
                "primary": "missing_assumption",
                "labels": ["missing_assumption", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "cos(xi)/xi solves the index one equation exactly as well as "
                    "sin(xi)/xi, and only regularity at the centre excludes it; "
                    "the condition is dropped here, so nothing in the case would "
                    "reject a profile that diverges at the middle of the star"
                ),
                "patches": [
                    (
                        '# Solving the equation is not enough to pick a star. cos(xi)/xi solves it just\n'
                        '# as well and is excluded only by regularity at the centre, so that condition\n'
                        '# is imposed here rather than left implicit in the choice of profile.\n'
                        'rejected = sp.cos(xi) / xi\n'
                        'check("the_discarded_solution_solves_the_equation_too",\n'
                        '      residual_at(1, rejected) == 0,\n'
                        '      f"residual is {residual_at(1, rejected)}, so the equation alone does not choose")\n'
                        '\n'
                        'check("and_regularity_at_the_centre_is_what_chooses_between_them",\n'
                        '      sp.limit(unit_profile, xi, 0) == 1\n'
                        '      and sp.limit(sp.diff(unit_profile, xi), xi, 0) == 0\n'
                        '      and sp.limit(rejected, xi, 0) == sp.oo,\n'
                        '      f"sin(xi)/xi tends to {sp.limit(unit_profile, xi, 0)} with zero slope, "\n'
                        '      "while cos(xi)/xi diverges")',
                        '# The equation determines the profile, so sin(xi)/xi is the index one\n'
                        '# solution and nothing further need be imposed on it.\n'
                        'rejected = sp.cos(xi) / xi\n'
                        'check("the_discarded_solution_solves_the_equation_too", True,\n'
                        '      "the second branch is not the physical one")\n'
                        '\n'
                        'check("and_regularity_at_the_centre_is_what_chooses_between_them", True,\n'
                        '      "sin(xi)/xi is the standard index one profile")',
                    ),
                ],
            },
            {
                "suffix": "one_calibration_case",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "missing_domain"],
                "severity": "critical",
                "note": (
                    "the integrator is calibrated at index one alone, where the "
                    "equation is linear and homogeneous so an error in the "
                    "central value is a pure rescaling and cannot move the zero; "
                    "the one case that would feel such an error is removed, and "
                    "the calibration is blind to the failure it exists to catch"
                ),
                "patches": [
                    (
                        '# Index one alone would not validate the integrator: there the equation is\n'
                        '# linear and homogeneous, so an error in the central value is a pure rescaling\n'
                        '# and cannot move the zero. Index zero carries a source, and does feel one.\n'
                        'flat_located, _ = integrate(0, 5e-4, 20.0)\n'
                        'check("the_integrator_also_reproduces_the_index_zero_zero",\n'
                        '      abs(flat_located - math.sqrt(6)) < 1e-11,\n'
                        '      f"found xi_1 = {flat_located:.13f} against sqrt(6) = {math.sqrt(6):.13f}, "\n'
                        '      f"apart by {abs(flat_located - math.sqrt(6)):.3e}")',
                        '# One closed-form index is calibration enough; the same integrator runs at\n'
                        '# every other index without modification.\n'
                        'flat_located, _ = integrate(0, 5e-4, 20.0)\n'
                        'check("the_integrator_also_reproduces_the_index_zero_zero", True,\n'
                        '      f"index zero gives xi_1 = {flat_located:.6f}")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "al_lagrange_converse",
        "domain": "group_theory",
        "objective": (
            "Verify Lagrange's theorem by the coset partition and exhibit the "
            "failure of its converse in the alternating group on four letters."
        ),
        "intuition": (
            "Cosets partition a group into blocks of equal size, so a subgroup "
            "order divides; the converse fails at order six, because a subgroup "
            "of index two would have to be normal and none of that order is."
        ),
        "defects": [
            {
                "suffix": "strided_search",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the claim is that no subgroup of order six EXISTS, and the "
                    "search is cut to every seventh subset while the comment "
                    "above it still calls it exhaustive; a partial search can "
                    "only fail to find something"
                ),
                "patches": [
                    (
                        '    subset for subset in itertools.combinations(ALTERNATING, 6)\n',
                        '    subset for subset in list(itertools.combinations(ALTERNATING, 6))[::7]\n',
                    ),
                ],
            },
            {
                "suffix": "index_unverified",
                "primary": "unreachable_failure",
                "labels": ["unreachable_failure", "missing_assumption"],
                "severity": "major",
                "note": (
                    "the rule under test is that a subgroup of INDEX TWO is "
                    "normal, and the clause requiring the index to be two is "
                    "dropped, so it passes on subgroups of any index and the "
                    "rule the whole explanation rests on is never exercised"
                ),
                "patches": [
                    (
                        '      and all(len(elements) == 2 * len(group)\n'
                        '              for group, elements, _, _ in index_two_cases)\n',
                        "",
                    ),
                ],
            },
        ],
    },
    {
        "base": "ml_interpolation_and_holdout",
        "domain": "machine_learning",
        "objective": (
            "Show that a training error of zero is forced by the parameter count "
            "and that selecting on a held-out set makes its error optimistic."
        ),
        "intuition": (
            "A polynomial with as many coefficients as points interpolates them "
            "whatever they are; the test error has an interior minimum; and the "
            "winner's curse scales with how noisily the choice is made."
        ),
        "defects": [
            {
                "suffix": "single_split",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the optimism of selecting on a held-out set is asserted from "
                    "ONE split, which reports a convincing five per cent; "
                    "repeated over independent splits at that size the effect is "
                    "half a standard error from zero, so the number is noise"
                ),
                "patches": [
                    (
                        "# Selecting on a held-out set and then quoting that set's error is optimistic,\n"
                        '# but one split cannot establish it and the size of the set decides how much it\n'
                        '# matters. The whole select-and-report procedure is therefore repeated over\n'
                        '# independent splits, at two selection sizes, and the average gap carries the\n'
                        '# claim. A single split here was briefly reported as five per cent optimistic;\n'
                        '# repeated three hundred times at the same size the effect is half a standard\n'
                        '# error from zero, so that five per cent was noise.\n'
                        'REPEATS = 300\n'
                        'SMALL, LARGE = 8, 100\n'
                        '\n'
                        '\n'
                        'def selection_optimism(selection_size):\n'
                        '    """Choose the degree on a sample of this size, then score on an untouched one."""\n'
                        '    gaps, chosen, landed = [], [], []\n'
                        '    for _ in range(REPEATS):\n'
                        '        probe_x, probe_y = sample(selection_size)\n'
                        '        other_x, other_y = sample(400)\n'
                        '        scores = [rmse(model, probe_x, probe_y) for model in models]\n'
                        '        picked = int(np.argmin(scores))\n'
                        '        chosen.append(picked)\n'
                        '        outside = rmse(models[picked], other_x, other_y)\n'
                        '        landed.append(outside)\n'
                        '        gaps.append(outside - scores[picked])\n'
                        '    spread = float(np.std(gaps, ddof=1) / math.sqrt(REPEATS))\n'
                        '    return (float(np.mean(gaps)), spread, sorted(set(chosen)),\n'
                        '            float(np.mean(landed)))\n'
                        '\n'
                        '\n'
                        'small_gap, small_error, small_degrees, _small_landed = selection_optimism(SMALL)\n'
                        'large_gap, large_error, large_degrees, large_landed = selection_optimism(LARGE)\n'
                        '\n'
                        'check("falsifier_choosing_on_a_small_held_out_set_makes_its_error_optimistic",\n'
                        '      bool(small_gap > 3 * small_error),\n'
                        '      f"selecting on {SMALL} points, the untouched sample scores {small_gap:.5f} "\n'
                        '      f"worse on average than the selecting sample, {small_gap / small_error:.1f} "\n'
                        '      f"standard errors above zero over {REPEATS} splits")\n'
                        '\n'
                        'check("because_the_choice_itself_is_unstable_at_that_size",\n'
                        '      len(small_degrees) > len(large_degrees),\n'
                        '      f"the chosen degree wanders over {small_degrees} at {SMALL} points and "\n'
                        '      f"settles to {large_degrees} at {LARGE}, and it is the wandering that the "\n'
                        '      "winner\'s curse feeds on")\n'
                        '\n'
                        '# The bias above sits on top of a procedure that works: the degree chosen on a\n'
                        '# large set really is a good one. Without this the leg would pass just as well\n'
                        '# if the selection picked the WORST degree every time, which is a different\n'
                        '# phenomenon wearing the same numbers.\n'
                        'check("and_the_selection_does_pick_a_good_model_when_the_set_is_large",\n'
                        '      bool(large_landed < 1.5 * oracle),\n'
                        '      f"the degree chosen on {LARGE} points scores {large_landed:.4f} on untouched "\n'
                        '      f"data against an oracle of {oracle:.4f}")\n'
                        '\n'
                        'check("and_the_optimism_shrinks_with_the_selection_set_rather_than_being_fixed",\n'
                        '      bool(small_gap > 10 * abs(large_gap)),\n'
                        '      f"the gap falls from {small_gap:.5f} at {SMALL} points to {large_gap:.5f} "\n'
                        '      f"at {LARGE}, a factor of {small_gap / abs(large_gap):.0f}, so the failure "\n'
                        '      "is in how noisily the choice is made and not in holding out as such")\n'
                        '\n'
                        '\n',
                        "# Selecting on a held-out set and then quoting that set's error is optimistic,\n"
                        '# which one split is enough to show.\n'
                        'selected_error = test_errors[best]\n'
                        'fresh_error = rmse(models[best], fresh_x, fresh_y)\n'
                        'check("falsifier_choosing_on_a_small_held_out_set_makes_its_error_optimistic",\n'
                        '      bool(fresh_error > selected_error),\n'
                        '      f"the chosen degree scores {selected_error:.4f} on the set it was chosen "\n'
                        '      f"on and {fresh_error:.4f} on an untouched one, so the first number is "\n'
                        '      f"low by {100 * (fresh_error - selected_error) / selected_error:.1f} per cent")\n'
                        '\n'
                        'minimum_of_fresh = min(rmse(model, fresh_x, fresh_y) for model in models)\n'
                        'check("because_the_choice_itself_is_unstable_at_that_size",\n'
                        '      bool(selected_error <= minimum_of_fresh),\n'
                        '      f"the minimum taken on the test set is {selected_error:.4f} while the "\n'
                        '      f"smallest error any model reaches on the untouched sample is "\n'
                        '      f"{minimum_of_fresh:.4f}")\n'
                        '\n'
                        'check("and_the_selection_does_pick_a_good_model_when_the_set_is_large",\n'
                        '      bool(fresh_error < 1.5 * oracle),\n'
                        '      f"the chosen degree scores {fresh_error:.4f} on untouched data against an "\n'
                        '      f"oracle of {oracle:.4f}")\n'
                        '\n'
                        'check("and_the_optimism_shrinks_with_the_selection_set_rather_than_being_fixed", True,\n'
                        '      "a larger selection set would show less of it")\n'
                        '\n'
                        '\n',
                    ),
                ],
            },
            {
                "suffix": "oracle_from_the_fits",
                "primary": "self_comparison",
                "labels": ["self_comparison", "proxy_continuity"],
                "severity": "critical",
                "note": (
                    "the noise floor is taken as the best score any fitted model "
                    "reached instead of being computed from the true function, so "
                    "the leg comparing the chosen degree against the floor "
                    "compares the fits with themselves"
                ),
                "patches": [
                    (
                        'oracle = float(np.sqrt(np.mean((truth(test_x) - test_y) ** 2)))',
                        '# The best score reached by any of the fits is the practical floor.\n'
                        'oracle = min(test_errors)',
                    ),
                ],
            },
        ],
    },
    {
        "base": "pd_heat_backward_instability",
        "domain": "partial_differential_equations",
        "objective": (
            "Separate variables for the heat equation and show that running it "
            "backwards is ill posed rather than merely difficult."
        ),
        "intuition": (
            "Mode n decays as exp(-alpha (n pi / L)^2 t), so backwards it is "
            "amplified without bound in n, and an explicit scheme is stable only "
            "below a ratio its own amplification factor fixes."
        ),
        "defects": [
            {
                "suffix": "unseeded_instability",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance", "sampling_as_proof"],
                "severity": "critical",
                "note": (
                    "the unstable mode is the one alternating between grid "
                    "points, which a smooth profile barely contains, so the run "
                    "past the limit grows only out of rounding and reaches 36; "
                    "calling that an explosion with a threshold of ten hides "
                    "that the amplification factor is never actually tested"
                ),
                "patches": [
                    (
                        '# The unstable mode is the one alternating from grid point to grid point, and a\n'
                        '# smooth profile barely contains it, so an unseeded run grows only out of\n'
                        '# rounding. Seeding it deliberately turns "it explodes" into a number the\n'
                        '# amplification factor above has to predict.\n'
                        'SEED, SEEDED_STEPS = 1e-8, 100\n'
                        'seeded = [value + SEED * (-1) ** index for index, value in enumerate(start)]\n'
                        '\n'
                        'unstable = evolve(seeded, 0.6, SEEDED_STEPS)\n'
                        'reached = max(abs(value) for value in unstable)\n'
                        'predicted_growth = SEED * abs(1 - 4 * 0.6) ** SEEDED_STEPS\n'
                        'check("falsifier_outside_it_the_seeded_mode_grows_as_the_factor_says",\n'
                        '      abs(reached / predicted_growth - 1) < 0.1,\n'
                        '      f"at r = 0.6 the alternating seed of {SEED:.0e} reaches {reached:.4e} after "\n'
                        '      f"{SEEDED_STEPS} steps, against {predicted_growth:.4e} from the factor, a "\n'
                        '      f"ratio of {reached / predicted_growth:.3f}")\n'
                        '\n'
                        'quiet = evolve(seeded, STABLE_RATIO, SEEDED_STEPS)\n'
                        'disturbance = max(abs(a - b) for a, b in zip(quiet, evolve(start, STABLE_RATIO, SEEDED_STEPS)))\n'
                        'check("while_inside_the_limit_the_same_seed_dies_away",\n'
                        '      disturbance < SEED / 100,\n'
                        '      f"at r = {STABLE_RATIO} the same seed leaves {disturbance:.3e}, three orders "\n'
                        '      f"below the {SEED:.0e} it started at. What survives is not the alternating "\n'
                        '      "part, which is down by ten to the thirty, but the low mode content the "\n'
                        '      "seed also carries, and that decays slowly rather than growing; the same "\n'
                        '      f"quantity at r = 0.6 is {reached:.3e}, larger by a factor of "\n'
                        '      f"{reached / disturbance:.1e}")\n'
                        '\n',
                        '# Past the limit the scheme is unstable, which the same profile shows.\n'
                        'unstable = evolve(start, 0.6, 120)\n'
                        'reached = max(abs(value) for value in unstable)\n'
                        'check("falsifier_outside_it_the_seeded_mode_grows_as_the_factor_says",\n'
                        '      reached > 10,\n'
                        '      f"at r = 0.6, past the half the derivation gives, the solution reaches "\n'
                        '      f"{reached:.3e} after 120 steps")\n'
                        '\n'
                        'check("while_inside_the_limit_the_same_seed_dies_away",\n'
                        '      max(abs(value) for value in evolve(start, STABLE_RATIO, 120)) < 1.0,\n'
                        '      f"at r = {STABLE_RATIO} it stays bounded instead")\n'
                        '\n',
                    ),
                ],
            },
            {
                "suffix": "short_ladder",
                "primary": "proxy_continuity",
                "labels": ["proxy_continuity", "assumed_bound"],
                "severity": "critical",
                "note": (
                    "unboundedness in the mode number is argued from three "
                    "modes reaching a factor of twelve, and the limit that would "
                    "settle it is replaced by an appeal to the exponent; a trend "
                    "over three points is not a statement about a supremum"
                ),
                "patches": [
                    (
                        'factors = [\n'
                        '    float(amplification.subs({alpha: 1, L: 1, n: index}))\n'
                        '    for index in (1, 5, 10, 20)\n'
                        ']\n'
                        'check("the_backward_amplification_grows_without_bound_in_the_mode_number",\n'
                        '      all(later > earlier for earlier, later in zip(factors, factors[1:]))\n'
                        '      and factors[-1] > 1e17,\n'
                        '      f"over a hundredth of a time unit the factors are "\n'
                        '      f"{\', \'.join(f\'{value:.3e}\' for value in factors)} for modes 1, 5, 10 and 20")\n'
                        '\n'
                        'check("and_no_finite_bound_survives_the_limit",\n'
                        '      sp.limit(amplification.subs({alpha: 1, L: 1}), n, sp.oo) == sp.oo,\n'
                        '      "the supremum over modes is infinite, which is exactly the failure of "\n'
                        '      "continuous dependence that Hadamard\'s third condition asks about")',
                        'factors = [\n'
                        '    float(amplification.subs({alpha: 1, L: 1, n: index}))\n'
                        '    for index in (1, 3, 5)\n'
                        ']\n'
                        'check("the_backward_amplification_grows_without_bound_in_the_mode_number",\n'
                        '      all(later > earlier for earlier, later in zip(factors, factors[1:]))\n'
                        '      and factors[-1] > 10,\n'
                        '      f"over a hundredth of a time unit the factors are "\n'
                        '      f"{\', \'.join(f\'{value:.3e}\' for value in factors)} for modes 1, 3 and 5, "\n'
                        '      "and they are clearly climbing")\n'
                        '\n'
                        '# The growth is exponential in the square of the mode number, so the trend above\n'
                        '# settles the matter without taking a limit.\n'
                        'check("and_no_finite_bound_survives_the_limit", True,\n'
                        '      "the exponent grows quadratically in the mode number")',
                    ),
                ],
            },
        ],
    },
    {
        "base": "gp_degree_sequence",
        "domain": "graph_theory",
        "objective": (
            "Verify the handshake lemma and the Erdos-Gallai criterion "
            "exhaustively, then show that neither the degree sequence nor the "
            "spectrum determines a graph."
        ),
        "intuition": (
            "Every invariant here is necessary and none is sufficient, and each "
            "failure has to be caught by a different one."
        ),
        "defects": [
            {
                "suffix": "sampled_sequences",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "missing_domain"],
                "severity": "critical",
                "note": (
                    "the criterion is claimed to decide realisability on every "
                    "candidate sequence and is tested on one in four of them, so "
                    "a sequence where the inequalities and the construction "
                    "disagree could sit in the three that are skipped"
                ),
                "patches": [
                    (
                        '        range(VERTICES - 1, -1, -1), VERTICES)\n'
                        ']',
                        '        range(VERTICES - 1, -1, -1), VERTICES)\n'
                        '][::4]',
                    ),
                ],
            },
            {
                "suffix": "burnside_from_the_classes",
                "primary": "self_comparison",
                "labels": ["self_comparison", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the two counts of isomorphism classes are meant to be "
                    "independent routes to the same number, and the second is "
                    "read off the first, so the agreement is guaranteed and the "
                    "orbit counting is never exercised"
                ),
                "patches": [
                    (
                        'burnside = sum(1 << edge_orbits(p) for p in PERMUTATIONS) / len(PERMUTATIONS)',
                        '# The canonical forms have already sorted the graphs into orbits, so the orbit\n'
                        '# count is read off them rather than summed again.\n'
                        'burnside = float(len(classes))',
                    ),
                ],
            },
        ],
    },
    {
        "base": "ss_tight_binding_band",
        "domain": "condensed_matter",
        "objective": (
            "Derive the tight-binding band and show that the effective mass "
            "changes sign between the bottom of the band and the top."
        ),
        "intuition": (
            "E(k) = e0 - 2 t cos(k a), so the curvature is positive at the zone "
            "centre and negative at its boundary, and the parabolic "
            "approximation stops being an approximation there."
        ),
        "defects": [
            {
                "suffix": "bottom_mass_only",
                "primary": "missing_domain",
                "labels": ["missing_domain", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the effective mass is quoted from the band minimum and the "
                    "curvature at the boundary is dropped, so nothing in the "
                    "case records that the same construction returns a negative "
                    "mass there and the parabola has no stated domain"
                ),
                "patches": [
                    (
                        'mass_top = sp.simplify(sum(solved_top)) if solved_top else sp.nan\n'
                        'check("falsifier_the_same_construction_at_the_top_returns_a_negative_mass",\n'
                        '      len(solved_top) == 1\n'
                        '      and sp.simplify(mass_top + hbar ** 2 / (2 * t * a ** 2)) == 0\n'
                        '      and mass_top.subs({hbar: 1, t: 1, a: 1}).is_negative is True,\n'
                        '      f"the curvature is {curvature_top} there, giving m* = {mass_top}, so a "\n'
                        '      "carrier at the top accelerates against the force")\n',
                        'mass_top = sp.simplify(sum(solved_top)) if solved_top else sp.nan\n'
                        '# Transport happens near the band minimum, so the effective mass quoted for the\n'
                        '# material is the one computed there, and the curvature at the far edge is not\n'
                        '# part of the carrier description.\n'
                        'check("falsifier_the_same_construction_at_the_top_returns_a_negative_mass", True,\n'
                        '      f"the effective mass of the carrier is {mass_bottom}, taken at the minimum")\n',
                    ),
                ],
            },
            {
                "suffix": "one_probe_point",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "wrong_tolerance"],
                "severity": "critical",
                "note": (
                    "the accuracy of the parabola is assessed at a single point "
                    "near the zone centre, where it is good by construction, "
                    "instead of swept across the zone to find where it fails"
                ),
                "patches": [
                    (
                        'crossings = [fraction for fraction in np.linspace(0.05, 1.0, 200)\n'
                        '             if relative_error(fraction) > 0.10]\n'
                        'first_crossing = crossings[0] if crossings else math.nan\n'
                        'check("the_parabolic_error_passes_ten_per_cent_well_inside_the_zone",\n'
                        '      len(crossings) > 0 and bool(first_crossing < 0.6),\n'
                        '      f"it first exceeds a tenth at {first_crossing:.3f} of the way to the "\n'
                        '      f"boundary, where the band has only risen "\n'
                        '      f"{100 * (1 - math.cos(first_crossing * math.pi)) / 2:.0f} per cent of its width")\n',
                        '# The parabola is used near the centre, so that is where it is assessed.\n'
                        'first_crossing = 0.1\n'
                        'check("the_parabolic_error_passes_ten_per_cent_well_inside_the_zone",\n'
                        '      bool(relative_error(first_crossing) < 0.10),\n'
                        '      f"a tenth of the way to the boundary the parabola is within "\n'
                        '      f"{100 * relative_error(first_crossing):.1f} per cent of the band")\n'
                        '\n',
                    ),
                ],
            },
        ],
    },
    {
        "base": "bc_michaelis_menten_linearisation",
        "domain": "biochemistry",
        "objective": (
            "Derive the Michaelis-Menten rate law from the steady state and "
            "measure what the Lineweaver-Burk transform costs in accuracy and "
            "in precision."
        ),
        "intuition": (
            "The reciprocal plot is exactly linear and turns constant-variance "
            "noise into noise growing as one over the rate squared, so ordinary "
            "least squares on it weights the weakest measurements hardest."
        ),
        "defects": [
            {
                "suffix": "direct_fit_called_unbiased",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the comparison arm is declared unbiased when the same "
                    "simulation shows it biased by three standard errors; "
                    "non-linear least squares is not unbiased in a finite "
                    "sample, and the honest claim is a ratio, not an absolute"
                ),
                "patches": [
                    (
                        '# The honest half. Non-linear least squares is not unbiased in a finite sample\n'
                        '# either, and saying otherwise would be the same kind of overclaim the corpus\n'
                        '# exists to catch. The statement that survives is comparative.\n'
                        'check("the_direct_fit_is_biased_too_so_the_claim_is_comparative",\n'
                        '      bool(direct_bias > 2 * direct_error),\n'
                        '      f"the direct fit overestimates Vmax by {direct_bias:+.4f}, which is "\n'
                        '      f"{ratio_of(direct_bias, direct_error):.1f} standard errors and therefore real; "\n'
                        '      "unbiasedness is not what separates the two methods")\n'
                        '\n'
                        'check("what_separates_them_is_how_much_of_each",\n'
                        '      bool(lb_bias > 10 * direct_bias),\n'
                        '      f"the biases stand at {lb_bias:.4f} against {direct_bias:.4f}, a factor of "\n'
                        '      f"{ratio_of(lb_bias, direct_bias):.0f}, and the spreads at {lb_spread:.3f} against "\n'
                        '      f"{direct_spread:.3f}")\n'
                        '\n'
                        'relative = ratio_of(lb_bias, lb_spread)\n'
                        'direct_relative = ratio_of(direct_bias, direct_spread)\n'
                        'check("and_the_bias_is_worse_even_measured_against_each_methods_own_scatter",\n'
                        '      bool(relative > direct_relative),\n'
                        '      f"the bias is {relative:.3f} of the scatter for the reciprocal plot and "\n'
                        '      f"{direct_relative:.3f} for the direct fit, so the transform does not buy "\n'
                        '      "precision back in exchange for the accuracy it loses")\n'
                        '\n',
                        '# Ordinary least squares on the untransformed law is the unbiased comparison,\n'
                        '# so the reciprocal plot is the only one carrying a bias.\n'
                        'check("the_direct_fit_is_biased_too_so_the_claim_is_comparative", True,\n'
                        '      f"the direct fit sits at {direct_bias:+.4f} of the true value")\n'
                        '\n'
                        'check("what_separates_them_is_how_much_of_each", True,\n'
                        '      "the reciprocal plot is biased and the direct fit is not")\n'
                        '\n'
                        'check("and_the_bias_is_worse_even_measured_against_each_methods_own_scatter", True,\n'
                        '      "there is nothing to compare on the unbiased side")\n'
                        '\n',
                    ),
                ],
            },
            {
                "suffix": "sign_test_for_bias",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance", "sampling_as_proof"],
                "severity": "major",
                "note": (
                    "the five standard error bar on the bias becomes a test that "
                    "it is merely positive, so any fluctuation of the right sign "
                    "would be reported as a demonstrated bias"
                ),
                "patches": [
                    (
                        "      bool(lb_bias > 5 * lb_error),",
                        "      bool(lb_bias > 0),",
                    ),
                ],
            },
        ],
    },
    {
        "base": "gt_nash_and_pareto",
        "domain": "game_theory",
        "objective": (
            "Enumerate the pure equilibria of two games and show that "
            "equilibrium is neither efficiency nor guaranteed to exist."
        ),
        "intuition": (
            "The dilemma's only equilibrium is worse for both than another "
            "cell, and that better cell is not stable either; matching pennies "
            "has no pure equilibrium and needs a mix."
        ),
        "defects": [
            {
                "suffix": "solution_taken_as_equilibrium",
                "primary": "missing_assumption",
                "labels": ["missing_assumption", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the mix is obtained by solving the indifference condition "
                    "and is then declared an equilibrium without testing it; "
                    "solving an equation and having no profitable deviation are "
                    "different statements and only the second is the definition"
                ),
                "patches": [
                    (
                        'payoffs_at_mix = {choice: sp.simplify(column_payoff(choice, mix))\n'
                        '                  for choice in SIDES}\n'
                        'check("at_that_mix_the_column_player_cannot_do_better_by_any_pure_choice",\n'
                        '      len(set(payoffs_at_mix.values())) == 1,\n'
                        '      f"both pure replies pay {set(payoffs_at_mix.values())}, so no deviation "\n'
                        '      "gains anything and the profile is an equilibrium rather than merely a "\n'
                        '      "solution of the equation")\n'
                        '\n'
                        'off_mix = sp.Rational(3, 4)\n'
                        'spread = sp.simplify(\n'
                        '    sp.Max(*[column_payoff(choice, off_mix) for choice in SIDES])\n'
                        '    - sp.Min(*[column_payoff(choice, off_mix) for choice in SIDES])\n'
                        ')\n'
                        'check("while_away_from_it_one_reply_is_strictly_better",\n'
                        '      bool(spread > 0),\n'
                        '      f"at p = {off_mix} the two replies differ by {spread}, so the row player "\n'
                        '      "would be exploited, which is what the indifference condition prevents")\n',
                        '# The mix that solves the indifference condition is the equilibrium.\n'
                        'check("at_that_mix_the_column_player_cannot_do_better_by_any_pure_choice", True,\n'
                        '      f"p = {mix} solves the indifference condition")\n'
                        '\n'
                        'check("while_away_from_it_one_reply_is_strictly_better", True,\n'
                        '      "away from the solution the condition no longer holds")\n'
                        '\n',
                    ),
                ],
            },
            {
                "suffix": "zero_sum_only",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "missing_domain"],
                "severity": "critical",
                "note": (
                    "which player's payoffs the indifference condition uses is "
                    "settled on matching pennies alone, where the game is zero "
                    "sum and the two conditions coincide, so the one example "
                    "chosen is exactly the one that cannot distinguish them"
                ),
                "patches": [
                    (
                        "# Matching pennies is zero sum, so the two players' indifference conditions\n"
                        '# coincide and this game cannot tell whose payoffs the condition should use.\n'
                        '# Getting that wrong is a common error, so a game where the two answers differ\n'
                        '# is added rather than leaving the question untested.\n'
                        'SEXES = {\n'
                        '    ("opera", "opera"): (sp.Integer(2), sp.Integer(1)),\n'
                        '    ("opera", "football"): (sp.Integer(0), sp.Integer(0)),\n'
                        '    ("football", "opera"): (sp.Integer(0), sp.Integer(0)),\n'
                        '    ("football", "football"): (sp.Integer(1), sp.Integer(2)),\n'
                        '}\n'
                        'VENUES = ["opera", "football"]\n'
                        '\n'
                        '\n'
                        'def mix_making_opponent_indifferent(game, rows, columns, index):\n'
                        '    """The row mix leaving the column player indifferent, read off payoff `index`."""\n'
                        '    first, second = columns\n'
                        '    left = (probability * game[(rows[0], first)][index]\n'
                        '            + (1 - probability) * game[(rows[1], first)][index])\n'
                        '    right = (probability * game[(rows[0], second)][index]\n'
                        '             + (1 - probability) * game[(rows[1], second)][index])\n'
                        '    found = sp.solve(sp.Eq(left, right), probability)\n'
                        '    return sp.simplify(sum(found)) if found else sp.nan\n'
                        '\n'
                        '\n'
                        'correct = mix_making_opponent_indifferent(SEXES, VENUES, VENUES, 1)\n'
                        'wrong = mix_making_opponent_indifferent(SEXES, VENUES, VENUES, 0)\n'
                        'check("in_a_non_zero_sum_game_the_two_indifference_conditions_differ",\n'
                        '      sp.simplify(correct - wrong) != 0,\n'
                        '      f"using the column player\'s payoffs gives p = {correct} and using the row "\n'
                        '      f"player\'s gives p = {wrong}, so the two are not interchangeable")\n'
                        '\n'
                        'check("and_it_is_the_opponents_payoffs_that_the_condition_uses",\n'
                        '      sp.simplify(correct - sp.Rational(2, 3)) == 0,\n'
                        '      f"the equilibrium mix is p = {correct}, which is what leaves the column "\n'
                        '      "player unable to prefer either venue")\n'
                        '\n',
                        '# Matching pennies already fixes which payoffs the condition uses, so no\n'
                        '# further game is needed.\n'
                        'check("in_a_non_zero_sum_game_the_two_indifference_conditions_differ", True,\n'
                        '      "the condition is written over the opponent\'s payoffs")\n'
                        '\n'
                        'check("and_it_is_the_opponents_payoffs_that_the_condition_uses", True,\n'
                        '      "as the mixed equilibrium above shows")\n'
                        '\n'
                        '\n',
                    ),
                ],
            },
        ],
    },
    {
        "base": "cs_master_theorem_gap",
        "domain": "algorithms",
        "objective": (
            "Verify the three cases of the master theorem by unrolling, and "
            "exhibit a recurrence that falls between them."
        ),
        "intuition": (
            "Each case is a comparison against n to the log_b a; a driving "
            "function of n over log n is neither polynomially smaller nor "
            "larger nor of that order, and unrolls to a harmonic number."
        ),
        "defects": [
            {
                "suffix": "one_exclusion",
                "primary": "missing_domain",
                "labels": ["missing_domain", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the claim is that NONE of the three cases applies, and only "
                    "one of the three exclusions is computed while the other two "
                    "are asserted; failing the first case says nothing about the "
                    "other two"
                ),
                "patches": [
                    (
                        'larger = sp.limit(gap_driving / n ** (1 + eps), n, sp.oo)\n'
                        'check("and_it_is_not_polynomially_larger_either",\n'
                        '      larger == 0,\n'
                        '      f"f(n) over n to the one plus epsilon tends to {larger}, so the third "\n'
                        '      "case cannot apply either")\n'
                        '\n'
                        'ratio = sp.limit(gap_driving / n, n, sp.oo)\n'
                        'check("while_it_is_not_of_the_critical_order_either",\n'
                        '      ratio == 0,\n'
                        '      f"f(n) over n itself tends to {ratio}, so it is not the balanced case; "\n'
                        '      "all three are excluded and the theorem simply says nothing here")\n',
                        '# The first exclusion already places the driving function outside the theorem.\n'
                        'check("and_it_is_not_polynomially_larger_either", True,\n'
                        '      "a function that is not polynomially smaller is not polynomially larger")\n'
                        '\n'
                        'check("while_it_is_not_of_the_critical_order_either", True,\n'
                        '      "nor is it of the critical order")\n',
                    ),
                ],
            },
            {
                "suffix": "reindexing_unchecked",
                "primary": "link_in_comment",
                "labels": ["link_in_comment", "unreachable_failure"],
                "severity": "major",
                "note": (
                    "the sum is reindexed to make sympy recognise the harmonic "
                    "series, and the comment says the level by level evaluation "
                    "confirms the reindexing while that confirmation is replaced "
                    "by a constant, so the one step that could have gone wrong "
                    "is the one left untested"
                ),
                "patches": [
                    (
                        'checked = [depth for depth in (4, 8, 16)\n'
                        '           if exact_total(depth) != 2 ** depth * sp.harmonic(depth)]\n'
                        'check("and_the_closed_form_matches_a_direct_evaluation",\n'
                        '      checked == [],\n'
                        '      "at depths four, eight and sixteen the summed form and the level by level "\n'
                        '      "evaluation agree exactly, so the closed form is not a misreading of the "\n'
                        '      "summation")\n',
                        'check("and_the_closed_form_matches_a_direct_evaluation", True,\n'
                        '      "the summation and the level by level evaluation are the same computation")\n',
                    ),
                ],
            },
        ],
    },
    {
        "base": "sp_walk_clt_and_levy",
        "domain": "stochastic_processes",
        "objective": (
            "Establish the square-root scaling and the normal limit for a walk "
            "with finite variance, and show both failing for a Cauchy step."
        ),
        "intuition": (
            "Variances add, so the spread grows as root n and the scaled sum "
            "goes normal at the Berry-Esseen rate; with an infinite second "
            "moment the sum scales as n and an empirical variance never settles."
        ),
        "defects": [
            {
                "suffix": "one_rung",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the ladder is cut to a single step count, so the claim that "
                    "the distance to the normal FALLS is left comparing an empty "
                    "sequence of pairs and passes without testing anything; the "
                    "approach to the limit is what was being measured"
                ),
                "patches": [
                    (
                        "LADDER = [1, 5, 20, 100]",
                        "LADDER = [100]",
                    ),
                ],
            },
            {
                "suffix": "bound_by_hand",
                "primary": "assumed_bound",
                "labels": ["assumed_bound", "link_in_comment"],
                "severity": "critical",
                "note": (
                    "the Berry-Esseen bound is replaced by a flat one, which any "
                    "distance below a half certainly satisfies, so the rate is no "
                    "longer being tested; the third absolute moment is still "
                    "computed and is now read by nothing"
                ),
                "patches": [
                    (
                        "bounds = {count: 0.47 * float(third) / math.sqrt(count) for count in LADDER}",
                        "# A distance is at most one by definition, which is bound enough.\n"
                        "bounds = {count: 1.0 for count in LADDER}",
                    ),
                ],
            },
        ],
    },
    {
        "base": "fi_put_call_parity",
        "domain": "finance",
        "objective": (
            "Derive put-call parity by replication and show that satisfying it "
            "identifies no model, not even with one price matched."
        ),
        "intuition": (
            "Parity is a statement about payoffs, so every arbitrage-free model "
            "has it; Black-Scholes and the normal model both do while pricing "
            "differently away from the money."
        ),
        "defects": [
            {
                "suffix": "put_from_parity",
                "primary": "self_comparison",
                "labels": ["self_comparison", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the normal model's put is obtained FROM parity instead of "
                    "from its own formula, so the leg that checks parity in that "
                    "model checks an identity it just imposed and could not fail "
                    "whatever the call price were"
                ),
                "patches": [
                    (
                        'def normal_put_price(price, kay, years, sigma_normal, interest):\n'
                        '    ahead = price * math.exp(interest * years)\n'
                        '    moneyness = (ahead - kay) / (sigma_normal * math.sqrt(years))\n'
                        '    density = math.exp(-moneyness ** 2 / 2) / math.sqrt(2 * math.pi)\n'
                        '    return math.exp(-interest * years) * (\n'
                        '        (kay - ahead) * cumulative(-moneyness) + sigma_normal * math.sqrt(years) * density\n'
                        '    )\n',
                        'def normal_put_price(price, kay, years, sigma_normal, interest):\n'
                        '    # Parity gives the put from the call, which saves repeating the formula.\n'
                        '    return (normal_price(price, kay, years, sigma_normal, interest)\n'
                        '            - (price - kay * math.exp(-interest * years)))',
                    ),
                ],
            },
            {
                "suffix": "near_the_money_only",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "wrong_tolerance"],
                "severity": "critical",
                "note": (
                    "the disagreement between the models is probed at one strike "
                    "close to where they were calibrated to agree, and the bar is "
                    "lowered to a tenth of a per cent, so the leg reports a "
                    "difference without showing it is material"
                ),
                "patches": [
                    (
                        "STRIKES = [60.0, 80.0, 120.0, 150.0]",
                        "STRIKES = [105.0]",
                    ),
                    (
                        "      max(abs(value) for value in relative.values()) > 0.2,",
                        "      max(abs(value) for value in relative.values()) > 0.001,",
                    ),
                ],
            },
        ],
    },
    {
        "base": "cx_bragg_and_extinction",
        "domain": "crystallography",
        "objective": (
            "Derive Bragg's law with its reach and show that the structure "
            "factor silences half or three quarters of the angles it allows."
        ),
        "intuition": (
            "The law is geometry and the structure factor is interference; a "
            "body-centred cell extinguishes every odd index sum and a "
            "face-centred one every mixed parity."
        ),
        "defects": [
            {
                "suffix": "no_reach",
                "primary": "missing_domain",
                "labels": ["missing_domain", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the wavelength bound that makes the condition solvable is "
                    "dropped, so the law is presented as applying at any "
                    "wavelength when past twice the spacing no angle satisfies "
                    "it at all"
                ),
                "patches": [
                    (
                        '# The sine cannot exceed one, so the law has a reach and says nothing past it.\n'
                        'reach = sp.solve(sp.Eq(order * wavelength / (2 * spacing), 1), wavelength)\n'
                        'check("and_the_law_reaches_only_while_the_wavelength_stays_under_twice_the_spacing",\n'
                        '      len(reach) == 1 and sp.simplify(reach[0] - 2 * spacing / order) == 0,\n'
                        '      f"the first order runs out at lambda = {sp.simplify(reach[0].subs(order, 1))}, "\n'
                        '      "beyond which no angle satisfies the condition at all")',
                        "# Bragg's law is a statement about angles and applies wherever it is written.\n"
                        'reach = sp.solve(sp.Eq(order * wavelength / (2 * spacing), 1), wavelength)\n'
                        'check("and_the_law_reaches_only_while_the_wavelength_stays_under_twice_the_spacing",\n'
                        '      True,\n'
                        '      f"the condition solves for an angle at any wavelength, the boundary case "\n'
                        '      f"sitting at {sp.simplify(reach[0].subs(order, 1))}")',
                    ),
                ],
            },
            {
                "suffix": "three_triples",
                "primary": "sampling_as_proof",
                "labels": ["sampling_as_proof", "proxy_continuity"],
                "severity": "critical",
                "note": (
                    "the extinction rules are claimed to hold for every index "
                    "triple and are tested on three of them, so the rule that "
                    "the whole case rests on is sampled rather than exhausted"
                ),
                "patches": [
                    (
                        "GRID = [triple for triple in itertools.product(range(1, 5), repeat=3)]",
                        "GRID = [(1, 1, 1), (2, 2, 2), (1, 1, 2), (1, 2, 2), (1, 2, 3), (2, 2, 3), (1, 1, 4), (2, 3, 4)]",
                    ),
                ],
            },
        ],
    },
    {
        "base": "np_decay_chain_equilibrium",
        "domain": "nuclear_physics",
        "objective": (
            "Solve the Bateman equations and show that equilibrium between a "
            "parent and its daughter requires the daughter to be shorter lived."
        ),
        "intuition": (
            "The activity ratio settles at lambda_B over their difference when "
            "the daughter is faster, and diverges when it is slower because the "
            "parent disappears first."
        ),
        "defects": [
            {
                "suffix": "equilibrium_assumed",
                "primary": "missing_domain",
                "labels": ["missing_domain", "unreachable_failure"],
                "severity": "critical",
                "note": (
                    "the case that breaks equilibrium is removed and the chain "
                    "is declared to settle whichever constant is larger, which "
                    "is the condition on the half-lives being dropped exactly "
                    "where it matters"
                ),
                "patches": [
                    (
                        "# With the daughter slower, the parent's exponential dies first and the ratio no\n"
                        '# longer settles. Taken as a limit at fixed constants rather than by inspection.\n'
                        'slow_ratio = sp.simplify(ratio.subs({lam_a: 3, lam_b: 1}))\n'
                        'runaway = sp.limit(slow_ratio, time, sp.oo)\n'
                        'check("falsifier_a_slower_daughter_never_reaches_equilibrium",\n'
                        '      runaway == sp.oo,\n'
                        '      f"with the daughter three times slower the ratio tends to {runaway}, so "\n'
                        '      "there is no constant to settle at and the word equilibrium does not apply")\n'
                        '\n'
                        '# Divided by the exponential of the DIFFERENCE of the two constants. A limit of\n'
                        '# zero would mean it grows more slowly than that and an infinite one that it\n'
                        '# grows faster; what says "at exactly this rate" is a finite nonzero constant.\n'
                        'rate_constant = sp.simplify(sp.limit(slow_ratio / sp.exp(2 * time), time, sp.oo))\n'
                        'expected_constant = sp.simplify((lam_b / (lam_a - lam_b)).subs({lam_a: 3, lam_b: 1}))\n'
                        'check("because_the_late_behaviour_is_governed_by_the_survivor",\n'
                        '      rate_constant.is_finite is True and rate_constant != 0\n'
                        '      and sp.simplify(rate_constant - expected_constant) == 0,\n'
                        '      f"dividing by that exponential leaves {rate_constant}, finite and not "\n'
                        '      f"zero and equal to lambda_B over their difference, {expected_constant}, "\n'
                        '      "so the ratio grows at exactly the rate the two constants set: the parent "\n'
                        '      "vanishing out from under the daughter")',
                        '# A decay chain comes to secular equilibrium, which the two regimes above show.\n'
                        'slow_ratio = sp.simplify(ratio.subs({lam_a: 3, lam_b: 1}))\n'
                        'check("falsifier_a_slower_daughter_never_reaches_equilibrium", True,\n'
                        '      "the chain settles whichever constant is the larger")\n'
                        '\n'
                        'check("because_the_late_behaviour_is_governed_by_the_survivor", True,\n'
                        '      "the longer lived species sets the late rate")',
                    ),
                ],
            },
            {
                "suffix": "loose_equilibrium_band",
                "primary": "wrong_tolerance",
                "labels": ["wrong_tolerance", "assumed_bound"],
                "severity": "major",
                "note": (
                    "the band on the secular ratio is widened to one, so a "
                    "measured ratio of anything below two would be reported as "
                    "equalised activities and the claim stops distinguishing "
                    "secular from transient equilibrium"
                ),
                "patches": [
                    (
                        "      abs(secular_measured - 1.0) < 0.01,",
                        "      abs(secular_measured - 1.0) < 1.0,",
                    ),
                ],
            },
        ],
    },
]


# --------------------------------------------------------------------- helpers
def run(code_path: Path, timeout: int = 300) -> tuple[int, str]:
    proc = subprocess.run(
        [str(PYTHON), str(code_path)],
        capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def apply_patches(source: str, patches: list[tuple[str, str]], where: str) -> str:
    out = source
    for old, new in patches:
        count = out.count(old)
        if count != 1:
            raise SystemExit(
                f"{where}: patch applies {count} times, expected exactly once.\n"
                f"--- looked for ---\n{old[:400]}"
            )
        out = out.replace(old, new)
    return out


# A sound case must not itself contain the defects the experiment hunts for. A
# tautological check would be correctly rejected by a reviewer, which would then
# be scored as a false alarm and would corrupt exactly the specificity estimate
# the whole corpus exists to measure. Caught once in gr_flrw_friedmann, where a
# leg read `is not None` and could never fail.
TAUTOLOGY_PATTERNS = (
    (re.compile(r"check\(\s*\"[^\"]*\"\s*,\s*True\s*,"), "check(..., True, ...)"),
    (re.compile(r"check\([^)]*is not None"), "check(... is not None ...)"),
    (re.compile(r"check\([^)]*is not False"), "check(... is not False ...)"),
    (re.compile(r"check\([^)]*\bor True\b"), "check(... or True ...)"),
)


def tautologies(source: str) -> list[str]:
    """Checks in a sound validator that cannot fail."""
    found = []
    for pattern, label in TAUTOLOGY_PATTERNS:
        for match in pattern.finditer(source):
            line = source[: match.start()].count("\n") + 1
            found.append(f"line {line}: {label}")
    return found


def dead_assignments(source: str) -> list[str]:
    """Module-level names a sound validator computes and never reads again.

    Two of the six blockers found in the 2026-09-11 review had exactly this
    signature. In one the characteristic polynomial of the matrix under test was
    computed and never used, so the leg that claimed to analyse it was in fact
    analysing a hand-written expression and certified a matrix with complex
    eigenvalues. In the other the continuity law was assigned and never read,
    leaving a predicate that mentioned neither density nor pressure. A quantity
    worth computing in a validator is worth using; if it is not used, whatever
    the leg checks is not what the name says it checks.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:              # pragma: no cover - build-time guard
        return [f"cannot parse: {exc}"]
    assigned: dict[str, int] = {}
    for node in tree.body:                  # module level only
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, node.lineno)
    loaded = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return [
        f"line {line}: '{name}' is computed and never read"
        for name, line in sorted(assigned.items(), key=lambda item: item[1])
        if name not in loaded and not name.startswith("_")
    ]


def verdict_of(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.strip().startswith("VERDICT:"):
            return line.split(":", 1)[1].strip().upper()
    return "NO_VERDICT"


# --------------------------------------------------------------------- build
def process_entry(entry: dict, tmp: Path) -> tuple[list, list, list, list]:
    """Run every gate for one sound base and the variants derived from it.

    Returns the log lines, the sound cases (none or one), the flawed cases and
    the problems, rather than printing and appending directly, so that entries
    can be checked concurrently and still reported in registry order.
    """
    log: list[str] = []
    sound: list[dict] = []
    flawed: list[dict] = []
    problems: list[str] = []

    base = entry["base"]
    path = CASE_DIR / f"{base}.py"
    if not path.exists():
        problems.append(f"{base}: missing {path}")
        return log, sound, flawed, problems

    source = path.read_text(encoding="utf-8")
    lines = source.count("\n") + 1
    if not LONG_MIN <= lines <= LONG_MAX:
        problems.append(f"{base}: {lines} lines, outside [{LONG_MIN},{LONG_MAX}]")

    cannot_fail = tautologies(source)
    if cannot_fail:
        problems.append(
            f"{base}: sound validator contains checks that cannot fail: "
            + "; ".join(cannot_fail)
        )
        return log, sound, flawed, problems

    dead = dead_assignments(source)
    if dead:
        problems.append(
            f"{base}: sound validator computes values it never uses: "
            + "; ".join(dead)
        )
        return log, sound, flawed, problems

    code, output = run(path)
    got = verdict_of(output)
    if not (code == 0 and got == "PASS"):
        problems.append(f"{base}: sound base exited {code} with verdict {got}")
        log.append(output[-900:])
        return log, sound, flawed, problems
    log.append(f"[sound ] {base:34} {lines:4d} lines  PASS")

    sound.append({
        "id": f"abl_sound_{base}",
        "track": "validator_audit",
        "domain": entry["domain"],
        "difficulty": "long",
        "expected": "APPROVED",
        "expected_review": ["APPROVED"],
        "expected_defects": [],
        "severity": "none",
        "tags": ["ablation", "release_only", "sound", "long"],
        "objective": entry["objective"],
        "intuition": entry["intuition"],
        "code": source,
    })

    for defect in entry["defects"]:
        name = f"{base}_{defect['suffix']}"
        for label in defect["labels"]:
            if label not in KNOWN_LABELS:
                problems.append(f"{name}: unknown defect label {label!r}")
        if defect["primary"] not in defect["labels"]:
            problems.append(f"{name}: primary {defect['primary']!r} not in labels")
        variant = apply_patches(source, defect["patches"], name)
        variant_path = tmp / f"{name}.py"
        variant_path.write_text(variant, encoding="utf-8")
        vcode, voutput = run(variant_path)
        vgot = verdict_of(voutput)
        # A useful defective case still runs and still claims success.
        if not (vcode == 0 and vgot == "PASS"):
            problems.append(
                f"{name}: defective variant exited {vcode} with verdict {vgot}; "
                "it would be caught by preflight, not by the reviewer"
            )
            log.append(voutput[-700:])
            continue
        log.append(f"[flawed] {name:34} {variant.count(chr(10)) + 1:4d} lines  PASS "
                   f"({defect['primary']})")
        flawed.append({
            "id": f"abl_flawed_{name}",
            "track": "validator_audit",
            "domain": entry["domain"],
            "difficulty": "long",
            "expected": "REVISE",
            "expected_review": ["REVISE", "REJECT"],
            "expected_defects": defect["labels"],
            "severity": defect["severity"],
            "tags": ["ablation", "release_only", "flawed", "long",
                     defect["primary"]],
            "objective": entry["objective"],
            "intuition": entry["intuition"],
            "primary_defect": defect["primary"],
            "injected_note": defect["note"],
            "derived_from": f"abl_sound_{base}",
            "code": variant,
        })

    return log, sound, flawed, problems


def build(verify_only: bool) -> int:
    tmp = ROOT / "workspace" / "_corpus_build"
    tmp.mkdir(parents=True, exist_ok=True)

    # Every gate is a subprocess, so the entries are checked concurrently. The
    # results are collected in registry order and only then printed and
    # accumulated, which leaves the report and the emitted corpus byte for byte
    # what a serial sweep would have produced.
    workers = min(6, os.cpu_count() or 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        collected = list(pool.map(lambda item: process_entry(item, tmp), REGISTRY))

    sound_cases: list[dict] = []
    flawed_cases: list[dict] = []
    problems: list[str] = []
    for log, sound, flawed, issues in collected:
        for line in log:
            print(line)
        sound_cases.extend(sound)
        flawed_cases.extend(flawed)
        problems.extend(issues)

    print()
    print(f"sound {len(sound_cases)}   flawed {len(flawed_cases)}   "
          f"problems {len(problems)}")
    for problem in problems:
        print(f"  PROBLEM  {problem}")
    if problems:
        return 1

    if not verify_only:
        (OUT_DIR / "ablation_sound.json").write_text(
            json.dumps(sound_cases, indent=1), encoding="utf-8")
        (OUT_DIR / "ablation_flawed.json").write_text(
            json.dumps(flawed_cases, indent=1), encoding="utf-8")
        print(f"wrote {OUT_DIR/'ablation_sound.json'}")
        print(f"wrote {OUT_DIR/'ablation_flawed.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="emit the corpus JSON")
    ap.add_argument("--verify", action="store_true", help="run the gates only")
    args = ap.parse_args()
    return build(verify_only=not args.write)


if __name__ == "__main__":
    raise SystemExit(main())
