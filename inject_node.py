import sys
sys.path.append(".")
from scripts.deep_think_mcts import add_node

conj = "Trial wave function psi(x) = exp(-alpha*x**2 - beta*x**4). Compute local energy residual using sympy."
code = """import sympy as sp
x, alpha, beta, g = sp.symbols('x alpha beta g')
psi = sp.exp(-alpha*x**2 - beta*x**4)
H_psi = -sp.Rational(1,2) * sp.diff(psi, x, x) + (sp.Rational(1,2)*x**2 + g*x**4)*psi
E_L = sp.cancel(H_psi / psi)
E_L = sp.expand(E_L)
print("Local energy polynomial:")
print(E_L)"""

new_id = add_node("root", conj, code)
print("NODE_ID:", new_id)
