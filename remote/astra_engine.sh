#!/usr/bin/env bash
# astra_engine.sh — despachador único de motores de cálculo en el clúster Astrum.
#
#   astra_engine.sh <motor> <fichero> [args...]
#   astra_engine.sh list
#
# Problema que resuelve: los motores viven en CINCO entornos distintos y cada uno
# tiene su intérprete. Sin esto, mandar un cálculo exige recordar rutas absolutas
# como ~/miniforge3/envs/sci/bin/python. Con esto, el emisor solo dice QUÉ motor
# quiere; dónde vive es problema del clúster.
#
# ASTRA vive en la máquina de Nelson. Esto es solo su BRAZO de cálculo.
set -uo pipefail

H="$HOME"
declare -A ENGINES=(
  [oracle]="$H/astra-worker/venv/bin/python"          # sympy z3 qutip numba torch cupy jax
  [sci]="$H/miniforge3/envs/sci/bin/python"           # ase pyscf gpaw pymatgen kwant spglib
  [sage]="$H/miniforge3/envs/sage/bin/sage"           # SageMath 10.7 (+ sage.manifolds, GR)
  [cadabra]="$H/miniforge3/envs/cadabra/bin/cadabra2" # álgebra tensorial (.cdb)
  [cadabra-py]="$H/miniforge3/envs/cadabra/bin/python" # cadabra2 desde Python
  [maxima]="/usr/bin/maxima"
  [lean]="$H/astra-worker/lean_verify.sh"             # Lean4 + mathlib4 compilado
  [pkgs]="$H/miniforge3/envs/pkgs/bin/python"         # paquetes propios de Nelson
)
declare -A DESC=(
  [oracle]="numérico/simbólico general + GPU (sympy, z3, qutip, torch, cupy, jax)"
  [sci]="materia condensada / DFT (ase, pyscf, gpaw, pymatgen, kwant, spglib)"
  [sage]="SageMath 10.7 — simbólico pesado, sage.manifolds para GR"
  [cadabra]="álgebra tensorial de campos (ficheros .cdb)"
  [cadabra-py]="cadabra2 vía API de Python"
  [maxima]="CAS clásico"
  [lean]="verificación formal contra mathlib4 (solo lectura, sin lake)"
  [pkgs]="paquetes propios (ver ~/pkgs/README.md) — GR: GR_python+grthermo, pyWarpFactory, TELAR, warp_nn, natario, metric-engine | fundamentos: protoespacio | materia condensada: QuantumTransportEOM, mobius_rsoc | fluidos: rectification"
)

if [ "${1:-list}" = "list" ]; then
  echo "Motores disponibles en $(hostname):"
  for k in oracle sci sage cadabra cadabra-py maxima lean pkgs; do
    b="${ENGINES[$k]}"
    if [ -x "$b" ]; then s="OK "; else s="NO "; fi
    printf "  [%s] %-11s %s\n" "$s" "$k" "${DESC[$k]}"
  done
  echo
  echo "uso: $0 <motor> <fichero> [args...]"
  exit 0
fi

ENGINE="$1"; shift
BIN="${ENGINES[$ENGINE]:-}"
[ -n "$BIN" ] || { echo "motor desconocido: $ENGINE (prueba: $0 list)" >&2; exit 2; }
[ -x "$BIN" ] || { echo "motor '$ENGINE' no instalado en $BIN" >&2; exit 127; }
[ $# -ge 1 ] || { echo "falta el fichero a ejecutar" >&2; exit 2; }

# maxima necesita -b para lotes no interactivos; el resto toma el fichero directo.
if [ "$ENGINE" = "maxima" ]; then
  exec "$BIN" --very-quiet -b "$@"
fi
exec "$BIN" "$@"
