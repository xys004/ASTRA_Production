"""Print a non-secret, machine-readable audit of ASTRA production topology."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.architecture_contract import audit_production_architecture
from core.preflight import load_project_env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-binary-check",
        action="store_true",
        help="Audit configuration without checking CLI executables on PATH.",
    )
    args = parser.parse_args()
    load_project_env()
    audit = audit_production_architecture(
        check_binaries=not args.no_binary_check,
    )
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
