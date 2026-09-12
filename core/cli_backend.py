"""
ASTRA — Subscription-CLI backend.

Permite que ASTRA_Production use los CLIs de suscripcion (Claude Code, Codex)
en lugar de APIs de pago. La idea: NO se paga API; se usan las mensualidades
de Claude/ChatGPT a traves de sus CLIs oficiales en modo headless.

Este modulo expone una sola funcion sincrona `call_cli(kind, prompt, ...)`
que `core/llm_client.py` invoca (via asyncio.to_thread) desde `_call_api`.

Windows: `claude` (>=2.x) y `agy` son .exe NATIVOS y se invocan DIRECTO por argv
(claude ademas con el prompt por stdin); `codex`/`gemini` siguen via PowerShell.
OJO 2026-07-19: PowerShell SIN CONSOLA (server MCP lanzado por el host de
escritorio) pierde el stdout de sus hijos nativos -> por eso claude se saco de
PowerShell. El prompt siempre viaja en archivo temporal (cero problemas de
comillas o limite de longitud de argv).

GOTCHAS resueltos en la puesta a punto (no reaparezcas):
  * Codex se CUELGA sin EOF en stdin -> se le pasa el prompt POR stdin
    (Get-Content archivo | codex exec ... -) y subprocess usa stdin=DEVNULL.
  * Codex necesita CLI >= 0.144 para los modelos gpt-5.6-* (usar `codex update`).
  * --ignore-user-config silencia los MCP servers del usuario (la auth vive en
    CODEX_HOME, sigue autenticado con ChatGPT).
  * El sandbox de Codex es experimental en Windows y se cuelga; como los agentes
    aqui solo GENERAN texto, se salta con --dangerously-bypass-approvals-and-sandbox.
  * Claude: --output-format json, se lee el campo "result".
  * Las cuotas de suscripcion son POR MODELO, no por cuenta: agotar Fable/Opus
    no agota Sonnet. La escalera ASTRA_*_MODELS (abajo) explota exactamente eso.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import shutil
import subprocess
import tempfile
import uuid
from pathlib import PureWindowsPath
from dataclasses import dataclass

# Directorio de trabajo para el -C de codex (dir del proyecto/workspace).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_WS = os.path.join(_PROJECT_ROOT, "workspace")

# CREATE_NO_WINDOW: cuando el padre NO tiene consola (runner de ciclo lanzado
# con DETACHED_PROCESS, o el server MCP lanzado por el host de escritorio),
# cada hijo de consola (powershell, codex, claude, agy, taskkill) abria una
# VENTANA visible y vacia que vivia lo que durase la fase (30-420 s) — las
# "ventanas PowerShell sin nada" reportadas en produccion. Con este flag el
# hijo recibe una consola OCULTA: sigue TENIENDO consola (no reaparece el
# gotcha 2026-07-19 de "PowerShell sin consola pierde el stdout de sus hijos
# nativos", que era el caso DETACHED/sin consola), y el stdout/stderr van por
# pipes igual que antes.
_NT_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass
class CliResult:
    ok: bool
    text: str = ""
    error: str = ""
    cost_usd: float = 0.0     # proxy de consumo (contabilidad, NO cargo real)
    model_used: str = ""      # modelo que respondio ('default' = el configurado del CLI)
    warning: str = ""         # aviso cuando la respuesta vino de un modelo fallback
    account_profile: str = "" # perfil local de credenciales usado por este proceso


def _claude_bin() -> str:
    """Resuelve el claude.exe NATIVO que hay detras del shim npm.

    2026-07-19: claude >=2.x es un .exe nativo (no node). Invocarlo via
    PowerShell (shim .ps1) FALLA cuando el proceso padre no tiene consola
    (caso: server MCP lanzado por el host de escritorio de Claude): PowerShell
    sin consola PIERDE el stdout de sus hijos nativos -> "salida vacia" en
    --version y en cada fase (los ciclos morian en conjecture al agotar los
    420s). El exe directo con stdin por pipe funciona en ese mismo entorno.
    ASTRA_CLAUDE_BIN en .env permite fijar otra ruta sin tocar codigo."""
    b = (os.environ.get("ASTRA_CLAUDE_BIN") or "").strip().strip("'\"")
    if b:
        return b
    shim = shutil.which("claude")
    if shim:
        exe = os.path.join(os.path.dirname(shim), "node_modules",
                           "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.exists(exe):
            return exe
    return shim or "claude"


def _claude_argv(promptfile: str, model: str | None, _out: str, _ws: str) -> dict:
    # Prompt por STDIN (pipe), NO como argumento: los prompts de ASTRA superan el
    # limite de ~32KB de la linea de comandos de Windows y claude devolvia vacio.
    # Claude Code is AGENTIC: every ASTRA phase supplies all allowed context through
    # the prompt and expects text on stdout. An explicit deny-list proved insufficient
    # on Windows because newer Claude releases can expose PowerShell under a tool name
    # other than Bash. `--tools ""` is the CLI's supported hard disable for all tools.
    tools = ["--tools", ""]
    # Without this, every claude -p call here loads the user's GLOBAL MCP config:
    # Gmail/Calendar/Drive, two npx filesystem servers that fail to connect (each a
    # potential multi-second-to-hung npx registry fetch), and -- critically -- a second,
    # RECURSIVE copy of this very astra MCP server, exposing astra_cycle/astra_execute
    # back to the inner model. Built-in tools are hard-disabled above, while this flag
    # also prevents inherited MCP configuration and its startup overhead.
    # This is the root cause behind "astra_cycle a veces se cuelga": isolate the child
    # process from the user's MCP config entirely. Measured impact on a trivial call:
    # 23073 cache-creation tokens / $0.26 / 5.5s -> 3050 tokens / $0.065 / 3.0s.
    isolate = ["--strict-mcp-config"]
    argv = [_claude_bin(), "-p", "--output-format", "json", *tools, *isolate]
    if model:
        argv += ["--model", model]
    # stdin_file: _invoke_once conecta el promptfile directo al stdin del exe
    # (bytes crudos utf-8 del disco, sin shell intermedia que los corrompa).
    return {"argv": argv, "stdin_file": promptfile}


# Windows PowerShell 5.1 pipes to native executables using $OutputEncoding,
# which defaults to us-ascii, and Get-Content without -Encoding reads a BOM-less
# file as ANSI. Both destroy every non-ASCII character on the way to the CLI:
# measured 2026-08-12 in the ASTRA 2.0 line, one `∀` reached Codex as `???`
# (one `?` per UTF-8 byte), which made the reviewer reject an otherwise sound
# Lean validator, and Spanish accents in the consensus conjectures degraded the
# same way. Declaring UTF-8 before the pipe restores fidelity; the leading BOM
# PowerShell emits is pre-existing and harmless. The POSIX route feeds the file
# to stdin directly and was never affected.
_PS_UTF8_PREAMBLE = (
    "$OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
    "[Console]::OutputEncoding = $OutputEncoding; "
)


def _ps_codex(promptfile: str, model: str | None, out: str, ws: str) -> str:
    m = f" -m {model}" if model else ""
    # Reasoning effort = la palanca de INTELIGENCIA de los modelos GPT de razonamiento
    # (low/medium/high). OJO: --ignore-user-config DESCARTA el model_reasoning_effort del
    # config.toml del usuario, asi que aqui se FUERZA por -c (los overrides -c si se
    # aplican sobre esa base). Quoting: PS 5.1 se come las comillas al pasar args a un
    # exe nativo, dejando TOML invalido ('high' a secas); por eso se envuelve en comillas
    # SIMPLES de PowerShell y se escapan las dobles con backslash -> codex recibe
    # model_reasoning_effort="high" (validado con un impresor de argv). Poner
    # ASTRA_CODEX_REASONING='' respeta el default interno de codex (no pasa -c).
    effort = (os.environ.get("ASTRA_CODEX_REASONING", "high") or "").strip().strip("'\"")
    r = f" -c 'model_reasoning_effort=\\\"{effort}\\\"'" if effort else ""
    # 2026-08-09: el server MCP puede arrancar con un PATH sin el dir de codex
    # (instalador nativo en AppData\Local\Programs\OpenAI\Codex\bin) -> el pipeline
    # moria con CommandNotFound en la fase reviewer. Se honra ASTRA_CODEX_BIN
    # tambien en Windows (como ya hacia la rama POSIX) con el call operator `&`.
    cbin = (
        (os.environ.get("ASTRA_CODEX_BIN") or "").strip().strip("'\"")
        or shutil.which("codex")
        or "codex"
    )
    return (f'{_PS_UTF8_PREAMBLE}'
            f'Get-Content -Raw -Encoding UTF8 -LiteralPath "{promptfile}" | '
            f'& "{cbin}" exec --dangerously-bypass-approvals-and-sandbox --ignore-user-config '
            f'--skip-git-repo-check{m}{r} -C "{ws}" -o "{out}" -')


def _codex_builder(
    promptfile: str,
    model: str | None,
    out: str,
    ws: str,
) -> str | dict:
    """Build the Codex invocation without requiring PowerShell on POSIX.

    Windows keeps the production-tested PowerShell pipeline. macOS/Linux pass
    the prompt file directly to the native CLI stdin, which also preserves EOF
    and avoids shell quoting differences.
    """
    if os.name == "nt":
        return _ps_codex(promptfile, model, out, ws)

    cbin = (
        (os.environ.get("ASTRA_CODEX_BIN") or "").strip().strip("'\"")
        or shutil.which("codex")
        or "codex"
    )
    argv = [
        cbin,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--ignore-user-config",
        "--skip-git-repo-check",
    ]
    if model:
        argv += ["-m", model]
    effort = (
        os.environ.get("ASTRA_CODEX_REASONING", "high") or ""
    ).strip().strip("'\"")
    if effort:
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    argv += ["-C", ws, "-o", out, "-"]
    return {"argv": argv, "stdin_file": promptfile}


def _ps_gemini(promptfile: str, model: str | None, _out: str, _ws: str) -> str:
    m = f" -m {model}" if model else ""
    # 2026-06-18: Google DESCONTINUO el gemini CLI para cuentas individuales
    # (IneligibleTierError; free/AI Pro/Ultra) y lo reemplazo por el Antigravity
    # CLI (`agy`), anunciado como fork compatible. ASTRA_GEMINI_BIN permite
    # apuntar a `agy` (u otro binario compatible) sin tocar codigo cuando este
    # instalado. OJO: el paquete npm sin scope `antigravity-cli` NO es de Google
    # (typosquat probable) — instalar agy solo desde canales oficiales.
    gbin = (os.environ.get("ASTRA_GEMINI_BIN") or "gemini").strip().strip("'\"") or "gemini"
    # stdin + `-p .`: modo headless con el prompt entero por stdin (sin limite de
    # argv). OJO: NO usar -p "" — PowerShell pierde el argumento vacio al pasar por
    # el shim .ps1 de npm, -p se traga el "-o" siguiente y yargs vomita el help
    # (bug real observado). El punto es un sufijo inocuo apendido al prompt.
    # --approval-mode plan = SOLO LECTURA nativo: el CLI no puede escribir archivos
    # ni ejecutar nada, asi que siempre responde texto (la leccion del bug de claude
    # que escribia el script a disco, resuelta aqui por diseno del propio CLI).
    return (f'{_PS_UTF8_PREAMBLE}'
            f'Get-Content -Raw -Encoding UTF8 -LiteralPath "{promptfile}" | '
            f'{gbin} -p . -o json --approval-mode plan{m}')


def _agy_argv(promptfile: str, model: str | None, _out: str, _ws: str) -> list:
    # agy = Antigravity CLI (Google). SUSTITUYE al `gemini` CLI que Google descontinuo
    # para cuentas individuales (IneligibleTierError, 2026-06-18). Interfaz DISTINTA a
    # gemini: NO tiene `-o json` ni `--approval-mode`; el prompt es POSICIONAL de --print
    # y la salida es TEXTO PLANO.
    #
    # A DIFERENCIA de claude/gemini (shims .ps1) y codex, agy es un .EXE NATIVO -> se
    # ejecuta DIRECTO (este builder devuelve un argv LISTA, no un string de PowerShell).
    # Motivo: PowerShell 5.1 corrompe comillas y saltos de linea al pasar texto como
    # argumento de un exe nativo; Python cita el argv correctamente via CreateProcess.
    # Contrapartida: techo practico ~32KB (limite de linea de comandos de Windows), pero
    # los prompts POR FASE de ASTRA quedan holgadamente por debajo.
    #
    # --mode plan = SOLO LECTURA (no escribe archivos ni ejecuta): garantiza que la fase
    # responda TEXTO, la misma leccion que el --tools "" de Claude (que si no,
    # escribia el script a disco y devolvia prosa). El prompt debe ser una instruccion
    # directa (generar/traducir/analizar), no "explora mi repo".
    with open(promptfile, encoding="utf-8") as f:
        prompt = f.read()
    abin = (os.environ.get("ASTRA_AGY_BIN") or "").strip().strip("'\"") \
        or shutil.which("agy") or "agy"
    # Antigravity exposes an explicit reasoning-effort control in addition to
    # the model name.  Production defaults to the highest supported level so
    # `gemini-3.1-pro-high` is not accidentally invoked with a weaker session
    # effort.  Keep the accepted set closed: a typo must not become an opaque
    # CLI failure several minutes into a cycle.
    effort = (
        os.environ.get("ASTRA_AGY_EFFORT", "high")
        .strip()
        .strip("'\"")
        .lower()
    )
    if effort not in {"low", "medium", "high"}:
        effort = "high"
    argv = [
        abin,
        "--print",
        prompt,
        "--mode",
        "plan",
        "--effort",
        effort,
    ]
    if model:
        argv += ["--model", model]
    return argv


def _wsl_path(path: str) -> str:
    """Map a local Windows path into its standard WSL mount without a shell."""
    if os.name != "nt":
        return path
    parsed = PureWindowsPath(path)
    drive = parsed.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"Muse WSL bridge needs an absolute Windows path: {path}")
    return "/mnt/" + drive + "/" + "/".join(parsed.parts[1:])


def _muse_argv(promptfile: str, model: str | None, _out: str, _ws: str) -> list:
    """Run Meta's Muse Code headlessly, with all ASTRA turns text-only.

    ASTRA runs natively on Windows while Muse is installed in Debian/WSL.  The
    prompt stays in a temporary file, so neither Windows nor WSL command-line
    limits can truncate a scientific phase.  Muse receives no write, shell, or
    web capability; every permitted input is already embedded in the prompt.

    Three further guards, each measured on 2026-09-04 with `--provider echo`:

    * ``--workspace`` is pinned to the per-call prompt directory.  Without it
      Muse roots its policy-gated *read* tools at the process cwd, which for a
      cycle is the whole ASTRA checkout (stderr: "workspace root:
      /mnt/c/Users/Nelson/Dev/ASTRA (cwd default)").  With
      ``--max-model-steps 1`` a single file read would end the run with an
      empty reply, and the readable tree includes ``.env``.  The prompt
      directory holds nothing but the prompt.
    * ``--no-session-log --no-foreign-personal-context --approval-judge off``:
      a headless scientific turn has no session to resume, no personal rules
      to load and no tool call for a judge to review.  Dropping them took the
      bridge overhead from ~2.2 s to ~1.1 s per call and stops every ASTRA
      turn from persisting a session tree under ``~/.local/share/muse``.
    * ``MUSE_NO_AUTO_UPDATE=1``: the launcher otherwise checks for and installs
      a new CLI build every hour, so a 30-day trial pinned to one model id
      would still drift across CLI versions.  The launcher honours this
      variable explicitly.
    """
    effort = (os.environ.get("ASTRA_MUSE_REASONING", "high") or "high").strip().lower()
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "ultra"}:
        effort = "high"
    args = ["--reasoning-effort", effort]
    if model:
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", model):
            raise ValueError("Muse model id contains unsupported characters")
        args += ["--model", model]
    # call_cli always hands over an absolute prompt path (mkdtemp-based), so
    # the workspace is simply its directory; on Windows _wsl_path rejects a
    # relative one anyway.
    workspace = os.path.dirname(promptfile)
    if os.name != "nt":
        return [
            "env", "MUSE_NO_AUTO_UPDATE=1",
            (os.environ.get("ASTRA_MUSE_BIN") or "muse").strip() or "muse",
            "exec", "--prompt-file", promptfile, "--workspace", workspace,
            "--no-session-log", "--no-foreign-personal-context",
            "--approval-judge", "off",
            "--disable-write", "--disable-shell", "--disable-web-tools",
            "--approval-mode", "never", "--max-model-steps", "1", *args,
        ]

    distro = (os.environ.get("ASTRA_MUSE_WSL_DISTRO") or "Debian").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", distro):
        raise ValueError("ASTRA_MUSE_WSL_DISTRO contains unsupported characters")
    # wsl.exe does not reliably preserve positional arguments after `bash -c`
    # on this Windows build. The generated path/model values are validated or
    # locally derived, then shell-quoted before becoming part of the script.
    quoted_args = " ".join(shlex.quote(item) for item in args)
    script = (
        'export MUSE_NO_AUTO_UPDATE=1; export PATH="$HOME/.local/bin:$PATH"; '
        f'exec muse exec --prompt-file {shlex.quote(_wsl_path(promptfile))} '
        f'--workspace {shlex.quote(_wsl_path(workspace))} '
        '--no-session-log --no-foreign-personal-context --approval-judge off '
        '--disable-write --disable-shell --disable-web-tools '
        f'--approval-mode never --max-model-steps 1 {quoted_args}'
    )
    return ["wsl.exe", "-d", distro, "--", "bash", "-lc", script]


_BUILDERS = {"claude": _claude_argv, "codex": _codex_builder, "gemini": _ps_gemini,
             "agy": _agy_argv, "muse": _muse_argv}


def _parse_claude(stdout: str, _outfile: str) -> tuple[str, float]:
    s = (stdout or "").strip()
    if not s:
        raise RuntimeError("claude devolvio salida vacia (posible tope de cuota o auth)")
    # Robusto: prueba la ultima linea, luego todo el texto, luego el 1er objeto {...}
    data = None
    for cand in (s.splitlines()[-1], s):
        try:
            data = json.loads(cand)
            break
        except Exception:
            data = None
    if data is None:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise RuntimeError(f"claude: JSON no parseable: {s[:200]}")
        data = json.loads(m.group(0))
    if data.get("is_error"):
        raise RuntimeError(data.get("result", "claude is_error=true"))
    return data.get("result", ""), float(data.get("total_cost_usd", 0.0) or 0.0)


def _parse_codex(_stdout: str, outfile: str) -> tuple[str, float]:
    with open(outfile, encoding="utf-8", errors="replace") as f:
        return f.read().strip(), 0.0


def _parse_gemini(stdout: str, _outfile: str) -> tuple[str, float]:
    s = (stdout or "").strip()
    if not s:
        raise RuntimeError("gemini devolvio salida vacia "
                           "(¿sin login OAuth? correr `gemini` una vez y usar /auth)")
    # -o json => objeto con "response"; fallback robusto a texto plano.
    data = None
    try:
        data = json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if isinstance(data, dict):
        resp = data.get("response")
        if isinstance(resp, str) and resp.strip():
            return resp.strip(), 0.0
        if data.get("error"):
            raise RuntimeError(str(data.get("error"))[:400])
    return s, 0.0


def _parse_agy(stdout: str, _outfile: str) -> tuple[str, float]:
    s = (stdout or "").strip()
    if not s:
        raise RuntimeError("agy devolvio salida vacia "
                           "(posible tope de cuota o sin login OAuth de Antigravity)")
    # agy en headless AUTO-DENIEGA los permisos de herramientas y, cuando el modelo
    # intenta usar una (p.ej. read_file), imprime un META-MENSAJE tipo "... no output
    # produced ... headless mode cannot prompt ..." CON exit 0. Eso NO es una respuesta:
    # si lo dejaramos pasar, envenenaria la fase (texto no vacio + exit 0 = "valido").
    # Se trata como error para que la escalera de cuota / el retry del ciclo reaccione.
    low = s.lower()
    if ("no output produced" in low and "headless" in low) \
            or "dangerously-skip-permissions" in low:
        raise RuntimeError("agy aborto por permiso de herramienta en modo headless "
                           "(el modelo intento leer/escribir en vez de responder texto): "
                           f"{s[:200]}")
    return s, 0.0


def _parse_muse(stdout: str, _outfile: str) -> tuple[str, float]:
    s = (stdout or "").strip()
    if not s:
        raise RuntimeError("muse devolvio salida vacia (posible login, cuota o facturacion)")
    return s, 0.0


_PARSERS = {"claude": _parse_claude, "codex": _parse_codex, "gemini": _parse_gemini,
            "agy": _parse_agy, "muse": _parse_muse}


# --- Escalera de fallback por cuota -------------------------------------------
# ASTRA_CLAUDE_MODELS / ASTRA_CODEX_MODELS (.env): modelos a intentar EN ORDEN
# cuando el llamador no fuerza uno. Token 'default' (o vacio) = sin --model,
# es decir el modelo por defecto configurado en el CLI (hoy claude -> Opus 4.8).
# Solo se avanza al siguiente peldano si el error PARECE de cuota/limite; un
# error real (parseo, crash) corta la escalera: reintentar con otro modelo no
# arregla un bug y si quema cuota. Los peldanos agotados fallan en segundos
# (el CLI rechaza sin correr el modelo), asi que el fallback casi no anade
# latencia ni consume ventana de uso.

# "hit your weekly limit" es la redaccion ACTUAL de Claude Code y no encajaba
# en "reached your ... limit" ni en "usage limit": la escalera rompia en el
# primer peldano creyendo que era un error real, sin llegar a probar el
# siguiente modelo ni emitir el diagnostico de cuota agotada.
#
# Meta's Muse Code words an exhausted or unpaid account differently again:
# "Muse Code requires a payment method" (observed 2026-09-03 during login),
# and the Model API side reports billing / insufficient credits. None of those
# matched, so a Muse account running dry would have read as a real bug rather
# than as quota, and the ensemble would have lost the classification that
# tells a caller which proposer to top up.
_QUOTA_PAT = re.compile(
    r"((?:reached|hit) your .{0,40}?limit|limit reached|weekly limit|"
    r"usage limit|plan limit|usage-credits|rate.?limit|quota|"
    r"too many requests|overloaded|credit balance|resource.?exhausted|"
    r"\b429\b|tope de cuota|"
    r"requires? a payment method|payment method (?:is )?required|"
    r"\bbilling\b|insufficient credits?)",
    re.IGNORECASE)


def _is_quota_error(msg: str) -> bool:
    return bool(_QUOTA_PAT.search(msg or ""))


def _semantic_error_from_stdout(stdout: str):
    """claude reporta errores SEMANTICOS (limite de cuota, auth) saliendo con
    exit!=0 pero dejando JSON valido en stdout: is_error=true y el mensaje en
    "result". Sin este rescate, la escalera veria solo "exit 1: <cola de stats
    de tokens>" y no podria clasificar el fallo como cuota (bug real observado
    con --model claude-fable-5 agotado). Devuelve el mensaje o None."""
    s = (stdout or "").strip()
    if not s:
        return None
    data = None
    for cand in (s.splitlines()[-1], s):
        try:
            data = json.loads(cand)
            break
        except Exception:
            data = None
    if data is None:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
    if isinstance(data, dict) and data.get("is_error"):
        return str(data.get("result") or "is_error=true sin mensaje")
    return None


def _model_ladder(kind: str, model: str | None, override: str | None = None) -> list:
    """Resuelve la lista de modelos a intentar. None dentro de la lista
    significa 'sin --model' (default del CLI). `override` permite una escalera
    POR FASE (ASTRA_TRANSLATOR_MODELS, etc.) que gana sobre la global del CLI."""
    if model:
        return [model]          # el llamador forzo un modelo -> sin escalera
    raw = (override or os.environ.get(f"ASTRA_{kind.upper()}_MODELS") or "").strip().strip("'\"")
    if not raw:
        return [None]           # sin config -> comportamiento clasico (1 intento)
    ladder = []
    for tok in raw.split(","):
        tok = tok.strip().strip("'\"")
        ladder.append(None if tok.lower() in ("", "default") else tok)
    return ladder or [None]


def _kill_tree(pid: int) -> None:
    """Mata el ARBOL de procesos completo (PowerShell -> claude.cmd -> node).
    Matar solo al padre (lo que hace subprocess con timeout) deja al NIETO vivo
    sosteniendo el pipe de stdout: el drenaje post-kill bloquea hasta que el
    nieto muera solo — bug REAL medido en produccion: fases de 956s y 893s con
    timeout=600, mas un claude -p huerfano quemando cuota por cada timeout."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15,
                           creationflags=_NT_NO_WINDOW)
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def _dump_failure(kind: str, cmd, model, proc, reason: str = "") -> None:
    """Autopsia de un fallo de CLI: escribe comando + stdout/stderr COMPLETOS
    en workspace/cli_failures/ (el error del CliResult solo lleva 400 chars).
    ``reason`` distingue el fallo (p.ej. un timeout) del exit!=0 corriente, para
    que la rama de timeout deje rastro en vez de tirar la salida parcial.
    Nunca puede tumbar la llamada: cualquier problema aqui se ignora."""
    try:
        import json as _json
        import time as _time
        d = os.path.join(_PROJECT_ROOT, "workspace", "cli_failures")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, _time.strftime(f"%Y%m%d_%H%M%S_{kind}.json"))
        with open(path, "w", encoding="utf-8") as f:
            _json.dump({
                "kind": kind,
                "model": model,
                "reason": reason,
                "returncode": proc.returncode,
                "cmd": cmd if isinstance(cmd, list) else [cmd],
                "stdout": (proc.stdout or "")[-20000:],
                "stderr": (proc.stderr or "")[-20000:],
            }, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _writable_probe(root: str) -> str | None:
    """Confirma que de verdad se puede CREAR un subdirectorio bajo ``root``
    antes de entregarselo a tempfile.mkdtemp.

    En Windows os.access(W_OK) decide solo con la DACL y NUNCA consulta el token
    de acceso restringido, asi que bajo el sandbox de Codex (cuyos SID
    restrictivos no estan en el ACL de cli_tmp) os.mkdir lanza WinError 5
    mientras os.access sigue diciendo True. tempfile.mkdtemp se fia de os.access
    y reintenta hasta os.TMP_MAX veces (2**31-1 en CPython 3.12): un cuelgue sin
    fin, no un error, de modo que el timeout de call_cli -- que solo envuelve
    communicate() -- jamas se dispara. Un unico mkdir real convierte ese cuelgue
    en un fallo inmediato y explicito (reproducido 2026-09-10, 3,7 dias para
    agotar el tope). Devuelve el mensaje de error o None si se puede escribir."""
    probe = os.path.join(root, f".astra_probe_{uuid.uuid4().hex}")
    try:
        os.mkdir(probe)
    except OSError as exc:
        return (
            "No se pudo crear un subdirectorio temporal en "
            f"{root}: {type(exc).__name__}: {exc}. "
            "Suele ser un contexto de permisos restringido (p.ej. el sandbox de "
            "Codex, cuyo token restringido no cubre este arbol): invoca ASTRA "
            "por su servidor MCP en vez de correr astra_tool.py DENTRO del "
            "sandbox, o apunta ASTRA_CLI_TEMP_ROOT a un directorio escribible."
        )
    try:
        os.rmdir(probe)
    except OSError:
        pass
    return None


def _cli_temp_root(workspace: str) -> str:
    """Return an ASTRA-owned temporary directory for subscription CLI turns.

    Windows service/MCP hosts can inherit a ``TEMP`` or ``TMP`` directory that
    is readable but not writable by the child identity.  Calling
    ``tempfile.mkdtemp()`` without ``dir=`` then raises WinError 5 before a
    deliberative review ever reaches its model.  Keep prompt and output files
    below the selected ASTRA workspace instead.  This path is also mounted in
    Debian/WSL, so the Muse bridge can consume the same prompt file.
    """
    configured = (os.environ.get("ASTRA_CLI_TEMP_ROOT") or "").strip().strip("'\"")
    root = configured or os.path.join(workspace, "cli_tmp")
    os.makedirs(root, exist_ok=True)
    return root


def _invoke_once(kind: str, promptfile: str, outfile: str, model: str | None,
                 ws: str, env: dict, timeout: int) -> CliResult:
    """Un intento contra un CLI con un modelo concreto (o el default)."""
    built = _BUILDERS[kind](promptfile, model, outfile, ws)
    # Formatos de builder:
    #  - dict {"argv": [...], "stdin_file": ruta}: exe nativo DIRECTO con el prompt
    #    conectado a stdin (claude: prompts >32KB no caben en argv y PowerShell
    #    sin consola pierde el stdout de hijos nativos -> nada de shells).
    #  - list: argv de exe nativo directo, sin stdin (agy: prompt como argumento).
    #  - str: comando PowerShell (Windows codex and legacy gemini).
    stdin_handle = subprocess.DEVNULL
    stdin_file = None
    if isinstance(built, dict):
        cmd = built["argv"]
        stdin_file = built.get("stdin_file")
    elif isinstance(built, list):
        cmd = built
    else:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", built]
    try:
        if stdin_file:
            stdin_handle = open(stdin_file, "rb")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=stdin_handle, text=True, encoding="utf-8",
            errors="replace", env=env,
            start_new_session=os.name != "nt",
            creationflags=_NT_NO_WINDOW,
        )
    except OSError as e:
        return CliResult(False, error=f"lanzamiento fallo: {e}")
    finally:
        # Popen ya duplico el handle en el hijo (o fallo): el nuestro sobra.
        if stdin_handle is not subprocess.DEVNULL:
            try:
                stdin_handle.close()
            except Exception:
                pass
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        partial_out, partial_err = "", ""
        try:
            partial_out, partial_err = proc.communicate(timeout=15)
        except Exception:
            pass

        class _PT:                 # adaptador para la autopsia del timeout
            returncode = proc.returncode if proc.returncode is not None else 124
            stdout = partial_out or ""
            stderr = partial_err or ""

        # Antes esta rama tiraba la salida parcial (el fallo del revisor de las
        # 12:23 del 2026-09-10 no dejo rastro). Ahora la conserva: autopsia
        # integra a cli_failures/ + una cola en el propio error.
        _dump_failure(kind, cmd, model, _PT, reason=f"timeout tras {timeout}s")
        tail = (_PT.stderr or _PT.stdout or "")[-400:]
        msg = f"timeout tras {timeout}s (arbol de procesos matado)"
        if tail.strip():
            msg += f"; salida parcial: {tail.strip()}"
        return CliResult(False, error=msg)

    class _P:                      # adaptador minimo para el resto del flujo
        returncode = proc.returncode
        stdout = out
        stderr = err
    proc = _P()

    if proc.returncode != 0:
        sem = _semantic_error_from_stdout(proc.stdout)
        if sem:
            return CliResult(False, error=sem)
        tail = (proc.stderr or proc.stdout or "")[-400:]
        # El tail de 400 chars ha resultado dos veces insuficiente para
        # diagnosticar fallos de lanzamiento (el error de PowerShell "char:222"
        # de codex llego truncado y sin CategoryInfo). Autopsia completa a
        # disco: comando construido + stdout/stderr integros.
        _dump_failure(kind, cmd, model, proc)
        return CliResult(False, error=f"exit {proc.returncode}: {tail.strip()}")

    try:
        text, cost = _PARSERS[kind](proc.stdout, outfile)
    except RuntimeError as e:
        # Error SEMANTICO del CLI (is_error=true, p.ej. limite de cuota): el
        # mensaje va verbatim para que _is_quota_error lo pueda clasificar.
        return CliResult(False, error=str(e))
    except Exception as e:
        return CliResult(False, error=f"parseo fallo: {type(e).__name__}: {e}")

    if not text.strip():
        # respuesta vacia suele indicar tope de cuota; la reportamos como error
        tail = (proc.stdout or "")[-300:]
        return CliResult(False, error=f"respuesta vacia (posible tope de cuota). {tail.strip()}")

    return CliResult(True, text=text, cost_usd=cost)


