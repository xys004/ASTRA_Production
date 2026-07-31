# Optimización de cuota — 2026-07-31

**Principio rector (decisión de Nelson): la ciencia primero.** En ASTRA la calidad
científica la garantiza la capa determinista (oráculo + `verdict_guard` + patas CHECK
+ Z3), no el nivel del modelo. Los modelos proponen; la máquina dispone. Por tanto:
frontier donde se crea ciencia (conjetura), barato-con-escalada donde las guardas
detectan cualquier bajón (traductor).

## Auditoría que motivó esto (33 ciclos de cycle_cache)

- 97,5 % del tiempo de modelo en DOS fases: translate 49,6 %, conjecture 47,9 %.
- Traductor en Opus (26 ciclos) vs sonnet (7): mismas ~150 líneas, sonnet más rápido
  y con 0 retries. Opus no compraba nada medible.
- Conjetura ensemble triple (agy + codex + merge Opus, 25 ciclos): 467 s vs 188 s del
  proveedor único, sin mejora en retries. El merge con Opus paga por leer las salidas
  de los otros dos: multiplica, no suma.
- `ASTRA_NAVIGATE_AFTER_CYCLE=1` disparaba agy tras cada ciclo sin dejar rastro en
  ningún timing (cuota invisible).
- Advertencia: n pequeño y sin aleatorización — no es un experimento controlado.
  La comparación real la darán los próximos 10–15 ciclos contra este baseline.

## Cambios aplicados (backups `.bak_20260731`)

### `.env`
| Variable | Antes | Ahora |
|---|---|---|
| `ASTRA_CONJECTURE_PROVIDER` | `'codex_cli,agy_cli'` (+merge Opus) | `'codex_cli'` |
| `ASTRA_TRANSLATOR_MODELS` | `'claude-opus-4-8,sonnet'` | `'sonnet,claude-opus-4-8'` |
| `ASTRA_NAVIGATE_AFTER_CYCLE` | `'1'` | `'0'` (opt-in) |

Sin tocar: `ASTRA_CODEX_REASONING='xhigh'` (es el motor de la conjetura — ciencia
primero), `ASTRA_CLAUDE_MODELS` global (Opus-first, protege cualquier fase claude sin
escalera propia), verdict_guard, oráculo.

**Modo profundo**: para un problema que merezca el ensemble, volver a poner
`ASTRA_CONJECTURE_PROVIDER='codex_cli,agy_cli'` para esa corrida.

### `astra_tool.py` — escalada por CALIDAD
La escalera de `cli_backend` solo desciende por errores de CUOTA. Antes, un retry por
`WEAK_PASS`/`CODE_ERROR` repetía con el mismo modelo. Ahora `_escalate_agent_models()`
sube el peldaño del traductor en cada retry de calidad: con la escalera invertida,
sonnet produce y Opus entra exactamente cuando el guard demostró que sonnet no bastó.
Queda registrado en `out["quality_escalations"]`.

### `astra_tool.py` + `core/llm_client.py` — telemetría de coste
Cada agente acumula `cli_cost_usd` (lo reporta el CLI de claude; codex/agy dan 0) y el
JSON del ciclo lo expone en `out["cli_cost_usd"]` con total. Antes esta cifra se
tiraba: la auditoría tuvo que usar tiempo-por-fase como proxy.

## Estado de verificación

- `py_compile` OK en ambos ficheros; helper de escalada con test unitario 5/5
  (incluye comillas del .env y espacios).
- **Pendiente el canario en vivo**: no se corrió ciclo real para no gastar justo lo
  que se quiere ahorrar. El primer ciclo tras reiniciar la sesión hace de canario;
  verificar que el JSON trae `cli_models.translator=sonnet` y `cli_cost_usd`.

## Cómo medir (los próximos 10–15 ciclos)

Comparar contra los 33 del baseline: tasa de retry (baseline 1/33), tasa de
WEAK_PASS, distribución VALIDATED/REFUTED, `timings` por fase, y ahora `cli_cost_usd`
real. Si la calidad se resiente, la escalada ya está pagando Opus sola; si ni así,
rollback = restaurar los tres `.bak_20260731`.

## Recordatorios operativos

- **Reiniciar la sesión de Codex/cliente**: `load_dotenv` no pisa variables ya
  cargadas en el proceso del server MCP; el `.env` nuevo entra al reiniciar.
- El doble-pago restante es de uso, no de config: conducir ASTRA en vivo desde una
  sesión interactiva re-razona y reenvía contexto en cada turno. Para ciclos largos:
  `astra_cycle_submit` / `astra_submit` y sondear con `astra_probe`/`astra_job`.
- `agy`: fuera de la ruta crítica. Su esfuerzo real no es auditable desde fuera
  (declara "Pro High" pero Nelson observa comportamiento light). Vive solo en el
  navegador opt-in.
