#!/usr/bin/env bash
set -euo pipefail

# User-space benchmark environment for ASTRUM. No sudo is required.
BENCH_ROOT="${ASTRA_BENCH_ROOT:-$HOME/astra-benchmarks}"
CONDA_BIN="${ASTRA_CONDA_BIN:-$HOME/miniforge3/bin/conda}"
ENV_DIR="${ASTRA_BENCH_ENV:-$HOME/miniforge3/envs/astra-bench}"
MINIF2F_COMMIT="f0dcc8b59e630fba00ba9569ca6714700e0a8801"
MATHLIB_COMMIT="cb2b02fff213ed6f65bebd64446baac64137dcda"
LEAN_TOOLCHAIN="leanprover-community/lean:3.42.1"
LEAN_INSTALLED_NAME="leanprover-community/lean:v3.42.1"
LEAN4_TOOLCHAIN="leanprover/lean4:v4.30.0"
LEAN4_INSTALLED_NAME="leanprover/lean4:v4.30.0"
MATHLIB4_TAG="v4.30.0"
MATHLIB4_COMMIT="c5ea00351c28e24afc9f0f84379aa41082b1188f"

if [[ ! -x "$CONDA_BIN" ]]; then
  echo "Missing Miniforge/Conda executable: $CONDA_BIN" >&2
  exit 2
fi

mkdir -p "$BENCH_ROOT"

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  "$CONDA_BIN" create -y -p "$ENV_DIR" python=3.11 pip git curl
fi

"$CONDA_BIN" install -y -p "$ENV_DIR" git curl
"$ENV_DIR/bin/pip" install --upgrade mathlibtools udocker

if [[ ! -x "$HOME/.elan/bin/elan" ]]; then
  ELAN_INSTALLER="$BENCH_ROOT/elan-init.sh"
  "$ENV_DIR/bin/curl" -sSfL https://elan.lean-lang.org/elan-init.sh \
    -o "$ELAN_INSTALLER"
  sh "$ELAN_INSTALLER" -y --default-toolchain none --no-modify-path
fi

if ! "$HOME/.elan/bin/elan" toolchain list | grep -Fq "$LEAN_INSTALLED_NAME"; then
  "$HOME/.elan/bin/elan" toolchain install "$LEAN_TOOLCHAIN"
fi
if ! "$HOME/.elan/bin/elan" toolchain list | grep -Fq "$LEAN4_INSTALLED_NAME"; then
  "$HOME/.elan/bin/elan" toolchain install "$LEAN4_TOOLCHAIN"
fi
"$HOME/.elan/bin/elan" default "$LEAN_TOOLCHAIN"

MINIF2F_DIR="$BENCH_ROOT/miniF2F"
if [[ ! -d "$MINIF2F_DIR/.git" ]]; then
  "$ENV_DIR/bin/git" clone --filter=blob:none \
    https://github.com/openai/miniF2F.git "$MINIF2F_DIR"
fi

"$ENV_DIR/bin/git" -C "$MINIF2F_DIR" fetch --depth 1 origin "$MINIF2F_COMMIT"
"$ENV_DIR/bin/git" -C "$MINIF2F_DIR" checkout --detach "$MINIF2F_COMMIT"

export PATH="$ENV_DIR/bin:$HOME/.elan/bin:$PATH"
(
  cd "$MINIF2F_DIR"
  "$HOME/.elan/bin/leanpkg" configure
  "$ENV_DIR/bin/leanproject" get-mathlib-cache
)

ACTUAL_MATHLIB="$(
  "$ENV_DIR/bin/git" -C "$MINIF2F_DIR/_target/deps/mathlib" rev-parse HEAD
)"
if [[ "$ACTUAL_MATHLIB" != "$MATHLIB_COMMIT" ]]; then
  echo "Unexpected mathlib commit: $ACTUAL_MATHLIB" >&2
  exit 3
fi

MATHLIB4_DIR="$BENCH_ROOT/mathlib4-$MATHLIB4_TAG"
if [[ ! -d "$MATHLIB4_DIR/.git" ]]; then
  "$ENV_DIR/bin/git" clone --filter=blob:none --branch "$MATHLIB4_TAG" \
    https://github.com/leanprover-community/mathlib4.git "$MATHLIB4_DIR"
fi

"$ENV_DIR/bin/git" -C "$MATHLIB4_DIR" fetch --depth 1 origin "$MATHLIB4_TAG"
"$ENV_DIR/bin/git" -C "$MATHLIB4_DIR" checkout --detach "$MATHLIB4_COMMIT"
(
  cd "$MATHLIB4_DIR"
  "$HOME/.elan/bin/lake" exe cache get
)

ACTUAL_MATHLIB4="$(
  "$ENV_DIR/bin/git" -C "$MATHLIB4_DIR" rev-parse HEAD
)"
if [[ "$ACTUAL_MATHLIB4" != "$MATHLIB4_COMMIT" ]]; then
  echo "Unexpected Mathlib 4 commit: $ACTUAL_MATHLIB4" >&2
  exit 4
fi

export UDOCKER_DIR="$BENCH_ROOT/udocker"
"$ENV_DIR/bin/udocker" install

"$HOME/.elan/bin/lean" --version
(
  cd "$MATHLIB4_DIR"
  "$HOME/.elan/bin/lake" env lean --version
)
"$ENV_DIR/bin/udocker" version
echo "ASTRUM external benchmark environment is ready at $BENCH_ROOT"