def call_cli(kind: str, prompt: str, timeout: int | None = None,
             model: str | None = None, workspace: str | None = None,
             env_extra: dict | None = None, models: str | None = None) -> CliResult:
    """
    Invoca un CLI de suscripcion en modo headless y devuelve su texto.
    kind: "claude" | "codex" | "gemini".

    Si el llamador no fuerza `model`, recorre una escalera ante errores de
    cuota: `models` (escalera por fase, string 'a,b,...') si viene, si no
    ASTRA_<KIND>_MODELS del .env. Si respondio un peldano que no es el primero,
    CliResult.warning lo AVISA y model_used dice quien respondio.
    """
    if kind not in _BUILDERS:
        return CliResult(False, error=f"kind CLI desconocido: {kind}")

    if timeout is None:
        # Presupuesto POR LLAMADA, deliberadamente menor que el presupuesto del
        # ciclo (800s en el MCP): si una fase se cuelga, muere ELLA sola y el
        # ciclo devuelve API_ERROR nombrando la fase — en vez del defecto
        # historico donde el timeout EXTERNO mataba el proceso entero sin
        # diagnostico. Peor caso sin retries: 240+240+180+~20 < 800.
        try:
            timeout = int(str(os.environ.get("ASTRA_CLI_TIMEOUT", "240")).strip().strip("'\""))
        except ValueError:
            timeout = 240

    ws = workspace or _DEFAULT_WS
    os.makedirs(ws, exist_ok=True)

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    if os.name == "nt":
        # Algunos hosts MCP lanzan el server con un entorno sin PATHEXT y los
        # hijos lo heredan. PowerShell es el UNICO consumidor: sin PATHEXT
        # clasifica codex.exe como "documento" y `... | & exe` muere con
        # CantActivateDocumentInPipeline (reproducido byte a byte 2026-08-20;
        # mato la fase codex de TODOS los ciclos lanzados desde ese host,
        # mientras claude/agy/ssh — CreateProcess directo — ni lo miran).
        env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.JS;.WSH;.MSC")
    account_profile = ""
    if kind in ("codex", "claude", "agy"):
        try:
            from core.account_profiles import profile_environment
            account_profile, profile_env = profile_environment(kind)
            env.update(profile_env)
        except Exception as exc:
            return CliResult(
                False,
                error=f"perfil de cuenta {kind} invalido: {exc}",
                account_profile=account_profile,
            )
    if kind in ("gemini", "agy"):
        # gemini_cli / agy = OAuth de suscripcion (Code Assist / Antigravity), cuota de
        # la cuenta Google, NO API de pago. Sin esto el CLI ve la GEMINI_API_KEY del .env
        # de ASTRA y podria cambiar solito a autenticacion por API key (otra
        # facturacion/limites). La variante API ya existe como provider 'gemini' en
        # llm_client: se mantienen separadas.
        env.pop("GEMINI_API_KEY", None)
        env.pop("GOOGLE_API_KEY", None)
    for k, v in (env_extra or {}).items():
        env[k] = str(v)

    # Un contexto de permisos restringido (sandbox) da os.mkdir denegado pero
    # os.access(W_OK) True: mkdtemp entra en un bucle de os.TMP_MAX intentos. El
    # probe lo corta antes de llegar a mkdtemp; ademas garantiza que el mkdtemp
    # de abajo acierte a la primera. Ver _writable_probe.
    try:
        temp_root = _cli_temp_root(ws)
    except OSError as exc:
        return CliResult(
            False,
            error=(
                "No se pudo preparar el directorio temporal de la fase CLI en el "
                f"espacio de trabajo de ASTRA: {type(exc).__name__}: {exc}"
            ),
            account_profile=account_profile,
        )
    probe_error = _writable_probe(temp_root)
    if probe_error:
        return CliResult(False, error=probe_error, account_profile=account_profile)

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="astra_cli_", dir=temp_root)
        promptfile = os.path.join(tmpdir, "prompt.txt")
        outfile = os.path.join(tmpdir, "codex_out.txt")
        with open(promptfile, "w", encoding="utf-8") as f:
            f.write(prompt)
    except OSError as exc:
        # mkdtemp may have already created the dir before the write failed
        # (disco lleno, lock del antivirus): no lo dejes atras -- es justo la
        # acumulacion que este cambio corrige.
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return CliResult(
            False,
            error=(
                "No se pudo crear el temporal de la fase CLI en el espacio de "
                f"trabajo de ASTRA: {type(exc).__name__}: {exc}"
            ),
            account_profile=account_profile,
        )

    # Higiene: cada turno crea un astra_cli_* y hasta ahora ninguno se borraba
    # (494 acumulados desde 2026-09-03). Se limpia en TODA salida -- exito o
    # fallo -- porque el prompt ya esta en memoria y la autopsia de un fallo va
    # aparte, a workspace/cli_failures/. ASTRA_CLI_KEEP_TEMP=1 lo conserva para
    # depurar. El borrado ocurre despues de que _invoke_once haya parseado el
    # outfile y de que Muse haya leido el promptfile durante la llamada.
    keep_temp = str(os.environ.get("ASTRA_CLI_KEEP_TEMP", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }
    try:
        ladder = _model_ladder(kind, model, models)
        fallidos = []   # [(etiqueta, error), ...] peldanos que no respondieron
        for mdl in ladder:
            res = _invoke_once(kind, promptfile, outfile, mdl, ws, env, timeout)
            res.account_profile = account_profile
            label = mdl or "default"
            if res.ok:
                res.model_used = label
                if fallidos:
                    caidos = "; ".join(f"'{l}' -> {e[:140]}" for l, e in fallidos)
                    res.warning = (f"AVISO CUOTA [{kind}]: {caidos}. "
                                   f"La fase la respondio el fallback '{label}'.")
                return res
            fallidos.append((label, res.error))
            if not _is_quota_error(res.error):
                break   # error real (no cuota): seguir bajando no ayuda

        detalle = "; ".join(f"'{l}': {e[:180]}" for l, e in fallidos)
        if len(fallidos) > 1 and all(_is_quota_error(e) for _, e in fallidos):
            return CliResult(False, error=(
                f"CUOTA AGOTADA en toda la escalera de {kind} "
                f"({', '.join(l for l, _ in fallidos)}): hay que ESPERAR la "
                f"ventana de uso o ampliar ASTRA_{kind.upper()}_MODELS / cambiar "
                f"de cuenta. Detalle: {detalle}"), account_profile=account_profile)
        return CliResult(False, error=detalle, account_profile=account_profile)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    k = sys.argv[1] if len(sys.argv) > 1 else "claude"
    p = sys.argv[2] if len(sys.argv) > 2 else "Responde solo: LISTO"
    r = call_cli(k, p, timeout=120)
    print(f"ok={r.ok} model={r.model_used} cost=${r.cost_usd:.4f} err={r.error}")
    if r.warning:
        print(f"WARNING: {r.warning}")
    print(r.text[:1000])
