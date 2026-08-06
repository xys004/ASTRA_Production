#!/usr/bin/env bash
# Restore only missing compiled dependencies from the pinned mathlib manifest.
# This never runs `lake update` at the mathlib root and never changes revisions.
set -euo pipefail

MATHLIB="${ASTRA_LEAN4_ROOT:-$HOME/astra-benchmarks/mathlib4-v4.30.0}"
GIT_BIN="${ASTRA_REMOTE_GIT_BIN:-$HOME/miniforge3/envs/astra-bench/bin/git}"
LAKE_BIN="${ASTRA_REMOTE_LAKE_BIN:-$HOME/.elan/bin/lake}"
MANIFEST="$MATHLIB/lake-manifest.json"

[ -f "$MANIFEST" ] || { echo "missing manifest: $MANIFEST" >&2; exit 2; }
[ -x "$GIT_BIN" ] || { echo "missing managed git: $GIT_BIN" >&2; exit 2; }
[ -x "$LAKE_BIN" ] || { echo "missing lake: $LAKE_BIN" >&2; exit 2; }

for name in plausible aesop batteries Qq proofwidgets importGraph; do
  package="$MATHLIB/.lake/packages/$name"
  compiled="$package/.lake/build/lib/lean"
  [ -d "$compiled" ] && continue

  metadata="$(python3 - "$MANIFEST" "$name" <<'PY'
import json, sys
manifest, name = sys.argv[1:]
data = json.load(open(manifest, encoding="utf-8"))
for package in data.get("packages", []):
    if package.get("name") == name:
        print(package.get("url", ""))
        print(package.get("rev", ""))
        break
PY
)"
  url="$(printf '%s\n' "$metadata" | sed -n '1p')"
  rev="$(printf '%s\n' "$metadata" | sed -n '2p')"
  [ -n "$url" ] && [ -n "$rev" ] || {
    echo "package $name is absent from the pinned manifest" >&2
    exit 3
  }

  if [ ! -d "$package/.git" ]; then
    if [ -e "$package" ]; then
      backup="$package.unusable.$(date +%Y%m%d-%H%M%S)"
      mv -- "$package" "$backup"
      echo "preserved unusable package at $backup" >&2
    fi
    "$GIT_BIN" clone "$url" "$package"
  fi
  current="$($GIT_BIN -C "$package" rev-parse HEAD)"
  if [ "$current" != "$rev" ]; then
    if [ -n "$($GIT_BIN -C "$package" status --porcelain)" ]; then
      echo "refusing to change dirty package $name ($current != $rev)" >&2
      exit 4
    fi
    "$GIT_BIN" -C "$package" fetch --depth 1 origin "$rev"
    "$GIT_BIN" -C "$package" checkout --detach "$rev"
  fi
  (cd "$package" && "$LAKE_BIN" build)
done

echo "Pinned Lean dependencies are compiled."
