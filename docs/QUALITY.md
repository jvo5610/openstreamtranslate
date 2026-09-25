# Cómo valido la calidad

No considero suficiente mostrar que aparece texto. Para evaluar el proyecto
separo reconocimiento, traducción, latencia, experiencia de lectura,
sincronización y distribución. Cada dimensión puede fallar sin que las demás lo
hagan, por eso conservo resultados individuales y un gate consolidado.

## Material que elegí

### Inglés → español

Uso `samples/ibm-future-computing-360p.webm`, una pieza de IBM Research de 70,6
segundos con subtítulos ingleses humanos publicados en Wikimedia. Comparo:

- la transcripción inglesa contra `ibm-future-computing.en.srt`;
- la traducción española contra `ibm-future-computing.es.srt`;
- el tiempo total contra la duración real del audio.

### Español → inglés

Uso los primeros 30 segundos de `samples/nerdearla-kubernetes-es.mp4`. La
referencia española proviene de captions automáticos de origen, por lo que no la
presento como ground truth humano. Su WER sirve para detectar regresiones grandes,
no para comparar modelos con precisión académica. También exijo una traducción
inglesa no vacía y mido el factor de tiempo real.

## Métricas y gates

| Dimensión | Gate | Motivo |
|---|---:|---|
| ASR inglés | WER ≤ 8 % | Referencia humana; gate estricto |
| Traducción EN→ES | chrF ≥ 0,60 | Tolera variantes válidas mejor que WER |
| Traducción EN→ES | F1 léxico ≥ 0,65 | Detecta omisiones y expansiones excesivas |
| ASR español | WER ≤ 30 % | Gate orientativo por la calidad de la referencia |
| Procesamiento por lotes | RTF ≤ 0,12 | Al menos 8,3 veces más rápido que tiempo real |
| Vivo bilingüe | primera leyenda ≤ 5 s | Límite de experiencia de usuario |
| Fan-out | mismo `event_id` | Verifica una inferencia compartida por espectadores |

No uso el tiempo total de un archivo largo como sustituto de la latencia del
directo. Un archivo de 70 segundos puede tardar más de cinco segundos bajo carga
y aun procesarse mucho más rápido que tiempo real. Para la experiencia en vivo
mido por separado la primera leyenda y `caption_lag`.

Calculo chrF como F2 sobre la precisión y el recall medios de n-gramas de
caracteres de orden 1 a 6, sin contar espacios. El F1 léxico usa tokens
normalizados. Son indicadores repetibles de regresión; antes de producción los
complementaría con una revisión humana bilingüe de adecuación y fluidez.

## Última ejecución

Ejecuté `make quality` con las dos señales permanentes del laboratorio activas:

| Caso | Resultado |
|---|---:|
| WER inglés | **3,70 %** |
| Exactitud inglesa | **96,30 %** |
| chrF EN→ES | **0,6873** |
| F1 léxico EN→ES | **0,7208** |
| WER español orientativo | **22,22 %** |
| RTF EN→ES / ES→EN | **0,0703 / 0,0804** |
| Primera leyenda EN→ES | **1,920 s** |
| Primera leyenda ES→EN | **2,062 s** |
| Entrega SSE p95 | **2,31 ms / 3,67 ms** |
| Resultado consolidado | **PASS** |

El informe reproducible queda en
`acceptance/latest-results/quality-matrix.json`. Los resultados pueden variar
por carga de GPU, temperatura y procesos concurrentes; por eso versiono cada
corrida en lugar de presentar una cifra aislada.

## Pausa y resincronización

Además de las métricas automáticas, probé el contrato del player con un directo
real del laboratorio:

1. pausé el video y el overlay;
2. esperé cuatro segundos mientras el backend siguió produciendo captions;
3. comprobé que el tiempo del video y el texto visible permanecieron idénticos;
4. reanudé y verifiqué que ambos saltaron al punto en vivo;
5. confirmé que la cola acumulada no se reprodujo sobre imágenes actuales.

En la ejecución registrada, el video quedó fijo en `21,576551 s` y al reanudar
saltó a `47,743764 s`. El estado del overlay cambió de `paused` a `live` y el
texto se actualizó únicamente después de la resincronización.

## Cómo repetirlo

```bash
docker compose up --build -d
make quality
make acceptance
make stress
```

Para una decisión de producción repetiría estas pruebas detrás del ingress real,
con la misma GPU, resolución, número de escenarios y mezcla de idiomas prevista
para el evento.
