# ASTRA — Manual de Usuario

**Asistente Autónomo de Investigación en Teoría Científica**
Versión 1.0 — Mayo 2026

---

## Tabla de Contenidos

1. [Descripción General](#1-descripción-general)
2. [Requisitos del Sistema y Arranque](#2-requisitos-del-sistema-y-arranque)
3. [Distribución de la Interfaz](#3-distribución-de-la-interfaz)
4. [Modo Ciclo Único](#4-modo-ciclo-único)
5. [Modo Bucle de Investigación](#5-modo-bucle-de-investigación)
6. [Comprensión de los Paneles de Salida](#6-comprensión-de-los-paneles-de-salida)
7. [Referencia de Estados](#7-referencia-de-estados)
8. [Configuración de Proveedores](#8-configuración-de-proveedores)
9. [Resolución de Problemas](#9-resolución-de-problemas)

---

## 1. Descripción General

ASTRA es un sistema multi-modelo orientado por objetivos, diseñado para generar,
desafiar, formalizar y validar hipótesis científicas mediante deliberación:

| Fase | Agente | Función |
|------|--------|---------|
| 1 — Recepción | — | Recibe la intuición o documento del usuario |
| 2 — Deliberación | Codex + agy | Generan conjeturas independientes, hacen crítica cruzada y sintetizan un consenso ligado al objetivo |
| 3 — Traducción | Claude Opus 4.8 | Escribe un validador falsable en Python, CAS o Lean |
| 4 — Revisión de código | Codex | Audita si el código de Claude puede probar o refutar los claims decisivos |
| 5 — Oráculo de Validación | Ejecutor sandbox/ASTRUM | Ejecuta el script aprobado y captura evidencia reproducible |
| 6 — Análisis | Codex | Lee código y evidencia: VALIDATED, REFUTED o CODE_ERROR |
| 7 — Navegación | agy | Relaciona el resultado con el objetivo final y propone el siguiente paso |

ASTRA opera en dos modos:

- **Ciclo Único** — el usuario aporta una intuición; ASTRA la procesa a través del pipeline una vez y espera aprobación antes de agregar el resultado a la Base Axiomática.
- **Bucle de Investigación** — el usuario aporta una pregunta macro; los tres
  modelos la comparten mientras agy navega ciclos deliberativos sucesivos.

---

## 2. Requisitos del Sistema y Arranque

### Requisitos previos

- Python 3.10 o superior
- Las CLI autenticadas de Codex, Claude Code y Antigravity (`agy`) para el mapa
  de producción, o al menos un proveedor API opcional
- Todas las dependencias Python instaladas (`pip install -r requirements.txt` dentro del `venv`)

### Variables de entorno

Configura tus claves en un archivo `.env` en el directorio raíz de `ASTRA_Production/`:

```
GEMINI_API_KEY=tu_clave_aqui
ANTHROPIC_API_KEY=tu_clave_aqui
OPENAI_API_KEY=tu_clave_aqui
VERTEX_PROJECT=tu_id_de_proyecto_gcp
VERTEX_LOCATION=us-central1
```

Solo es necesario incluir las claves de los proveedores que vayas a utilizar.

### Arranque

Ejecuta el asistente de configuración ASTRA desde la terminal:

```powershell
cd ASTRA_Production
.\venv\Scripts\python.exe wizard.py
```

El asistente realiza una verificación previa (dependencias, claves, CAS externos) y luego inicia el servidor Flask en el puerto **5050**. Abre el navegador en:

```
http://localhost:5050
```

---

## 3. Distribución de la Interfaz

La interfaz está dividida en tres secciones:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ASTRUM / Production                        [IDLE]  Ciclo 0       [Ayuda]  │
├──────────────────────┬──────────────────────────────────────────────────────┤
│                      │                                                      │
│    BARRA LATERAL     │    LIENZO PRINCIPAL                                  │
│                      │                                                      │
│  Toggle de modo      │  [Hilo de Investigación] [Registro de Ramas] ← inv. │
│  Panel de entrada    │                                                      │
│  Log del sistema     │  [Hipótesis]                                         │
│                      │  [Script de Validación]                              │
│                      │  [Informes de Ciclo]   [Base Axiomática]             │
└──────────────────────┴──────────────────────────────────────────────────────┘
```

**Barra superior** — muestra la pastilla de estado actual y el contador de ciclos. Se vuelve roja si el servidor queda fuera de línea.

**Barra lateral** — contiene el toggle de modo, el panel de entrada (Ciclo Único) o el panel de sesión (Bucle de Investigación), y el Log del Sistema en tiempo real con una barra de progreso.

**Lienzo principal** — área principal de información. Los paneles Hilo de Investigación y Registro de Ramas solo son visibles en el Modo Bucle de Investigación.

---

## 4. Modo Ciclo Único

### Paso a paso

1. Asegúrate de que la pestaña **Single Cycle** esté seleccionada en el toggle de modo.

2. Escribe una afirmación científica falsificable en el área de texto **Intuition Input**.

   Las buenas intuiciones son:
   - Específicas y acotadas (no preguntas de investigación abiertas)
   - Falsificables en principio mediante computación
   - Expresadas en términos que puedan traducirse a código SymPy/SciPy

   **Ejemplo:** "Verificar si el tensor de Ricci se anula fuera de r = 2M para la métrica de Schwarzschild."

3. (Opcional) Sube un documento PDF o TXT usando la zona de arrastre — ASTRA extraerá el texto y lo usará como contexto de la intuición.

4. Selecciona los proveedores de IA preferidos para Conjetura, Traductor y Analista usando los menús desplegables.

5. Haz clic en **Launch Cycle**. La barra de progreso y el Log del Sistema mostrarán el avance del pipeline en tiempo real.

6. Cuando el pipeline complete exitosamente, aparecerá el **Modal de Aprobación**:
   - **Approve & Add** — agrega el teorema validado a la Base Axiomática, donde podrá informar ciclos futuros.
   - **Reject** — descarta el resultado.

7. Si el ciclo resulta en **REFUTED**, no se requiere aprobación. El resultado aparece en los Informes de Ciclo.

8. Haz clic en **Launch Cycle** de nuevo para ejecutar otro ciclo con una intuición nueva o refinada.

### Qué muestra cada fase en el log

| Estado mostrado | Qué está ocurriendo |
|---|---|
| CONJECTURING | El Motor de Conjeturas está formalizando la intuición |
| TRANSLATING | El Traductor Formal está generando el script de validación |
| VALIDATING | El script se está ejecutando en el sandbox |
| ANALYZING | El Analista de Refutación está interpretando la salida |
| WAITING_APPROVAL | Pipeline exitoso — en espera de la decisión humana |
| IDLE | No hay ningún ciclo en ejecución |

---

## 5. Modo Bucle de Investigación

### Concepto

En el Modo Bucle de Investigación, ASTRA actúa como asistente de investigación autónomo. En lugar de una intuición única, el usuario proporciona una **pregunta de investigación macro** — una pregunta científica amplia que no puede responderse en un único ciclo. ASTRA entonces:

1. Genera una hipótesis relevante para la pregunta
2. La valida
3. Pasa el resultado al **Navegador de Investigación**, que decide la siguiente dirección
4. Ejecuta el siguiente ciclo de forma automática
5. Pausa en los **hitos** para revisión humana

El Navegador también identifica **ramas paralelas** — sub-preguntas independientes que vale la pena explorar más tarde — y las guarda en el Registro de Ramas.

### Paso a paso

1. Haz clic en **Research Loop** en el toggle de modo en la parte superior de la barra lateral.

2. Escribe tu **pregunta de investigación macro** en el área de texto.

   Una buena pregunta macro es:
   - Abierta (no puede responderse en un solo ciclo)
   - Científicamente precisa
   - Apta para validación computacional

   **Ejemplo:** "Determinar si la métrica de Alcubierre requiere densidad de energía estrictamente negativa en todo el interior de la burbuja, o si modificaciones geométricas pueden localizar o reducir los requisitos de materia exótica."

3. Selecciona proveedores de IA para los cuatro roles: Conjetura, Traductor, Analista y **Navegador**.

4. Establece el intervalo de **Heartbeat** — el número máximo de ciclos entre puntos de control forzados. El valor predeterminado es 5. El Navegador puede pausar antes si juzga que un resultado es un hito significativo.

5. Haz clic en **Launch Session**. La barra lateral mostrará la información de sesión activa con contadores en vivo.

6. ASTRA ejecutará ciclos de forma autónoma. Observa el panel **Hilo de Investigación** para ver el historial completo, y los paneles de **Script de Validación** e **Hipótesis** para ver qué ocurre en el ciclo actual.

7. Cuando se alcance un **hito**, ASTRA pausará y aparecerá automáticamente el **Modal de Propuesta del Navegador**.

### El Modal de Propuesta del Navegador

Este modal aparece en cada hito y muestra:

| Campo | Significado |
|---|---|
| Checkpoint Reason | Por qué el Navegador decidió pausar aquí |
| Progress Assessment | Resumen honesto de una frase sobre el avance de la investigación |
| Proposed Next Direction | La dirección recomendada por el Navegador para el próximo ciclo |
| Navigator Rationale | El razonamiento detrás de esa recomendación |
| Pending Branches (si las hay) | Direcciones paralelas guardadas que puedes activar en su lugar |

Tienes tres opciones:

- **Continue with Proposed Direction** — acepta la recomendación del Navegador y reanuda el ciclo de forma autónoma.
- **Redirect** — escribe tu propia dirección en el campo de texto y haz clic en Redirect. ASTRA usará tu dirección para el próximo ciclo en lugar de la propuesta.
- **Activate a Branch** — haz clic en cualquier botón de rama para cambiar a una dirección paralela guardada. ASTRA explorará esa rama como el nuevo hilo principal.

### El panel Registro de Ramas

El Registro de Ramas lista todas las direcciones paralelas propuestas por el Navegador durante la sesión. Cada entrada muestra:

- El ID de rama (identificador corto en snake_case)
- La dirección de investigación
- La motivación (por qué el Navegador la guardó)
- Estado: **PENDING** (no explorada aún), **ACTIVE** (en exploración activa) o **COMPLETED** (exploración finalizada)

Haz clic en **Activate** sobre cualquier rama PENDING para redirigir la sesión hacia esa rama en el próximo hito.

### Detener una sesión

Haz clic en **Stop** en cualquier momento. El ciclo actual completará su ejecución y ASTRA volverá a IDLE. Los datos de la sesión se guardan automáticamente en `workspace/sessions/session_{id}.json`.

---

## 6. Comprensión de los Paneles de Salida

### Panel Hipótesis

Muestra la conjetura completa formulada por el Motor de Conjeturas en el ciclo actual. La notación matemática se renderiza usando MathJax (LaTeX en línea y en bloque). Usa **Copy** para copiar el texto en crudo.

### Panel Script de Validación

Muestra el código Python generado por el Traductor Formal. Resaltado de sintaxis con Prism. Usa **Copy** para copiar el script. Este es el código que efectivamente se ejecuta en el Oráculo de Validación.

### Panel Hilo de Investigación *(solo Bucle de Investigación)*

Lista cronológica de todos los ciclos completados en la sesión actual. Cada entrada muestra:

- **C1, C2 …** — número de ciclo
- Insignia de estado: VALIDATED en verde, REFUTED en ámbar, CODE_ERROR en rojo
- Marca de tiempo
- Fragmento de la conjetura (primeros ~180 caracteres, en fuente monoespaciada)
- La dirección elegida por el Navegador para el siguiente ciclo (en azul)

### Panel Registro de Ramas *(solo Bucle de Investigación)*

Lista todas las ramas paralelas guardadas por el Navegador. Ver Sección 5 para más detalles.

### Panel Informes de Ciclo

Muestra una lista de todos los ciclos completados con enlaces a los informes generados (HTML, Markdown, PDF cuando estén disponibles). Haz clic en cualquier enlace para abrir el informe completo en una nueva pestaña.

### Panel Base Axiomática

Muestra todos los teoremas que han sido validados y aprobados durante la sesión. El contenido se renderiza con MathJax. La Base Axiomática se proporciona al Motor de Conjeturas en cada ciclo siguiente, asegurando que la investigación se acumule de forma coherente.

### Panel Log del Sistema

Muestra líneas de log en tiempo real provenientes del backend de ASTRA. Útil para monitorizar el progreso o diagnosticar errores. Incluye el chip del nombre de fase y la barra de progreso. Se desplaza automáticamente a la última entrada.

---

## 7. Referencia de Estados

| Estado | Descripción | Acción requerida |
|---|---|---|
| IDLE | No hay ningún ciclo en ejecución | Ninguna |
| CONJECTURING | El Motor de Conjeturas está trabajando | Esperar |
| TRANSLATING | El Traductor Formal está generando código | Esperar |
| VALIDATING | El Oráculo está ejecutando el script | Esperar |
| ANALYZING | El Analista está interpretando los resultados | Esperar |
| NAVIGATING | El Navegador está calculando la siguiente dirección | Esperar |
| WAITING_APPROVAL | Hipótesis validada; en espera de decisión humana | Aprobar o Rechazar en el modal |
| WAITING_DIRECTION | Hito de investigación alcanzado; en espera de decisión humana | Usar el Modal de Propuesta del Navegador |
| OFFLINE | Servidor Flask inaccesible | Reiniciar el asistente |

---

## 8. Configuración de Proveedores

ASTRA soporta los siguientes proveedores LLM:

| Clave de proveedor | Modelo utilizado | Variable de clave API |
|---|---|---|
| `codex_cli` | GPT-5.6 Sol (`xhigh`) | Inicio de sesión de la suscripción Codex |
| `claude_cli` | Claude Opus 4.8 | Inicio de sesión de Claude Code |
| `agy_cli` | Gemini 3.1 Pro High mediante Antigravity | Inicio de sesión Google/Antigravity |
| `vertexai` | Gemini 2.5 Flash (vía GCP) | `VERTEX_PROJECT` + ADC |
| `gemini` | Gemini 2.5 Flash | `GEMINI_API_KEY` |
| `anthropic` | Claude Sonnet 4.6 | `ANTHROPIC_API_KEY` |
| `openai` | GPT-4o | `OPENAI_API_KEY` |
| `deepseek` | DeepSeek R1 | `DEEPSEEK_API_KEY` |
| `xai` | Grok 3 | `XAI_API_KEY` |
| `qwen` | Qwen2.5-Math-72B | `DASHSCOPE_API_KEY` |
| `mistral` | Mistral Large | `MISTRAL_API_KEY` |
| `codestral` | Codestral | `MISTRAL_API_KEY` |
| `groq` | Llama 3.3 70B | `GROQ_API_KEY` |

**Configuración recomendada:**

| Rol | Proveedor recomendado | Motivo |
|---|---|---|
| Conjetura | `codex_cli,agy_cli` | Propuestas independientes y crítica cruzada adversarial |
| Síntesis | `codex_cli` | Síntesis matemática orientada al objetivo |
| Traductor | `claude_cli` | Opus 4.8 escribe y revisa el validador |
| Revisor de código | `codex_cli` | Auditoría independiente del programa de Claude |
| Analista | `codex_cli` | Lee el código y la evidencia de ejecución |
| Navegador | `agy_cli` | Explora el siguiente paso respecto del objetivo compartido |

Los proveedores CLI usan OAuth de suscripción y no requieren clave API del
modelo. Las APIs siguen siendo opcionales; un proveedor API sin credenciales
opera en modo simulado.

---

## 9. Resolución de Problemas

**El ciclo se queda en IDLE después de hacer clic en Launch**
- Confirma que el servidor Flask esté en ejecución (revisa la terminal).
- Verifica que al menos una clave API esté configurada en `.env`.
- Recarga la página e intenta de nuevo.

**CODE_ERROR repetido en cada reintento**
- El Traductor está generando código no válido. Reformula la intuición de manera más concreta y específica. Evita formulaciones abiertas o ambiguas.
- Prueba cambiar el proveedor del Traductor (Claude y Codestral tienden a producir el Python más confiable).

**REFUTED en una afirmación que crees verdadera**
- Lee el informe completo (Informes de Ciclo → HTML). El razonamiento del Analista explicará qué encontró la validación.
- La afirmación puede ser verdadera pero demasiado abstracta para que el validador actual la verifique. Intenta reformularla de forma más concreta.

**El Bucle de Investigación no pausa en los hitos**
- Reduce el intervalo de heartbeat (por ejemplo, a 3 ciclos).
- Revisa el Log del Sistema — si el Navegador está fallando en el parseo, puede estar omitiendo la detección de hitos.

**El Modal de Propuesta del Navegador no aparece**
- Confirma que el servidor devolvió el estado `WAITING_DIRECTION` (visible en la pastilla de la barra superior).
- Recarga la página — el modal debería reaparecer dentro del siguiente ciclo de sondeo (1 segundo).

**El servidor muestra OFFLINE**
- El proceso Flask se ha detenido. Reinicia el asistente desde la terminal.
- Si el puerto 5050 está ocupado, termina el proceso existente: `Get-Process python | Stop-Process`.

**Error de autenticación Vertex AI / ADC**
- Ejecuta `gcloud auth application-default login` en la terminal.
- Confirma que `VERTEX_PROJECT` esté configurado correctamente en `.env`.

**La subida de PDF no funciona**
- PyMuPDF debe estar instalado: `pip install PyMuPDF`.
- El paso de instalación automática del asistente debería encargarse de esto en el primer arranque.

**CAS externo no encontrado (SageMath, Maxima)**
- Son opcionales. Ejecuta `install_windows_wsl.ps1` para instalarlos vía WSL.
- La validación solo con Python (SymPy, SciPy, NumPy) funciona para la mayoría de los dominios científicos sin necesidad de estos.

---

*ASTRA está desarrollado por Astrum Drive Technologies.*
*Para problemas técnicos, consulta el Log del Sistema o contacta al equipo de desarrollo.*
