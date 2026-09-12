# ASTRA 0.3.0 — macOS collaborator release

This release turns ASTRA into a reproducible collaborator workstation on
Apple Silicon macOS while preserving the compact three-model production
architecture.

Highlights:

- native macOS invocation for Codex, Claude Code, and Antigravity `agy`;
- cross-platform process-group termination for bounded model calls and MCP jobs;
- one-command Python/MCP setup with `install_macos.sh`;
- workspace-scoped Antigravity MCP registration;
- non-destructive `astra_doctor.py` installation audit;
- individual Tailscale/SSH onboarding without shared private keys;
- ASTRUM engine discovery through `astra_engines`;
- managed `sci` and company-package `pkgs` execution through ASTRA;
- English and Spanish macOS onboarding documentation.

Validation at release preparation:

- production architecture contract: PASS;
- development test suite with pinned external caches: 126 passed;
- clean-clone suite: 118 passed, 8 optional external-benchmark tests skipped;
- ASTRUM smoke check: Python, SymPy/SciPy, Maxima, SageMath, Cadabra, and
  company-package environment passed.

An actual Mac acceptance run remains required after cloning because CLI login,
Tailscale membership, and the SSH key are intentionally per-user state.
