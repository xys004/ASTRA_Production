"""
ASTRA — Subscription-CLI backend.

Permite que ASTRA_Production use los CLIs de suscripcion (Claude Code, Codex)
en lugar de APIs de pago. La idea: NO se paga API; se usan las mensualidades
de Claude/ChatGPT a traves de sus CLIs oficiales en modo headless.

Este modulo expone una sola funcion sincrona `call_cli(kind, prompt, ...)`
que `core/llm_client.py` invoca (via asyncio.to_thread) desde `_call_api`.

Windows: `claude` y `gemini` son shims .ps1 (no .exe); `codex` es .exe. Para
uniformar, todo se invoca a traves de PowerShell y el prompt viaja en un archivo
temporal (cero problemas de comillas o limite de longitud de argv).

GOTCHAS resueltos en la puesta a punto (no reaparezcas):
  * Codex se CUELGA sin EOF en stdin -> se le pasa el prompt POR stdin
    (Get-Content archivo | codex exec ... -) y subprocess usa stdin=DEVNULL.
  * Codex necesita CLI >= 0.144 para los modelos gpt-5.6-* (usar `codex update`).
  * --ignore-user-config silencia los MCP servers del usuario (la auth vive en
    CODEX_HOME, sigue autenticado con ChatGPT).
  * El sandbox de Codex es experimental en Windows y se cuelga; como los agentes
    aqui solo GENERAN texto, se salta con --dangerously-bypass-approvals-and-sandbox.
  * Claude: --output-format json, se lee el campo "result".
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

# Directorio de trabajo para el -C de codex (dir del proyecto/workspace).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_WS = os.path.join(_PROJECT_ROOT, "workspace")


@dataclass
class CliResult:
    ok: bool
    text: str = ""
    error: str = ""
    cost_usd: float = 0.0     # proxy de consumo (contabilidad, NO cargo real)


def _ps_claude(promptfile: str, model: str | None, _out: str, _ws: str) -> str:
    m = f" --model {model}" if model else ""
    return (f'$p = Get-Content -Raw -LiteralPath "{promptfile}"; '
            f'claude -p $p --output-format json{m}')


def _ps_codex(promptfile: str, model: str | None, out: str, ws: str) -> str:
    m = f" -m {model}" if model else ""
    return (f'Get-Content -Raw -LiteralPath "{promptfile}" | '
            f'codex exec --dangerously-bypass-approvals-and-sandbox --ignore-user-config '
            f'--skip-git-repo-check{m} -C "{ws}" -o "{out}" -')


_BUILDERS = {"claude": _ps_claude, "codex": _ps_codex}


def _parse_claude(stdout: str, _outfile: str) -> tuple[str, float]:
    data = json.loads(stdout.strip().splitlines()[-1])
    if data.get("is_error"):
        raise RuntimeError(data.get("result", "claude is_error=true"))
    return data.get("result", ""), float(data.get("total_cost_usd", 0.0) or 0.0)


def _parse_codex(_stdout: str, outfile: str) -> tuple[str, float]:
    with open(outfile, encoding="utf-8", errors="replace") as f:
        return f.read().strip(), 0.0


_PARSERS = {"claude": _parse_claude, "codex": _parse_codex}


def call_cli(kind: str, prompt: str, timeout: int = 600,
             model: str | None = None, workspace: str | None = None,
             env_extra: dict | None = None) -> CliResult:
    """
    Invoca un CLI de suscripcion en modo headless y devuelve su texto.
    kind: "claude" | "codex".
    """
    if kind not in _BUILDERS:
        return CliResult(False, error=f"kind CLI desconocido: {kind}")

    ws = workspace or _DEFAULT_WS
    os.makedirs(ws, exist_ok=True)

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    for k, v in (env_extra or {}).items():
        env[k] = str(v)

    tmpdir = tempfile.mkdtemp(prefix="astra_cli_")
    promptfile = os.path.join(tmpdir, "prompt.txt")
    outfile = os.path.join(tmpdir, "codex_out.txt")
    with open(promptfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    ps_body = _BUILDERS[kind](promptfile, model, outfile, ws)
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_body]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return CliResult(False, error=f"timeout tras {timeout}s")

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        return CliResult(False, error=f"exit {proc.returncode}: {tail.strip()}")

    try:
        text, cost = _PARSERS[kind](proc.stdout, outfile)
    except Exception as e:
        return CliResult(False, error=f"parseo fallo: {type(e).__name__}: {e}")

    if not text.strip():
        # respuesta vacia suele indicar tope de cuota; la reportamos como error
        tail = (proc.stdout or "")[-300:]
        return CliResult(False, error=f"respuesta vacia (posible tope de cuota). {tail.strip()}")

    return CliResult(True, text=text, cost_usd=cost)


if __name__ == "__main__":
    import sys
    k = sys.argv[1] if len(sys.argv) > 1 else "claude"
    p = sys.argv[2] if len(sys.argv) > 2 else "Responde solo: LISTO"
    r = call_cli(k, p, timeout=120)
    print(f"ok={r.ok} cost=${r.cost_usd:.4f} err={r.error}")
    print(r.text[:1000])
