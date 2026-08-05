#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -x venv/bin/python ]; then
  echo "ASTRA is not installed. Run: bash install_macos.sh" >&2
  exit 2
fi

(sleep 2; open http://127.0.0.1:5050) >/dev/null 2>&1 &
exec venv/bin/python web/app.py
