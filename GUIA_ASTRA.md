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

**Piezas clave y rutas** (todo bajo `C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production\`):

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
cd C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production
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
| `astra_execute` | `(code, oracle="astrum", timeout=180)` | corre TU código y devuelve stdout + veredicto |
| `astra_cycle` | `(intuition, oracle="astrum", timeout=420)` | pipeline completo de ASTRA sobre una intuición |
| `astra_status` | `()` | ¿ASTRUM está vivo? |

**Devuelven JSON** con `stdout`, `exit_code`, `verdict` (PASS/FAIL/NONE), `oracle_used`, etc.
El script debe terminar imprimiendo `VERDICT: PASS` o `VERDICT: FAIL`.

### Ejemplos de lo que le dices al agente
- *"Con `astra_status`, confirma que ASTRUM está disponible."*
- *"Escribe un script sympy que verifique que el Ricci de Schwarzschild es 0 y córrelo con `astra_execute` en ASTRUM."*
- *"Usa `astra_cycle` para investigar si la métrica X viola la NEC."*

### 5.1 (Re)registrar el MCP
```powershell
$MPY = "C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production\mcp_server\venv\Scripts\python.exe"
$SRV = "C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production\mcp_server\server.py"

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
| **`astrum`** (default) | corre en tu workstation remota (RTX 3080, stack completo) |
| **`local`** | corre en el venv 3.9 local — rápido, siempre disponible, **fallback si ASTRUM está caído** |
| **`auto`** | *deciden los modelos*: el traductor puede marcar `# ASTRA_ORACLE: remote` o `local`; si no, una heurística manda GPU/cómputo pesado (torch/cupy/jax, `differential_evolution`, multiprocessing) a ASTRUM y lo simbólico ligero a local |

---

## 7. `.env` — configuración de referencia

Vive en la raíz del proyecto (contiene tus keys; **no lo subas a git público**).
Claves relevantes de esta configuración:

```ini
# Proveedores por fase (backend de suscripción)
ASTRA_CONJECTURE_PROVIDER=codex_cli
ASTRA_TRANSLATOR_PROVIDER=claude_cli
ASTRA_ANALYST_PROVIDER=claude_cli
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
```
Proveedores válidos por fase: `claude_cli`, `codex_cli` (suscripción) o los de API (`gemini`, `openai`, `anthropic`, `vertexai`, …) si tienes esas keys.

---

## 8. Cheat-sheet de comandos

```powershell
$CORE = "C:\Users\Nelson\Desktop\Proyectos\ASTRA_Production"
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
| `API_ERROR: ... usage limit` | Cuota de la cuenta agotada. Espera el reset, o cambia de cuenta (`codex login`). |
| ASTRUM no responde | Tailscale caído o nodo apagado → usa **Oráculo: Local** mientras tanto. |
| `cannot import name 'BinaryRelation'` (sympy) | sympy 1.14 corrupto → reinstala `sympy<1.14` (§3.1). |
| Web no arranca (`werkzeug...`) | paquete web corrupto → `pip install --force-reinstall flask werkzeug`. |
| Codex se cuelga | Requiere CLI ≥0.144 y stdin con EOF — **ya manejado** en `cli_backend.py`. |
| `astra_execute` da `CODE_ERROR` | El código generado falló; `astra_cycle` reintenta 1 vez. Con `astra_execute`, corrige y reintenta tú. |
| Un `VALIDATED` sospechoso | El analista está **endurecido**: exit≠0 nunca es VALIDATED; confía en `VERDICT:` del script. |

---

## 10. Filosofía (por qué está hecho así)

- **Sin API de pago:** los CLIs oficiales corren con tus mensualidades; el razonamiento caro lo pagan tus suscripciones.
- **Verificador objetivo:** tres LLMs pueden coincidir en algo elegante y *falso*. Solo el cómputo real (sympy que cierra, unidades que cuadran, simulación que corre en ASTRUM) convierte esto en ciencia. Por eso el veredicto se ancla al `exit_code` + `VERDICT:` del script, no a la opinión de un modelo.
- **Tú eliges cómo trabajar:** web para control visual; MCP para que tu agente favorito sea el enlace. Oráculo local o remoto según convenga.
