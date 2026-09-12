param(
    [ValidateSet("local", "astrum")]
    [string]$Oracle = "local",
    [int]$Timeout = 240
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "ASTRA virtual environment not found: $Python"
}

$source = @'
# ASTRA_ENGINE: lean4
import Mathlib

open scoped BigOperators

example (x y : ℝ) : (x + y)^2 = x^2 + 2*x*y + y^2 := by
  ring

example (x y : ℝ) (hxy : x ≤ y) : x + 1 ≤ y + 1 := by
  linarith

example (x : ℝ) : 0 ≤ x^2 := by
  positivity

example : (∑ i ∈ Finset.range 5, i) = 10 := by
  norm_num

example (A : Matrix (Fin 2) (Fin 2) ℝ) : A + 0 = A := by
  simp

example (x : ℝ) : HasDerivAt (fun t : ℝ => t^3) (3*x^2) x := by
  exact hasDerivAt_pow 3 x

example (n : ℕ) : n ≤ n + 2 := by
  omega
'@

$env:ASTRA_LEAN4_SMOKE_SOURCE = $source
$env:ASTRA_LEAN4_SMOKE_ORACLE = $Oracle
$env:ASTRA_LEAN4_SMOKE_TIMEOUT = $Timeout.ToString()

Push-Location $Root
try {
    & $Python -c @'
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

from core.formal_validators import evaluate_lean4_source

result = asyncio.run(
    evaluate_lean4_source(
        os.environ["ASTRA_LEAN4_SMOKE_SOURCE"],
        oracle=os.environ["ASTRA_LEAN4_SMOKE_ORACLE"],
        timeout=int(os.environ["ASTRA_LEAN4_SMOKE_TIMEOUT"]),
    )
)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result.get("status") == "PASS" else 1)
'@
    if ($LASTEXITCODE -ne 0) {
        throw "Lean 4 + Mathlib smoke test failed through the '$Oracle' oracle."
    }
}
finally {
    Pop-Location
    Remove-Item Env:ASTRA_LEAN4_SMOKE_SOURCE -ErrorAction SilentlyContinue
    Remove-Item Env:ASTRA_LEAN4_SMOKE_ORACLE -ErrorAction SilentlyContinue
    Remove-Item Env:ASTRA_LEAN4_SMOKE_TIMEOUT -ErrorAction SilentlyContinue
}
