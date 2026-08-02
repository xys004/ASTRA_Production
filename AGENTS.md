# ASTRA Agent Notes

## Al redactar artículos: `PUBLICATION_POLICY.md` (congelada 2026-07-31)

Obligatoria antes de escribir cualquier manuscrito con resultados de ASTRA. En
resumen: **las auditorías internas no se citan en artículos** (nada de identificadores
de ciclo, ni VALIDATED/REFUTED/WEAK_PASS, ni "ASTRA validó que…"), y todo manuscrito
lleva el **código extraído como artefacto independiente** que el referee pueda correr
sin ASTRA y que reproduzca las cifras del texto. Los volcados de auditoría solo van en
informes de empresa, y solo si Nelson lo pide explícitamente.

## Motores de cálculo en el clúster: NO uses el PATH para descubrirlos

`command -v sage` / `which cadabra2` / `which lean` devuelven **NADA** aunque los
tres estén instalados en Astrum. Viven en envs de conda y toolchains de elan. Para
saber qué hay: `~/astra-worker/astra_engine.sh list`. Para usar:
`astra_engine.sh <sage|cadabra|oracle|lean|sci|maxima|pkgs> <fichero>`.
Instrucción completa para pegar a otro agente:
`C:/Users/Nelson/CLUSTER_ENGINES_FOR_AGENTS.md`

Before changing the remote oracle path, read:

- `C:\Users\Nelson\REMOTE_CLUSTER_GUIDE.md`
- `REMOTE_ORACLE_HANDOFF.md`
- `remote/README.md`

Do not print or commit secrets. `.env` may contain API keys and remote oracle
settings. Local passwords, if needed, live outside this repo in:

`C:\Users\Nelson\Documents\ASTRA Remote\astra_remote_secrets.local.txt`

Use the remote check script after touching executor/oracle code:

```powershell
.\remote\check_remote_oracle.ps1
```
