# Guía de ASTRA

ASTRA es un sistema de investigación científica multiagente que convierte una
intuición en una conjetura falsable, genera un validador ejecutable, revisa ese
código, obtiene evidencia en un oráculo local o ASTRUM y analiza los límites del
resultado.

## Arquitectura de producción

| Función | Modelo |
|---|---|
| Conjetura, síntesis, revisión y análisis | Codex CLI |
| Segunda conjetura, crítica y navegación | Antigravity `agy` CLI |
| Escritura y reparación del validador | Claude Code CLI |

Los tres reciben el objetivo científico compartido. Antigravity o Codex pueden
ser la interfaz del investigador mediante MCP, pero no sustituyen a ninguno de
los tres CLI internos.

## Instalación

- macOS: `docs/onboarding/ASTRA_MACOS_INSTALL_ES.md`
- inicio rápido en Mac: `docs/onboarding/ASTRA_MACOS_QUICKSTART_ES.md`
- manual completo en español: `MANUAL_ES.md`
- manual completo en inglés: `MANUAL_EN.md`
- Windows: sección correspondiente de `README.md`

Las credenciales son siempre individuales. No se comparten `.env`, claves SSH
privadas, tokens de los modelos ni estado de Tailscale.

## Formas de uso

La interfaz web se inicia con `launch_astra.bat` en Windows o
`./launch_astra.sh` en macOS. Un agente conectado al MCP dispone de:

- `astra_capacity`: capacidad local y política de paralelismo;
- `astra_status`: conectividad con ASTRUM;
- `astra_engines`: inventario autoritativo de motores del clúster;
- `astra_execute`: ejecución de un validador existente;
- `astra_client_validate`: evidencia mínima estructurada para aplicaciones;
- `astra_cycle_submit`: ciclo deliberativo persistente;
- `astra_job`: seguimiento de trabajos;
- `astra_probe`: diagnóstico de un ciclo síncrono aparentemente lento.

Para trabajos científicos serios se recomienda `astra_cycle_submit` seguido de
`astra_job`. Los ciclos completos se serializan porque comparten las cuentas de
los modelos; los validadores independientes pueden aprovechar varios cores.

## Validadores

La máquina local ofrece Python, SymPy, Z3, NumPy/SciPy, mpmath, QuTiP, Pint y
otros paquetes de `requirements.txt`. ASTRUM mantiene SageMath, Maxima, Cadabra,
Lean, entornos GPU, el entorno científico `sci` y los paquetes propios `pkgs`.

Los motores remotos se descubren con `astra_engines`, no con `which`. Para un
validador que necesite los paquetes propios:

```python
# ASTRA_ENGINE: pkgs
# ASTRA_ORACLE: remote
```

Para el entorno de materiales y materia condensada:

```python
# ASTRA_ENGINE: sci
# ASTRA_ORACLE: remote
```

## Interpretación correcta

Un resultado tiene capas distintas:

- `job.status`: el proceso terminó o no;
- `oracle_verdict`: el programa ejecutado pasó o falló;
- `atomic_status`: estado de la conjetura acotada;
- `goal_coverage` y `scientific_status`: cobertura del objetivo general.

Un `PASS` del oráculo no certifica automáticamente un artículo o programa de
investigación completo. Deben conservarse supuestos, limitaciones, elementos
diferidos, artefactos y comandos de reproducción.

## Verificación de la instalación

```bash
venv/bin/python scripts/astra_doctor.py --remote
venv/bin/python scripts/audit_architecture.py
venv/bin/python -m pytest -q
```

En Windows se usan las rutas equivalentes bajo `venv\Scripts\`.
