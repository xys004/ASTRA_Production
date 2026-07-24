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
import shutil
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
    model_used: str = ""      # modelo que respondio ('default' = el configurado del CLI)
    warning: str = ""         # aviso cuando la respuesta vino de un modelo fallback


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
    # Claude Code is AGENTIC: without restricting tools it WRITES the script to a file
    # (Write/Edit) and returns a PROSE summary (star insights, tables) instead of code
    # -> downstream SyntaxError. Deny mutating/exec tools so every text-only ASTRA phase
    # (conjecture/code/analysis) returns its answer on stdout.
    # ("MultiEdit" removed: current claude CLI no longer has that tool name and prints
    # a "matches no known tool" warning on every single call.)
    deny = ["--disallowed-tools", "Write,Edit,NotebookEdit,Bash"]
    # Without this, every claude -p call here loads the user's GLOBAL MCP config:
    # Gmail/Calendar/Drive, two npx filesystem servers that fail to connect (each a
    # potential multi-second-to-hung npx registry fetch), and -- critically -- a second,
    # RECURSIVE copy of this very astra MCP server, exposing astra_cycle/astra_execute
    # back to the inner model (nothing in the disallowed-tools list above blocks MCP
    # tools, and the conjecture/translator/analyst prompts never say "don't use tools").
    # This is the root cause behind "astra_cycle a veces se cuelga": isolate the child
    # process from the user's MCP config entirely. Measured impact on a trivial call:
    # 23073 cache-creation tokens / $0.26 / 5.5s -> 3050 tokens / $0.065 / 3.0s.
    isolate = ["--strict-mcp-config"]
    argv = [_claude_bin(), "-p", "--output-format", "json", *deny, *isolate]
    if model:
        argv += ["--model", model]
    # stdin_file: _invoke_once conecta el promptfile directo al stdin del exe
    # (bytes crudos utf-8 del disco, sin shell intermedia que los corrompa).
    return {"argv": argv, "stdin_file": promptfile}


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
    return (f'Get-Content -Raw -LiteralPath "{promptfile}" | '
            f'codex exec --dangerously-bypass-approvals-and-sandbox --ignore-user-config '
            f'--skip-git-repo-check{m}{r} -C "{ws}" -o "{out}" -')


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
    return (f'Get-Content -Raw -LiteralPath "{promptfile}" | '
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
    # responda TEXTO, la misma leccion que el --disallowed-tools de claude (que si no,
    # escribia el script a disco y devolvia prosa). El prompt debe ser una instruccion
    # directa (generar/traducir/analizar), no "explora mi repo".
    with open(promptfile, encoding="utf-8") as f:
        prompt = f.read()
    abin = (os.environ.get("ASTRA_AGY_BIN") or "").strip().strip("'\"") \
        or shutil.which("agy") or "agy"
    argv = [abin, "--print", prompt, "--mode", "plan"]
    if model:
        argv += ["--model", model]
    return argv


_BUILDERS = {"claude": _claude_argv, "codex": _ps_codex, "gemini": _ps_gemini,
             "agy": _agy_argv}


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


_PARSERS = {"claude": _parse_claude, "codex": _parse_codex, "gemini": _parse_gemini,
            "agy": _parse_agy}


# --- Escalera de fallback por cuota -------------------------------------------
# ASTRA_CLAUDE_MODELS / ASTRA_CODEX_MODELS (.env): modelos a intentar EN ORDEN
# cuando el llamador no fuerza uno. Token 'default' (o vacio) = sin --model,
# es decir el modelo por defecto configurado en el CLI (hoy claude -> Opus 4.8).
# Solo se avanza al siguiente peldano si el error PARECE de cuota/limite; un
# error real (parseo, crash) corta la escalera: reintentar con otro modelo no
# arregla un bug y si quema cuota. Los peldanos agotados fallan en segundos
# (el CLI rechaza sin correr el modelo), asi que el fallback casi no anade
# latencia ni consume ventana de uso.

_QUOTA_PAT = re.compile(
    r"(reached your .{0,40}?limit|usage limit|plan limit|usage-credits|"
    r"rate.?limit|quota|too many requests|overloaded|credit balance|"
    r"resource.?exhausted|\b429\b|tope de cuota)",
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
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=15)
    except Exception:
        pass


def _invoke_once(kind: str, promptfile: str, outfile: str, model: str | None,
                 ws: str, env: dict, timeout: int) -> CliResult:
    """Un intento contra un CLI con un modelo concreto (o el default)."""
    built = _BUILDERS[kind](promptfile, model, outfile, ws)
    # Formatos de builder:
    #  - dict {"argv": [...], "stdin_file": ruta}: exe nativo DIRECTO con el prompt
    #    conectado a stdin (claude: prompts >32KB no caben en argv y PowerShell
    #    sin consola pierde el stdout de hijos nativos -> nada de shells).
    #  - list: argv de exe nativo directo, sin stdin (agy: prompt como argumento).
    #  - str: comando PowerShell (codex/gemini, pendientes de migrar a argv).
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
        try:
            proc.communicate(timeout=15)
        except Exception:
            pass
        return CliResult(False, error=f"timeout tras {timeout}s (arbol de procesos matado)")

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

    tmpdir = tempfile.mkdtemp(prefix="astra_cli_")
    promptfile = os.path.join(tmpdir, "prompt.txt")
    outfile = os.path.join(tmpdir, "codex_out.txt")
    with open(promptfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    ladder = _model_ladder(kind, model, models)
    fallidos = []   # [(etiqueta, error), ...] peldanos que no respondieron
    for mdl in ladder:
        res = _invoke_once(kind, promptfile, outfile, mdl, ws, env, timeout)
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
            f"({', '.join(l for l, _ in fallidos)}): hay que ESPERAR la ventana "
            f"de uso o ampliar ASTRA_{kind.upper()}_MODELS / cambiar de cuenta. "
            f"Detalle: {detalle}"))
    return CliResult(False, error=detalle)


if __name__ == "__main__":
    import sys
    k = sys.argv[1] if len(sys.argv) > 1 else "claude"
    p = sys.argv[2] if len(sys.argv) > 2 else "Responde solo: LISTO"
    r = call_cli(k, p, timeout=120)
    print(f"ok={r.ok} model={r.model_used} cost=${r.cost_usd:.4f} err={r.error}")
    if r.warning:
        print(f"WARNING: {r.warning}")
    print(r.text[:1000])
