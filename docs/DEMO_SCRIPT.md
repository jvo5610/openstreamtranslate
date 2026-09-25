# Guion de demo — 90 segundos

Objetivo: mostrar valor para la audiencia, calidad técnica y escalabilidad sin
convertir el video en una explicación de código.

## Preparación

- ejecutar `make smoke` y confirmar `/api/health` en verde;
- abrir `/studio` y `/` en dos ventanas;
- usar `samples/nerdearla-kubernetes-es.mp4` para ES→EN;
- dejar cargados `CloudNativePG`, `Kubernetes` y `PostgreSQL` en el glosario;
- tener a mano `acceptance/latest-results/concurrency.json` y
  `acceptance/latest-results/sse-1000.json`;
- grabar a 1080p y añadir subtítulos ingleses generados por el propio proyecto.

## Toma sugerida

**0–10 s — problema.** “Más de 30 sesiones en inglés, muchas simultáneas. Las
soluciones comerciales escalan en costo y operación.” Mostrar la audiencia.

**10–30 s — experiencia final.** Iniciar el video español desde Studio. Cambiar
a la vista pública y mostrar captions ingleses dentro del reproductor. Abrir el
menú CC, ocultarlos y volver a inglés. Mutear y desmutear.

**30–45 s — calidad.** Mostrar brevemente el glosario y señalar que reconoce
`CloudNativePG` y `Kubernetes`. No detener el stream.

**45–60 s — conectable.** Mostrar el overlay `/embed/main-stage?lang=en` y
explicar que OBS/vMix lo consumen como Browser Source. Descargar el SRT desde
Studio.

**60–77 s — escala demostrada.** Superponer tres números: 10 sesiones, primera
leyenda máxima 2,72 s; 1.000 viewers, p95 133,1 ms; WER 3,70 %. Explicar que la
GPU trabaja por escenario y SSE distribuye el mismo evento a la audiencia.

**77–90 s — cierre.** Mostrar el diagrama y cerrar con: “Open source, sin API
comercial, desplegable por cualquier conferencia y listo para evolucionar a un
pool GPU con KubeRay.”

## Checklist antes de publicar

- duración entre 1:00 y 2:00;
- audio real de una charla;
- interacción visible, no sólo slides;
- enlace público o no listado en YouTube;
- subtítulos ingleses revisados;
- URL copiada en `SUBMISSION.md` y en Devpost.
