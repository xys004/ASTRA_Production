#!/usr/bin/env bash
# lean_verify.sh — verifica un fichero Lean 4 contra el mathlib YA COMPILADO
# del cluster. Uso:  lean_verify.sh fichero.lean
#
# POR QUE NO USA lake (2026-07-31, aprendido rompiendolo):
# `lake` resuelve dependencias en cada invocacion. Si decide que la URL de un
# paquete cambio, BORRA el directorio y lo reclona — y si falta git, o no hay
# red, te quedas sin la dependencia y mathlib deja de importar. Eso le paso a
# `plausible` en este nodo: una sola llamada a `lake env lean` destruyo el
# paquete. Para VERIFICAR una prueba no hace falta resolver nada: los oleans ya
# estan compilados. Este script solo arma LEAN_PATH y llama a `lean`.
#
# Salida: codigo 0 = teorema verificado (sin stdout). !=0 = rechazado, con el
# error de Lean en stderr. Determinista, sin red, sin escritura en mathlib.
set -uo pipefail

MATHLIB="${ASTRA_LEAN4_ROOT:-$HOME/astra-benchmarks/mathlib4-v4.30.0}"
TOOLCHAIN="${ASTRA_LEAN4_TOOLCHAIN:-$HOME/.elan/toolchains/leanprover--lean4---v4.30.0}"
LEAN_BIN="$TOOLCHAIN/bin/lean"

[ -x "$LEAN_BIN" ] || { echo "lean_verify: no existe $LEAN_BIN" >&2; exit 127; }
[ -d "$MATHLIB/.lake/build/lib/lean" ] || {
  echo "lean_verify: mathlib no compilado en $MATHLIB" >&2; exit 127; }
[ $# -ge 1 ] || { echo "uso: $0 fichero.lean [args de lean]" >&2; exit 2; }

# mathlib primero, luego cada paquete. Si falta alguno, avisar en vez de fallar
# con un críptico "unknown module prefix".
LP="$MATHLIB/.lake/build/lib/lean"
for p in "$MATHLIB"/.lake/packages/*/.lake/build/lib/lean; do
  [ -d "$p" ] && LP="$LP:$p"
done
for req in plausible aesop batteries Qq proofwidgets importGraph; do
  case "$LP" in
    *"/$req/"*) ;;
    *) echo "lean_verify: AVISO — falta el paquete '$req' compilado; " \
            "algunos imports de Mathlib fallaran. Restaurar con: " \
            "~/astra-worker/repair_lean_mathlib.sh" >&2 ;;
  esac
done

exec env LEAN_PATH="$LP" "$LEAN_BIN" "$@"
