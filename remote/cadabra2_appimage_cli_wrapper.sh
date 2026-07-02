#!/usr/bin/env bash
set -euo pipefail

ROOT="${CADABRA_APPDIR:-$HOME/Applications/Cadabra_2.5.14_x86_64_extracted}"
LOADER="$ROOT/runtime/default/lib64/ld-linux-x86-64.so.2"
LIB_PATH="$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/usr/lib:$ROOT/runtime/default/lib/x86_64-linux-gnu:$ROOT/runtime/default/lib"

export PATH="$ROOT/usr/bin:$PATH"
export PYTHONPATH="$ROOT/usr/lib/python3/dist-packages:$ROOT/usr/lib/python3.10/dist-packages:${PYTHONPATH:-}"

exec "$LOADER" --library-path "$LIB_PATH" "$ROOT/usr/bin/cadabra2-cli" "$@"
