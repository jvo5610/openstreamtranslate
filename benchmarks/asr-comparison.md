# Comparación ASR en RTX 3090

Fecha: 2026-09-25. Audio: `samples/ibm-future-computing-360p.webm`,
70,6 segundos de inglés técnico. Referencia: 162 palabras de los subtítulos
humanos publicados con el video.

## Resultados

| Modelo | Modalidad probada | WER | Exactitud | Tiempo para 70,6 s | VRAM aproximada |
|---|---|---:|---:|---:|---:|
| Canary-Qwen 2.5B | 2 bloques de menos de 40 s | **0,62%** | **99,38%** | 5,04 s | 10,0 GB |
| Whisper large-v3 | archivo completo | 1,23% | 98,77% | 3,15 s | ~3 GB |
| Nemotron 3.5, 1120 ms | streaming cache-aware | 3,09% | 96,91% | 3,01 s de cómputo | 1,25 GB |
| Nemotron 3.5, 320 ms | streaming cache-aware | 3,70% | 96,30% | 7,01 s de cómputo | 1,25 GB |
| Whisper large-v3-turbo | archivo completo | 4,32% | 95,68% | 1,11 s | 3,55 GB del servicio |
| Parakeet TDT 0.6B V3 | archivo completo | 6,79% | 93,21% | **0,42 s** | 1,43 GB |

Los tiempos son mediciones calientes, después de cargar y compilar el modelo.
El tiempo de cómputo de Nemotron no incluye esperar a que el hablante produzca
el audio; su latencia acústica configurada es 320 o 1120 ms respectivamente.

## Latencia con un bloque de 6 segundos

| Modelo | Inferencia caliente | Observación |
|---|---:|---|
| Parakeet V3 | **0,062 s** | Muy veloz, pero espera el bloque y perdió una oración en el audio completo. |
| Whisper large-v3-turbo | 0,202 s promedio | La aplicación vuelve a procesar ventanas solapadas. |
| Whisper large-v3 | 0,427 s promedio | Más preciso, sin streaming nativo persistente. |
| Canary-Qwen 2.5B | 0,592 s promedio | Máxima precisión, alto uso de VRAM y sin parciales nativos. |
| Nemotron 3.5 | 320 ms de latencia acústica | Procesa sólo audio nuevo y conserva el estado del encoder. |

## Decisión

En esta muestra **inglesa**, el mejor equilibrio puramente acústico es Nemotron
3.5 ASR Streaming 0.6B con 320 ms de lookahead: mejora la exactitud de
`large-v3-turbo`, usa menos VRAM y evita recalcular ventanas solapadas.

Para una segunda pasada o corrección final, **Canary-Qwen 2.5B** fue claramente
el más preciso. Una arquitectura híbrida razonable sería Nemotron para los
parciales y Canary para consolidar bloques terminados, siempre que se acepte el
uso adicional de aproximadamente 10 GB de VRAM.

El producto utiliza **Whisper `large-v3-turbo`** porque el gate final exige un
único camino bilingüe ES/EN, hotwords por charla y una integración estable ya
validada en ambos sentidos. No sería responsable promover Nemotron a producción
basándose sólo en la referencia inglesa. Queda como candidato a worker EN
especializado cuando exista una referencia humana española equivalente.

Parakeet no se recomienda para este video: fue el más rápido, pero omitió una
oración completa. Whisper `large-v3` es la alternativa conservadora si se
acepta mayor latencia a cambio de precisión de archivo.
