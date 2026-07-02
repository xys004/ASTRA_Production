$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    $script = @'
import asyncio
import json
from core.preflight import load_project_env
from core.executor import execute_python_code

load_project_env()

CASES = [
    ("python", "print(123)", "123"),
    (
        "sympy_scipy",
        "import sympy as sp\nimport scipy.integrate as si\nx=sp.symbols('x')\nprint(sp.integrate(sp.sin(x), x))\nprint(round(si.quad(lambda t: t*t, 0, 1)[0], 6))",
        "-cos(x)",
    ),
    (
        "maxima",
        "# ASTRA_ENGINE: maxima\nexpand((x+1)^3);\n",
        "3 x",
    ),
    (
        "sage",
        "# ASTRA_ENGINE: sage\nprint(factor(x^2 - 1))\n",
        "(x + 1)*(x - 1)",
    ),
    (
        "cadabra",
        "# ASTRA_ENGINE: cadabra\n{a,b,c}::Indices.\nex:= A_{a} B_{b};\nprint(ex);\n",
        "A_{a} B_{b}",
    ),
]

async def main():
    failed = False
    for name, code, expected in CASES:
        result = await execute_python_code(code, timeout=90)
        summary = {
            "case": name,
            "exit_code": result.get("exit_code"),
            "engine": result.get("engine"),
            "remote_host": result.get("remote_host"),
            "stdout": result.get("stdout", "")[:300],
            "stderr": result.get("stderr", "")[:300],
        }
        print(json.dumps(summary, ensure_ascii=False))
        if result.get("exit_code") != 0 or expected not in result.get("stdout", ""):
            failed = True
    raise SystemExit(1 if failed else 0)

asyncio.run(main())
'@

    $script | python -
}
finally {
    Pop-Location
}

