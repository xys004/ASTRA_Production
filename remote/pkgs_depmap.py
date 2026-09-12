#!/usr/bin/env python3
"""
Mapa de dependencias de los paquetes propios: qué DECLARAN vs qué IMPORTAN.

Objetivo: decidir cuáles pueden convivir en un env y cuáles necesitan el suyo.
Dos señales distintas, y la discrepancia entre ellas es lo interesante:

  DECLARADO  lo que dice pyproject/setup.py. Es la intención.
  IMPORTADO  lo que el código realmente hace `import`. Es la realidad.

Un import no declarado es una dependencia oculta: el paquete funciona en la
máquina donde se escribió y falla en otra. Una declaración sin import es peso
muerto que puede arrastrar conflictos de versión sin dar nada a cambio.

También detecta acoplamiento ENTRE paquetes propios (p. ej. mobius importa
grthermo), que es lo que obliga a instalarlos juntos o a ordenar la instalación.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / "pkgs"

PKGS = {
    "grthermo": "gr/grthermo",
    "protoespacio": "physics/protoespacio",
    "metric-engine": "metric-engine",
    "warp_nn": "warp/warp_nn",
    "pyWarpFactory": "warp/pyWarpFactory_push",
    "QuantumTransportEOM": "quantum/QuantumTransportEOM",
    "TELAR": "warp/TELAR",
    "natario": "warp/natario_energy_bound",
    "mobius_rsoc": "quantum/mobius_cylinder_rsoc",
    "rectification": "physics/rectification_design_map",
}

STDLIB = set(sys.stdlib_module_names)
# nombres de módulo de los propios paquetes, para detectar acoplamiento interno
OWN_MODULES = {
    "grthermo": "grthermo", "telar": "TELAR", "warp_nn": "warp_nn",
    "metric_engine": "metric-engine", "warpfactory": "pyWarpFactory",
    "pywarpfactory": "pyWarpFactory", "qteom": "QuantumTransportEOM",
    "quantumtransporteom": "QuantumTransportEOM", "validators": "protoespacio",
}


def declared(p: Path) -> list[str]:
    out = []
    pj = p / "pyproject.toml"
    sp = p / "setup.py"
    txt = ""
    if pj.exists():
        txt = pj.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", txt, re.S | re.M)
        if m:
            out = re.findall(r'"([A-Za-z0-9_.\-\[\]]+)', m.group(1))
    elif sp.exists():
        txt = sp.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"install_requires\s*=\s*\[(.*?)\]", txt, re.S)
        if m:
            out = re.findall(r'"([A-Za-z0-9_.\-\[\]]+)', m.group(1))
    return sorted({re.split(r"[<>=\[]", d)[0].lower() for d in out})


def imported(p: Path) -> tuple[set[str], set[str]]:
    """Devuelve (externos, propios). Sólo el primer componente del módulo."""
    ext, own = set(), set()
    for f in p.rglob("*.py"):
        if any(x in f.parts for x in ("__pycache__", ".venv", "venv", "build")):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:      # import relativo: interno del paquete
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                if not n or n in STDLIB:
                    continue
                low = n.lower()
                if low in OWN_MODULES:
                    own.add(OWN_MODULES[low])
                else:
                    ext.add(low)
    return ext, own


def main() -> int:
    rows = {}
    ext_by_pkg = {}
    for name, rel in PKGS.items():
        p = ROOT / rel
        if not p.exists():
            continue
        d = declared(p)
        e, o = imported(p)
        # sus propios módulos no cuentan como dependencia externa
        e -= {name.lower().replace("-", "_")}
        rows[name] = {"declared": d, "imported_ext": sorted(e),
                      "imports_own": sorted(o - {name})}
        ext_by_pkg[name] = e

    print("=" * 78)
    print("PAQUETES INSTALADOS Y SUS DEPENDENCIAS")
    print("=" * 78)
    for name, r in rows.items():
        print(f"\n### {name}")
        print(f"  declara : {', '.join(r['declared']) or '(nada — no empaquetado)'}")
        top = [x for x in r["imported_ext"] if x not in ("setuptools", "pytest")]
        print(f"  importa : {', '.join(top[:14])}{' …' if len(top) > 14 else ''}")
        undecl = [x for x in top if x not in r["declared"]]
        if undecl and r["declared"]:
            print(f"  ** OCULTAS (importa sin declarar): {', '.join(undecl[:10])}")
        if r["imports_own"]:
            print(f"  ** DEPENDE DE TUS PAQUETES: {', '.join(r['imports_own'])}")

    print("\n" + "=" * 78)
    print("ACOPLAMIENTO ENTRE TUS PAQUETES")
    print("=" * 78)
    edges = [(a, b) for a, r in rows.items() for b in r["imports_own"]]
    if edges:
        for a, b in edges:
            print(f"  {a}  ->  {b}")
    else:
        print("  ninguno")

    print("\n" + "=" * 78)
    print("PESOS PESADOS (candidatos a env propio)")
    print("=" * 78)
    heavy = {"jax", "jaxlib", "torch", "tensorflow", "optax", "jaxopt",
             "petsc4py", "pyamg", "cupy", "z3"}
    for name, e in ext_by_pkg.items():
        h = sorted(e & heavy)
        if h:
            print(f"  {name:22} {', '.join(h)}")

    print("\n" + "=" * 78)
    print("CONFLICTOS DE VERSION DECLARADOS")
    print("=" * 78)
    pins = defaultdict(set)
    for name, rel in PKGS.items():
        p = ROOT / rel
        for f in (p / "pyproject.toml", p / "setup.py", p / "requirements.txt"):
            if not f.exists():
                continue
            for dep, op, ver in re.findall(
                    r'"?([A-Za-z0-9_\-]+)\s*(>=|==|<=|<|>)\s*([0-9][0-9.]*)',
                    f.read_text(encoding="utf-8", errors="ignore")):
                pins[dep.lower()].add(f"{op}{ver} ({name})")
    for dep, vs in sorted(pins.items()):
        if len(vs) > 1:
            print(f"  {dep:16} {' | '.join(sorted(vs))}")

    (Path.home() / "pkgs_depmap.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nescrito: {Path.home() / 'pkgs_depmap.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
