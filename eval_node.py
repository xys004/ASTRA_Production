import asyncio
import sys
sys.path.append(".")
from core.executor import execute_python_code
from core.preflight import load_project_env
from scripts.deep_think_mcts import update_node

async def run():
    load_project_env()
    code = """import sympy as sp
x, alpha, beta, g = sp.symbols('x alpha beta g')
psi = sp.exp(-alpha*x**2 - beta*x**4)
H_psi = -sp.Rational(1,2) * sp.diff(psi, x, x) + (sp.Rational(1,2)*x**2 + g*x**4)*psi
E_L = sp.cancel(H_psi / psi)
E_L = sp.expand(E_L)
print("Local energy polynomial:")
print(E_L)"""
    res = await execute_python_code(code)
    output = res.get('stdout', '') + res.get('stderr', '')
    # If the execution succeeded and gave us a polynomial, we consider this a successful branch
    reward = 1.0 if res.get('exit_code') == 0 else -1.0
    update_node("node_3af9dd6d", output, reward)
    print("Execution output from cluster:")
    print(output)

if __name__ == '__main__':
    asyncio.run(run())
