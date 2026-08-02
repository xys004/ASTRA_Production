# Paquetes de cálculo propios en Astrum

Motor: `~/astra-worker/astra_engine.sh pkgs fichero.py`
Env: `~/miniforge3/envs/pkgs` (py3.12, jax-CUDA, cupy) · Código: `~/pkgs`

**ASTRA NO vive aquí.** ASTRA es un framework que necesita CLIs de IA (`claude`,
`codex`, …) para funcionar, y en este nodo no hay ninguno instalado —
deliberadamente. ASTRA corre en la máquina de Nelson y usa el clúster como brazo
de cálculo: le manda código, el clúster lo ejecuta y devuelve resultados. Lo que sí
vive aquí es `~/astra-worker/astra_remote_worker.py`, que es el receptor de esos
envíos, no el framework.

---

## Relatividad general y warp

| Paquete | Papel |
|---|---|
| **GR_python** | Motor GR base: tensores, biblioteca de métricas, ADM 3+1, Petrov, horizontes, geodésicas, Penrose |
| **grthermo** | Termodinámica en GR. **Trabaja EN CONJUNTO con GR_python**: calcula sobre las métricas y tensores que aquél provee, vía `grthermo.bridge_gr_python.load_gr_python()`. Sin GR_python presente, 20 de sus 104 tests se saltan en silencio |
| **pyWarpFactory** | Árbitro de condiciones de energía + solver Lichnerowicz/Bowen-York |
| **TELAR** | Optimización de configuraciones espacio-temporales; usa pyWarpFactory como tercer validador opcional |
| **warp_nn** | PINN sobre GPU (jax + CUDA) |
| **natario** | Cota de energía de Natário; usa grthermo |
| **metric-engine** | Laboratorio de ingeniería métrica (scripts, no paquete) |

## Fundamentos / espacio-tiempo emergente

| Paquete | Papel |
|---|---|
| **protoespacio** | Sustrato discreto Dirac–Weyl → geometría lorentziana emergente → GR inducida. Adyacente a GR pero no es GR clásica: su objeto es de dónde SALE la geometría |

## Materia condensada / transporte cuántico

| Paquete | Papel |
|---|---|
| **QuantumTransportEOM** | Transporte cuántico, CISS, Keldysh / Kadanoff–Baym |
| **mobius_cylinder_rsoc** | Acoplamiento espín-órbita Rashba en geometrías Möbius y cilindro |

## Fluidos / mecánica estadística

| Paquete | Papel |
|---|---|
| **rectification_design_map** | Rectificación en interfases líquido–vapor; companion del paper de covarianza agua–vapor |

---

## Cadenas de dependencia entre paquetes propios

```
GR_python  ──>  grthermo  ──>  natario
pyWarpFactory  ──>  TELAR
```

Nada más. `mobius_cylinder_rsoc` y `rectification_design_map` **no dependen de
ninguno de los otros y no tienen relación con GR** — comparten env por comodidad de
despliegue, no por parentesco temático.

## Por qué un solo entorno

Todos los conflictos de versión declarados son cotas mínimas compatibles (`>=`):
numpy de `>=1.20` a `>=2.0`, scipy de `>=1.7` a `>=1.12`, matplotlib de `>=3.4` a
`>=3.8`. Ni un `==` ni un techo `<` en juego. jax-CUDA, cupy y z3 conviven en el
mismo proceso, verificado. Separar entornos añadiría mantenimiento sin resolver
ningún problema real.

## Variables que el env fija por sí solo

`TELAR_PYWARPFACTORY` → `~/pkgs/warp/pyWarpFactory_push`
(en `envs/pkgs/etc/conda/activate.d/telar.sh`; sin ella TELAR da 178/193 porque su
default apunta a una ruta de Windows).
