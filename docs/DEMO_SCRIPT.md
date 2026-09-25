# Guion de demo — 90 segundos

Mi objetivo es mostrar la experiencia de la audiencia, la calidad técnica y la
capacidad de integración sin convertir el video en una explicación de código.

## Preparación

- Ejecuto `make smoke`, `make quality` y `make acceptance`.
- Confirmo que `/api/health` informa ASR, traducción y Redis disponibles.
- Inicio el laboratorio de streaming y abro `http://localhost:8090`.
- Dejo disponibles las señales Nerdearla ES→EN e IBM Research EN→ES.
- Cargo `CloudNativePG`, `Kubernetes` y `PostgreSQL` en el glosario.
- Preparo `acceptance/latest-results/quality-matrix.json` y
  `acceptance/latest-results/sse-1000.json` para mostrar evidencia.
- Grabo a 1080p y reviso manualmente los subtítulos finales del video.

## Toma sugerida

**0–10 s — problema.** Explico: “Una conferencia con más de 30 sesiones necesita
subtítulos precisos, de baja latencia y con un costo que no crezca por cada
espectador”. Muestro el reproductor público.

**10–32 s — experiencia en ambos idiomas.** Inicio con Nerdearla en español y
muestro la traducción inglesa dentro del video. Abro CC, cambio al idioma
original y oculto el texto. Luego cambio a IBM Research y muestro la traducción
española. Activo y desactivo el audio para demostrar que el video es real.

**32–45 s — sincronización.** Pauso la transmisión. Señalo que video y caption
quedan congelados. Reanudo y muestro que ambos regresan juntos al punto en vivo,
sin reproducir una cola de subtítulos anteriores.

**45–58 s — integración.** Muestro el flujo OBS/vMix → RTMP/SRT → MediaMTX →
FFmpeg → WebSocket y explico que la aplicación recibe sólo audio. Muestro el
overlay `/embed/main-stage?lang=en` como Browser Source y menciono que también
puedo descargar SRT o VTT.

**58–78 s — evidencia.** Presento cuatro números: WER inglés 3,70 %; traducción
EN→ES chrF 0,6873; 10 sesiones con primera leyenda máxima de 3,51 s; y 1.000
espectadores con p95 de fan-out de 173,07 ms. Aclaro que la GPU trabaja una vez
por escenario, no una vez por espectador.

**78–90 s — cierre.** Muestro el diagrama y cierro: “Construí una solución
abierta, reproducible y conectable a una cadena de streaming real. Separa media,
inferencia y distribución para poder escalar cada parte con el recurso que
necesita”.

## Checklist antes de publicar

- Duración entre 1:00 y 2:00.
- Audio real de una charla, no sólo diapositivas.
- Interacción visible con selector CC, cambio de señal, audio y pausa.
- Una captura breve de resultados reproducibles.
- Enlace público o no listado en YouTube.
- Subtítulos ingleses revisados.
- URL agregada a `SUBMISSION.md` y al formulario de Devpost.
