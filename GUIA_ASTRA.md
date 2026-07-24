# Guía de ASTRA — Uso e Instalación
### Backend de suscripción (Claude + Codex, sin API) · Oráculo ASTRUM · Acceso por MCP

> ASTRA convierte una intuición científica en un teorema **verificado o refutado** por
> cómputo real. Esta guía cubre la configuración que corre con tus **suscripciones**
> (no API de pago), verifica en **ASTRUM** (tu workstation con RTX 3080) o localmente,
> y es usable desde la **web** o desde **cualquier agente** (Claude Code, Codex, Gemini)
> vía **MCP**.

---

## 1. Mapa mental (cómo encaja todo)

```
   TÚ eliges cómo trabajar:
   ┌─────────────────────────┐        ┌──────────────────────────────┐
   │  A) GUI Web (navegador)  │        │  B) Cualquier agente vía MCP │
   │     http://127.0.0.1:5050│        │  (Claude Code / Codex / Gemini)│
   └───────────┬─────────────┘        └───────────────┬──────────────┘
               │                                        │  astra_execute / astra_cycle / astra_status
               ▼                                        ▼
        ┌───────────────────────── ASTRA core (venv 3.9) ─────────────────────────┐
        │  Conjetura → Traduce a código → EJECUTA → Analiza (VALIDATED/REFUTED)    │
        │  Modelos: Codex=conjetura · Claude=código/análisis  (tus suscripciones)  │
        └───────────────────────────────┬─────────────────────────────────────────┘
                                         ▼  Oráculo (elegible por corrida)
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                             ▼
          LOCAL (venv 3.9)                          ASTRUM  (remoto, por Tailscale)
          rápido / fallback                         Ryzen 9 + RTX 3080, stack completo
```

