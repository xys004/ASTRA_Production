# ASTRA_ENGINE: lean4
import Mathlib

open BigOperators

theorem zero_trace_of_pointwise_zero
    (diagonal : Fin 4 → ℝ)
    (h : ∀ i, diagonal i = 0) :
    (∑ i, diagonal i) = 0 := by
  simp [h]
