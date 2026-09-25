# Criterios de aceptación — Nerdearla Vibeathon 2026

Fuentes revisadas el 25/09/2026:

- [Overview y requirements](https://nerdearla26.devpost.com/)
- [Rules](https://nerdearla26.devpost.com/rules)

Las reglas también establecen que el código debe ser Open Source, que Nerdearla
puede usar, adaptar, forkear y desplegar la solución respetando su licencia, y
que sólo pueden participar personas registradas en Nerdearla antes del cierre.

## Bloqueantes de elegibilidad y entrega

| Criterio | Cómo se comprueba | Estado actual |
|---|---|---|
| Construido durante el 24–25/09/2026 | Fecha del root commit `34dbde4` | PASS — 25/09/2026 |
| Video demo de 1–2 min | Enlace YouTube en `SUBMISSION.md`; debe mostrar audio real y explicar uso | FAIL — falta grabarlo y enlazarlo |
| Repositorio público | Repositorio Git con remoto público | PASS — `github.com/jvo5610/openstreamtranslate` |
| Licencia OSI | Archivo `LICENSE` | PASS — MIT |
| README: puesta en marcha y modelos/credenciales | Inspección automática del README | PASS |
| README: cómo escalar a más sesiones | Inspección automática del README | PASS |
| Participantes registrados en Nerdearla antes del cierre | Verificación de cuenta/registro | MANUAL |
| Envío antes del 25/09/2026 15:00 UTC (12:00 ART) | Confirmación en Devpost | MANUAL — no puede automatizarse localmente |

## MVP obligatorio

| Criterio | Check automático | Umbral | Estado actual |
|---|---|---|---|
| Recibir audio en vivo | WebSocket PCM, micrófono, simulador y bridge RTMP/SRT/HLS | Entrada real y reproducible | PASS |
| Incluir audio de prueba fácil de importar | Archivo de muestra versionable | Archivo no vacío | PASS |
| Transcripción original en tiempo real | WebSocket entrega captions originales | Texto no vacío y cierre correcto | PASS |
| Traducción inglés → español en tiempo real | WebSocket entrega traducción | Texto no vacío y cierre correcto | PASS |
| Mostrar subtítulos | Vista pública con captions dentro del video y menú CC | Máximo dos líneas; scheduler adaptativo; sin acumulación | PASS — traza 0,1–2,4 s; cola pico 1 |
| Pausar y reanudar el directo | Control coordinado entre reproductor y overlay | Texto congelado al pausar; retorno conjunto al borde en vivo | PASS — ver `docs/QUALITY.md` |
| Streaming español → inglés | Dos flujos bilingües simultáneos | Metadatos, textos y sesiones aisladas | PASS |
| Dos sesiones simultáneas | Prueba con audio emitido a ritmo real | Todas reciben ambos textos; primera leyenda ≤ 5 s | PASS |
| Escala adicional | Misma prueba con 5 y 10 sesiones | Todas reciben ambos textos; primera leyenda ≤ 5 s | PASS |

## Pedido general del desafío

Estos puntos aparecen en la descripción del desafío aunque la sección “MVP” no los repita todos.

| Pedido | Estado actual | Observación |
|---|---|---|
| Varias sesiones (5, 10 o más) | PASS | El backend pasó 5 y 10 fuentes concurrentes con aislamiento por `session_id` |
| Página para la audiencia | PASS | `/` reproduce la señal y recibe captions por SSE |
| Elegir sesión | PASS | Catálogo de escenarios y suscripción independiente |
| Elegir idioma de transcripción | PASS | Botón CC dentro del reproductor: Off/Español/English, sin repetir inferencia |
| Despliegue replicable y documentado | PASS MVP | Docker, Redis, health checks y estrategia de escalado documentados |
| Fan-out sin reinferencia | PASS | 1.000 espectadores reciben el mismo evento con p95 173,07 ms; 5.000 con p95 1,316 s |
| Recurso conectable | PASS | WebSocket de audio, API de captions externos, SSE y overlay transparente |

## Criterios de evaluación

| Dimensión | Evidencia de la batería | Estado actual |
|---|---|---|
| Calidad ASR | WER inglés contra subtítulo humano ≤ 8% | PASS — 3,70 %, ver `latest-results/quality-asr-en.json` |
| Calidad de traducción | chrF ≥ 0,60 y F1 léxico ≥ 0,65 | PASS — chrF 0,6873 / F1 0,7208 |
| Rendimiento por idioma | Factor de tiempo real ≤ 0,12 en ambas direcciones | PASS — inglés 0,0703 / español 0,0804 |
| Latencia | Primera leyenda concurrente ≤ 5 s; atraso visual habitual < 2 s y recuperación < 3 s | PASS — visual 0,1–2,4 s; backend p95 0,758 s |
| Escalabilidad | Carga simultánea de 2, 5 y 10 sesiones más fan-out SSE hasta 5.000 viewers | PASS |
| Despliegue y operación | Compose válido, health checks, métricas Prometheus, logs estructurados y README | PASS MVP — recuperación forzada sigue siendo un check manual |
| Innovación | Overlay, glosario, exportación y observabilidad | PASS — 4 de 5 opcionales oficiales implementados |

## Opcionales que suman puntaje

- Integración OBS/vMix u overlay para streaming: implementada en `/embed/{id}?lang=...`.
- Más idiomas, por ejemplo portugués: pendiente.
- Glosario técnico y nombres propios: implementado por sesión y dirección de
  idioma; alimenta `hotwords` de Whisper y reglas de TranslateGemma.
- Exportación SRT/VTT/texto: implementada desde captions confirmados, en ambos idiomas.
- Métricas de monitoreo y logs: implementados fuera del front público.

## Batería repetible

La última batería general terminó en **39 PASS · 1 FAIL · 5 manuales/pendientes**.
La batería de calidad más reciente terminó en **PASS** para ASR inglés, ASR
español orientativo, traducción EN→ES, procesamiento ES→EN, tiempo real y dos
streams simultáneos. La batería general conserva como único bloqueo de entrega
el enlace del video demo. Los controles que dependen de una persona son el
envío en Devpost, el registro de participantes, la revisión de naturalidad, la
demostración de recuperación ante fallos y el opcional de un tercer idioma.

Ejecutar desde la raíz del proyecto:

```bash
make quality
make acceptance
```

La batería de calidad valida ambos idiomas, WER, chrF, F1 léxico, tiempo real y
dos streams concurrentes. La batería de aceptación valida documentación y
empaquetado, salud de ASR/traducción/broker,
UI, un archivo real con referencia humana, latencia, WER, carga concurrente de
2/5/10 sesiones, flujos EN→ES y ES→EN simultáneos y fan-out SSE hasta 1.000
espectadores. `make stress` amplía el fan-out a 5.000. Los artefactos de la
última corrida quedan en `acceptance/latest-results/`.

Los umbrales de 8% WER y 5 segundos no fueron impuestos numéricamente por Devpost: son gates internos, deliberadamente exigentes, para convertir “precisa” y “retraso aceptable” en checks objetivos.