**Piezas clave y rutas** (todo bajo `C:\Users\Nelson\Dev\ASTRA\`):

| Pieza | Ruta | Qué es |
|-------|------|--------|
| Core | `venv\` (Python 3.9) | motor de ASTRA + verificadores |
| Backend suscripción | `core\cli_backend.py` | invoca Claude/Codex CLI headless |
| Oráculo local/remoto | `core\executor.py`, `core\remote_executor.py` | dónde corre el código |
| API por subprocess | `astra_tool.py` | puente para procesos externos (MCP) |
| Servidor MCP | `mcp_server\server.py` + `mcp_server\venv\` (Python 3.12) | expone ASTRA a los agentes |
| Web | `web\app.py`, `web\templates\index.html` | GUI |
| Config | `.env` | proveedores + oráculo + conexión ASTRUM |
| Lanzador | `launch_astra.bat` + acceso directo del escritorio | abre la web |

---

## 2. Requisitos (qué debe existir)

- **CLIs autenticados con suscripción** (NO API key):
  - `claude` (Claude Code) — Claude Pro/Max
  - `codex` (Codex CLI **≥ 0.144**) — ChatGPT (cuenta `astrumdrivetechnologies`, mayor cuota)
  - `gemini` (opcional)
- **Tailscale** activo (para llegar a ASTRUM).
- **Python 3.9** (core) y **Python 3.12** (servidor MCP).
- **ASTRUM** encendido y en la tailnet: `astrum@100.66.143.117`.

Verificación rápida de que todo está vivo:
```powershell
claude --version; codex --version; gemini --version
tailscale status | Select-String astrum
# ASTRUM alcanzable + GPU:
ssh -i "C:\Users\Nelson\.ssh\google_compute_engine" -o "ProxyCommand=tailscale nc %h %p" `
    astrum@100.66.143.117 "hostname; nvidia-smi -L"
```

---

## 3. Instalación desde cero (solo si hay que rehacerlo)

> Normalmente ya está todo instalado. Esta sección es para reconstruir.

### 3.1 Core (venv 3.9)
```powershell
cd C:\Users\Nelson\Dev\ASTRA
python3.9 -m venv venv
.\venv\Scripts\python -m pip install -r requirements.txt
# Fixes conocidos (el venv se corrompió una vez):
.\venv\Scripts\python -m pip install --force-reinstall "sympy>=1.12,<1.14"  # NO 1.14 (rota)
.\venv\Scripts\python -m pip install "qutip<5" "numpy==1.26.4"              # qutip 5 choca con scipy
.\venv\Scripts\python -m pip install pint fluids networkx
# Si pip mismo se rompe en 3.9:  irm https://bootstrap.pypa.io/pip/3.9/get-pip.py -OutFile gp.py ; .\venv\Scripts\python gp.py --force-reinstall
```
Chequeo de salud del venv: `.\venv\Scripts\python -c "import sympy,z3,qutip,einsteinpy,pint,fluids,networkx,flask; print('OK')"`

### 3.2 Servidor MCP (venv 3.12)
```powershell
python3.12 -m venv mcp_server\venv
.\mcp_server\venv\Scripts\python -m pip install mcp
```

### 3.3 Login de los CLIs (una vez, interactivo)
```powershell
claude            # /login con tu cuenta, luego /exit
codex login       # cuenta astrumdrivetechnologies (mayor cuota)
gemini            # /auth -> Login with Google (opcional)
```

### 3.4 ASTRUM (worker remoto)
Ya desplegado en `~/astra-worker/astra_remote_worker.py`. Si hay que redeployar:
```powershell
.\remote\deploy_worker.ps1
```

### 3.5 `.env` (ver §7 para las claves)

### 3.6 Registrar ASTRA como MCP en los agentes (ver §5.1)

### 3.7 Acceso directo
Ya creado en el escritorio ("ASTRA Production"). Apunta a `launch_astra.bat`.

---

## 4. Uso A — La GUI Web

**Abrir:** doble clic en **"ASTRA Production"** del escritorio (o `.\venv\Scripts\python web\app.py`).
Se abre el navegador en **http://127.0.0.1:5050**.

- **Single Cycle** — escribe una hipótesis (o sube un PDF/TXT) → *Launch Cycle*. Corre las 5 fases y da un reporte.
- **Research Loop** — una pregunta macro; ASTRA explora en profundidad, con pausas (milestones) para tu aprobación. Modo autónomo opcional.
- **Selectores** (arriba de cada panel):
  - **Proveedores por fase** — por defecto Codex (conjetura), Claude (traductor/analista).
  - **Oráculo** — **ASTRUM** (default), **Local**, o **Auto** (ver §6).
- **Reportes** en `workspace\reports\`; historial en *Investigations*.

> ⏱️ La primera respuesta de cada fase tarda **~30–100 s** (arranque en frío del CLI). Es normal.

---

## 5. Uso B — Desde cualquier agente (MCP)

Ya registrado en **Claude Code**, **Codex** y **Gemini**. En una sesión **nueva** del agente,
pídele en lenguaje natural que use las herramientas. El agente es tu **cerebro** (conjetura,
navega) y ASTRA su **verificador con GPU**.

### Herramientas expuestas

| Herramienta | Firma | Para qué |
|-------------|-------|----------|
| `astra_execute` | `(code, oracle="local", timeout=180)` | corre TU código y devuelve stdout + veredicto. `timeout` ahora se respeta de verdad (fix 2026-07-15: antes el env lo pisaba) |
| `astra_cycle` | `(intuition, oracle="local", timeout=1500, exec_timeout=0)` | pipeline completo. **Un ciclo de física pesada tarda 10-25 min y es NORMAL** (traducción medida: 350-700s) — sondear con `astra_probe`, no matar. Si el traductor agota su presupuesto, la respuesta incluye la `conjecture` ya pagada: tradúcela tú y usa `astra_execute` |
| `astra_probe` | `()` | **SONDA**: ¿qué hace ASTRA ahora? — fase en vuelo + heartbeat + ciclos recientes, leído de `workspace\progress\`. Gratis e instantánea; sondear cada ~60s antes de asumir cuelgue |
| `astra_submit` | `(code, oracle="local", max_seconds=86400)` | **JOB ASÍNCRONO** para cómputo >10 min: retorna `job_id` al instante y el trabajo corre desacoplado (sobrevive al cliente y sus reinicios). Local o ASTRUM (`astrum`: el runner sostiene el SSH — laptop despierta) |
| `astra_job` | `(job_id="")` | Sondea un job: status, heartbeat, **tail EN VIVO del stdout** (python local), y el resultado final (verdict/exit/duración). Sin `job_id`: lista los 10 recientes |
| `astra_status` | `()` | ¿ASTRUM está vivo? |

**Política de duraciones** (el traductor ya la estima con `# ASTRA_EST_RUNTIME: short|medium|long` y el ciclo la reporta en `est_runtime`):

| Clase | Duración | Vía |
|---|---|---|
| short | < 2-3 min | defaults (`astra_execute` / `astra_cycle` tal cual) |
| medium | 3-10 min | `astra_execute(timeout=N)` o `astra_cycle(exec_timeout=N)` explícitos |
| long | > 10 min (muro síncrono del cliente MCP ≈15 min) | **`astra_submit` + `astra_job`** — sin muros; para sweeps, cotiza con corrida piloto: 1 punto medido × N puntos |

**Devuelven JSON** con `stdout`, `exit_code`, `verdict` (PASS/FAIL/NONE), `oracle_used`, etc.
El script debe terminar imprimiendo `VERDICT: PASS` o `VERDICT: FAIL`.

### Ejemplos de lo que le dices al agente
- *"Con `astra_status`, confirma que ASTRUM está disponible."*
- *"Escribe un script sympy que verifique que el Ricci de Schwarzschild es 0 y córrelo con `astra_execute` en ASTRUM."*
- *"Usa `astra_cycle` para investigar si la métrica X viola la NEC."*

### 5.1 (Re)registrar el MCP
```powershell
$MPY = "C:\Users\Nelson\Dev\ASTRA\mcp_server\venv\Scripts\python.exe"
$SRV = "C:\Users\Nelson\Dev\ASTRA\mcp_server\server.py"

# Claude Code (global, todos tus proyectos):
claude mcp add astra -s user -- $MPY $SRV
# Codex:
codex mcp add astra -- $MPY $SRV
# Gemini (scope user):
gemini mcp add -s user astra $MPY $SRV

# Verificar / quitar:
claude mcp get astra   |   codex mcp get astra   |   gemini mcp list
claude mcp remove astra -s user  |  codex mcp remove astra  |  gemini mcp remove astra
```
> Tras registrar, **abre una sesión nueva** del agente para que cargue las tools.

---

## 6. Modos de oráculo (dónde corre la verificación)

Elegible por corrida (dropdown en la web, o parámetro `oracle` en las tools):

| Modo | Qué hace |
|------|----------|
| **`astrum`** | corre en tu workstation remota (RTX 3080, stack completo). Default de la GUI web |
| **`local`** (default de las tools MCP desde 2026-07-15) | corre en el venv 3.9 local — rápido, siempre disponible, **fallback si ASTRUM está caído** |
| **`auto`** | *deciden los modelos*: el traductor puede marcar `# ASTRA_ORACLE: remote` o `local`; si no, una heurística manda GPU/cómputo pesado (torch/cupy/jax, `differential_evolution`, multiprocessing) a ASTRUM y lo simbólico ligero a local |

---

## 7. `.env` — configuración de referencia

Vive en la raíz del proyecto (contiene tus keys; **no lo subas a git público**).
Claves relevantes de esta configuración:

```ini
# Proveedores por fase (config vigente 2026-07-15)
ASTRA_CONJECTURE_PROVIDER=claude_cli
ASTRA_TRANSLATOR_PROVIDER=claude_cli
ASTRA_ANALYST_PROVIDER=gemini      # API free-tier (flash): tercera pierna, no gasta cuota Claude
ASTRA_NAVIGATOR_PROVIDER=codex_cli

# Oráculo por defecto = ASTRUM
ASTRA_ORACLE_MODE=remote
ASTRA_ORACLE_TIMEOUT=180

# Conexión a ASTRUM (Tailscale)
ASTRA_REMOTE_HOST=astrum@100.66.143.117
ASTRA_REMOTE_PYTHON=~/astra-worker/venv/bin/python
ASTRA_REMOTE_WORKER=~/astra-worker/astra_remote_worker.py
ASTRA_REMOTE_WORKDIR=~/astra-worker/workspace
ASTRA_REMOTE_CONNECT_TIMEOUT=15
ASTRA_REMOTE_SSH_OPTIONS=-i C:\Users\Nelson\.ssh\google_compute_engine -o "ProxyCommand=tailscale nc %h %p"

# Escalera de fallback por CUOTA (cli_backend): modelos a intentar en orden.
# 'default' = el modelo por defecto del CLI (hoy claude=Opus 4.8). Las cuotas de
# suscripción son POR MODELO: agotar uno no agota los demás. Si hubo fallback,
# el JSON del ciclo trae 'warnings' (aviso textual) y 'cli_models' (quién
# respondió cada fase). Los peldaños agotados fallan en segundos: casi no añade latencia.
ASTRA_CLAUDE_MODELS=default,sonnet
# ASTRA_CODEX_MODELS=default

# Modelos por FASE (2026-07-15): escalera propia por fase; si esta vacia aplica
# la global del CLI. Conjetura queda en Opus (default); traductor/analista en
# Sonnet — el harness de auto-refutacion + auditor determinista absorben la
# diferencia, y ante cuota agotada la escalera SUBE a Opus sola.
ASTRA_TRANSLATOR_MODELS=sonnet,default
ASTRA_ANALYST_MODELS=sonnet,default
# Reintentos del ciclo: autofix mecanico gratis primero, luego traductor.
ASTRA_MAX_RETRIES=2
# Cache de ciclos (hash intuicion+providers+oraculo -> workspace/cycle_cache). 0=off.
ASTRA_CYCLE_CACHE=1
# Presupuesto POR llamada CLI (2026-07-15): una fase colgada muere sola
# (API_ERROR + nombre de fase) en vez de que el timeout externo del MCP mate
# el ciclo sin diagnostico. El kill es de ARBOL (taskkill /T): sin el, el
# claude nieto sobrevivia, el drenaje bloqueaba (fases de 956s medidas con
# timeout=600) y quedaba un huerfano quemando cuota por cada timeout.
ASTRA_CLI_TIMEOUT=240
# El TRADUCTOR es la fase lenta por naturaleza — MEDIDO: sonnet ~354s para
# ~194 lineas desde tarea compacta; conjeturas grandes de Opus -> mas.
# Presupuestos: 240 (conj) + 720 (trad) + 360 (retry minimo) + exec < 1800 (pared Codex).
ASTRA_TRANSLATOR_TIMEOUT=720
# Perplexity (API OpenAI-compatible; no existe CLI oficial de suscripcion):
# PERPLEXITY_API_KEY=pplx-...
```
Proveedores válidos por fase: `claude_cli`, `codex_cli`, `gemini_cli` (suscripción) o los de API (`gemini`, `openai`, `anthropic`, `vertexai`, `perplexity`, …) si tienes esas keys. Perplexity (`sonar-pro`, búsqueda web con citas) brilla como **navegador/conjetura con literatura al día**, no como traductor de código.

**`gemini_cli`** (añadido 2026-07-15, **aparcado**): el backend está completo (stdin + `-p .`, `-o json`, `--approval-mode plan` solo-lectura, escalera `ASTRA_GEMINI_MODELS`, OAuth forzado ocultando `GEMINI_API_KEY`), **pero Google descontinuó el gemini CLI para cuentas individuales el 2026-06-18** (`IneligibleTierError`: free/AI Pro/Ultra ya no son atendidos; el login se completa pero el backend rechaza). El reemplazo oficial es el **Antigravity CLI (`agy`)**, anunciado como fork compatible: cuando esté instalado desde un canal **oficial** (⚠️ el npm sin scope `antigravity-cli@0.0.1` NO es de Google — typosquat probable), basta `ASTRA_GEMINI_BIN='agy'` en el `.env` para activar todo. Mientras tanto, la tercera pierna práctica es el proveedor **`gemini` por API** (key ya en `.env`, free tier de AI Studio p/flash): `ASTRA_ANALYST_PROVIDER='gemini'`.

---

## 8. Cheat-sheet de comandos

```powershell
$CORE = "C:\Users\Nelson\Dev\ASTRA"
$PY   = "$CORE\venv\Scripts\python.exe"

# Abrir la web
& $PY "$CORE\web\app.py"

# Ciclo headless (sin web) — provider por fase
& $PY "$CORE\scripts\run_research_test.py" --provider claude_cli --cycles 1 --question "..."

# Ejecutar un script en ASTRUM directo (por la API subprocess)
'{"action":"execute","code":"import platform;print(platform.node());print(\"VERDICT: PASS\")","oracle":"astrum"}' | & $PY "$CORE\astra_tool.py"

# ¿ASTRUM vivo?  (ver §2)
# Salud del venv:
& $PY -c "import sympy,z3,qutip,einsteinpy,pint,fluids,networkx,flask; print('venv OK')"
```

---

## 9. Troubleshooting (problemas y soluciones aprendidas)

| Síntoma | Causa / Solución |
|---------|------------------|
| Todo tarda 30–100 s por paso | Arranque en frío del CLI de suscripción. **Normal**, no está colgado. |
| ¿Colgado o pensando? | Usa **`astra_probe`** (o lee `workspace\progress\cycle_*.json`): dice la fase en vuelo y hace cuántos segundos late. Regla de espera: fases de modelo 30–240 s; ejecución hasta su `exec_timeout`. Sondea 2-3 veces antes de matar nada. |
| `astra_cycle` colgado o lentísimo (histórico) | Resuelto 2026-07-15: los `claude -p` internos heredaban la config MCP **global** del usuario (recursión del propio server astra + servers `npx` que no conectan). Fix: `--strict-mcp-config` en `cli_backend.py` (además bajó el overhead por llamada ~7×). |
| `API_ERROR: ... usage limit` | Cuota del **modelo** agotada. La escalera `ASTRA_*_MODELS` baja sola al siguiente y deja `warnings` en el JSON del ciclo. Si dice `CUOTA AGOTADA en toda la escalera`, hay que esperar la ventana de uso, ampliar la escalera, o cambiar de cuenta (`codex login`; para claude, perfiles vía `CLAUDE_CONFIG_DIR`). |
| `warnings` en el resultado del ciclo | Una fase la respondió un modelo fallback por cuota (`cli_models` dice cuál). La calidad puede variar respecto al modelo principal. |
| Status `WEAK_PASS` | El script imprimió PASS pero el **auditor determinista** (AST, `core/verdict_guard.py`) lo rechazó: sin rama FAIL alcanzable, cero comparaciones, o CHECKs en FAIL. El ciclo ya reintenta reforzarlo solo (`ASTRA_MAX_RETRIES`); si persiste, trátalo como "no verificado". |
| El mismo prompt vuelve al instante con `cached: true` | Cache de ciclos (`workspace/cycle_cache/`). Es correcto: misma intuición+providers+oráculo ⇒ misma matemática. Bórralo o `ASTRA_CYCLE_CACHE=0` para forzar recomputo. |
| Timeout del ciclo sin saber qué fase colgó | Ya no pasa (2026-07-15): cada llamada CLI muere sola a los `ASTRA_CLI_TIMEOUT` s → `API_ERROR` + fase; el resultado trae `timings` (segundos por fase); y si el timeout externo aun mata el proceso, el error del MCP incluye `last_progress` (fase culpable + edad) leído de `workspace\progress\cycle_<pid>.json`. |
| Tailscale `NoState` con servicio Running (ASTRUM inalcanzable, `Connection closed by UNKNOWN port 65535`) | Causa vista 2026-07-15: la GUI `tailscale-ipn.exe` no estaba corriendo y sin *unattended mode* el demonio espera el perfil para siempre. Fix: arrancar la GUI o mejor `tailscale set --unattended=true` (**ya aplicado** — sobrevive sin GUI). Reiniciar solo el servicio NO basta. |
| ASTRUM no responde | Tailscale caído o nodo apagado → usa **Oráculo: Local** mientras tanto. |
| `cannot import name 'BinaryRelation'` (sympy) | sympy 1.14 corrupto → reinstala `sympy<1.14` (§3.1). |
| Web no arranca (`werkzeug...`) | paquete web corrupto → `pip install --force-reinstall flask werkzeug`. |
| Codex se cuelga | Requiere CLI ≥0.144 y stdin con EOF — **ya manejado** en `cli_backend.py`. |
| `gemini_cli` → `IneligibleTierError: no longer supported for individuals` | **No es tu auth**: Google cortó el gemini CLI para cuentas individuales (2026-06-18). Migrar al Antigravity CLI (`agy`, solo canal oficial) y poner `ASTRA_GEMINI_BIN='agy'`; o usar el proveedor `gemini` por API. (Gotcha Windows ya manejado: `-p ""` pierde el arg vacío en PowerShell → se usa `-p .`.) |
| `astra_execute` da `CODE_ERROR` | El código generado falló; `astra_cycle` reintenta 1 vez. Con `astra_execute`, corrige y reintenta tú. |
| Un `VALIDATED` sospechoso | El analista está **endurecido**: exit≠0 nunca es VALIDATED; confía en `VERDICT:` del script. |

---

## 10. Filosofía (por qué está hecho así)

- **Sin API de pago:** los CLIs oficiales corren con tus mensualidades; el razonamiento caro lo pagan tus suscripciones.
- **Verificador objetivo:** tres LLMs pueden coincidir en algo elegante y *falso*. Solo el cómputo real (sympy que cierra, unidades que cuadran, simulación que corre en ASTRUM) convierte esto en ciencia. Por eso el veredicto se ancla al `exit_code` + `VERDICT:` del script, no a la opinión de un modelo.
- **Tú eliges cómo trabajar:** web para control visual; MCP para que tu agente favorito sea el enlace. Oráculo local o remoto según convenga.
