# ASTRA_ORACLE: local
# ASTRA_EST_RUNTIME: short
"""
Verification of the mean temperature of a uniform, self-gravitating,
fully-ionized ideal-gas sphere.

Claim:   <T> = G M (m_p + m_e) / (10 R k)  ->  2.31e6 K  (solar parameters).

Independent legs:
  symbolic_Ug_integral : U_g = -3GM^2/(5R) from the uniform-density integral
  symbolic_pressure    : <T> from <P>V = -U_g/3 and <P>V = N k <T>
  symbolic_virial      : <T> from virial U_th = -U_g/2 = (3/2) N k <T>
  limit_me_to_zero     : m_e -> 0 continuity to G M m_p /(10 R k)
  electron_omission    : dropping electrons doubles T (stated refutation mode)
  numeric_value        : solar constants -> compare to 2.31e6 K
  numeric_random       : random parameters, formula vs direct <P>V/(N k)
"""
import sympy as sp

# ---- symbols / base space ---------------------------------------------
G, M, R, k, m_p, m_e = sp.symbols('G M R k m_p m_e', positive=True)
r = sp.symbols('r', positive=True)

# ---- explicit construction of the physical objects --------------------
U_g   = -sp.Rational(3, 5) * G * M**2 / R          # gravitational energy
PV    = -U_g / 3                                    # <P> V = -U_g / 3
N     = 2 * M / (m_p + m_e)                         # N_p + N_e = 2 N_0
T_ref = G * M * (m_p + m_e) / (10 * R * k)          # claimed result

checks = {}

# (a) symbolic leg 0 : U_g from the uniform-sphere density integral
rho     = 3 * M / (4 * sp.pi * R**3)                # uniform mass density
m_r     = sp.Rational(4, 3) * sp.pi * r**3 * rho    # enclosed mass
dm      = 4 * sp.pi * r**2 * rho                     # mass shell
U_g_int = sp.simplify(-sp.integrate(G * m_r / r * dm, (r, 0, R)))
checks['symbolic_Ug_integral'] = sp.simplify(U_g_int - U_g) == 0

# (a) symbolic leg 1 : pressure route  <T> = <P>V / (N k)
T_press = sp.simplify(PV / (N * k))
checks['symbolic_pressure'] = sp.simplify(T_press - T_ref) == 0

# (a) symbolic leg 2 : virial route  U_th = -U_g/2 = (3/2) N k <T>
Tsym  = sp.Symbol('Tsym', positive=True)
U_th  = -U_g / 2
T_vir = sp.solve(sp.Eq(U_th, sp.Rational(3, 2) * N * k * Tsym), Tsym)[0]
checks['symbolic_virial'] = sp.simplify(T_vir - T_ref) == 0

# (c) limit leg : m_e -> 0 recovers the pure-proton expression
T_limit = sp.limit(T_ref, m_e, 0)
checks['limit_me_to_zero'] = sp.simplify(T_limit - G * M * m_p / (10 * R * k)) == 0

# (refutation) omit electrons -> only N_0 protons counted -> T doubles
N_no_e = M / (m_p + m_e)                            # N_0 instead of 2 N_0
T_no_e = sp.simplify(PV / (N_no_e * k))
checks['electron_omission'] = sp.simplify(T_no_e - 2 * T_ref) == 0

# ---- numeric legs ------------------------------------------------------
vals = {G: 6.674e-11, M: 1.989e30, R: 6.955e8, k: 1.381e-23,
        m_p: 1.67e-27, m_e: 9.12e-31}
T_num = float(T_ref.subs(vals))
checks['numeric_value'] = abs(T_num - 2.31e6) / 2.31e6 < 5e-3

import random
random.seed(20260724)
order = (G, M, R, k, m_p, m_e)
Tf = sp.lambdify(order, T_ref, 'math')
Pf = sp.lambdify(order, PV / (N * k), 'math')
ok_rand = True
for _ in range(200):
    p = [random.uniform(0.5, 5.0) for _ in order]
    a, b = Tf(*p), Pf(*p)
    if abs(a - b) > 1e-9 * max(1.0, abs(b)):
        ok_rand = False
        break
checks['numeric_random'] = ok_rand

# ---- self-refutation report -------------------------------------------
for name, ok in checks.items():
    print(f"CHECK {name}: {'OK' if ok else 'FAIL'}")

if all(checks.values()):
    print(f"<T> = G M (m_p+m_e)/(10 R k) = {T_num:.4e} K")
    print("VERDICT: PASS")
    print("FINAL ANSWER: 2.31e6 K")
else:
    print(f"computed <T> = {T_num:.6e} K ; expected 2.31e6 K")
    print("VERDICT: FAIL")
