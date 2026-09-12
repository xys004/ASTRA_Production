# Política de publicación — ASTRA

**Congelada:** 2026-07-31 · **Decidida por:** Nelson · **Ámbito:** todo manuscrito
destinado a revista, preprint o conferencia que use resultados producidos con ASTRA.

**Cuándo aplica:** solo al redactar artículos. No cambia nada del ciclo de ASTRA ni
de los informes internos del día a día.

---

## 1. Las auditorías internas NO se citan en artículos

Prohibido en el texto de un manuscrito:

- identificadores de ciclo (`cycle_<hash>`, `job_<id>`, `cache_key`);
- el vocabulario de veredicto interno: **VALIDATED / REFUTED / WEAK_PASS /
  CODE_ERROR** — son estados de una máquina de estados privada, no afirmaciones
  científicas;
- corridas de benchmark internas, `verdict_guard`, historiales de parche,
  `quality_escalations`, escaleras de modelo;
- ASTRA como autoridad: **nunca** "ASTRA validó que…", "el oráculo confirmó…".

### Por qué

Citar una auditoría interna es citar algo **no publicado, no revisable y
autorreferencial**. Un referee no puede comprobar `cycle cd145e8d → VALIDATED`: no
tiene el código, ni el modelo, ni el entorno. Parece evidencia y no lo es — es una
apelación a una autoridad privada, y un lector exigente lo leerá como inflar el rigor.

La regla **no** es ocultar las auditorías. Es convertirlas en algo que el referee
pueda re-ejecutar. Eso es estrictamente más fuerte, no más débil: cambias "confía en
mi verificador" por "aquí está, córrelo tú".

## 2. Lo que SÍ viaja al artículo

El **contenido** de la verificación, no su etiqueta: la derivación, las hipótesis, los
checks concretos, las cifras, los límites de validez y las condiciones bajo las que
falla. Todo ello redactado como física, no como salida de herramienta.

Si se menciona el instrumental, va en Métodos o Agradecimientos como software
empleado, con versión (`SymPy 1.14`, `Lean 4.30.0 + mathlib4`, `Z3 4.16`), igual que
se cita cualquier biblioteca. Nunca como aval del resultado.

## 3. El código se extrae y viaja aparte

Todo manuscrito lleva un **artefacto reproducible separado** (material suplementario
/ repositorio con DOI). Requisitos para que cuente como tal:

1. **Independiente**: cero imports de ASTRA, cero rutas locales, cero configuración de
   clúster. Se ejecuta en una máquina limpia.
2. **Autocontenido**: dependencias fijadas con versión; semillas deterministas.
3. **Fiel**: produce **las cifras que aparecen en el artículo**, no unas parecidas.
   Cada número del texto debe poder señalarse a la salida que lo genera.
4. **Auto-refutable**: conserva las patas `CHECK` como aserciones ejecutables, de modo
   que el referee vea fallar el script si la afirmación es falsa. Esto es lo mejor que
   el arnés interno de ASTRA aporta a la ciencia pública — traducido a algo que no
   depende de ASTRA.
5. **Documentado**: un README con cómo correrlo, cuánto tarda y qué debe imprimir.

Coherente con [[feedback_cifras_solo_desde_outputs]]: ninguna cifra entra al artículo
sin un log depositado que la respalde.

## 4. Informes de empresa: régimen distinto

En informes internos de Astrum, las auditorías **sí** pueden citarse — identificadores
de ciclo, veredictos, escaleras, coste. Ahí el lector tiene acceso al sistema y la
trazabilidad es el objetivo.

Condición: **solo cuando Nelson lo pida explícitamente**. Por defecto, incluso un
informe interno se redacta sin volcado de auditoría.

## 5. Regla de decisión rápida

> ¿Puede un referee sin acceso a nuestra infraestructura comprobar esta frase?
>
> **Sí** → puede ir en el artículo.
> **No** → o se convierte en artefacto ejecutable, o se elimina.
