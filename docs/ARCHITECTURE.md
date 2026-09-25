# Arquitectura orientada a streaming

![Flujo desplegable](diagrams/architecture.png)

## Decisión

La solución separa el transporte de la señal, la inferencia por escenario y la
distribución a la audiencia. El recurso costoso es cada escenario activo; un
nuevo espectador no debe volver a ejecutar ASR ni traducción.

| Tramo | Opción elegida | Motivo |
|---|---|---|
| Fuente de navegador | WebSocket binario | Necesita enviar audio de baja latencia |
| Fuente de producción | SRT/RTMP hacia un media ingress | Protocolos soportados por OBS/vMix |
| Simulación | FFmpeg `-re` server-side | Conserva el ritmo temporal de una señal real |
| Estado e historial corto | Redis Streams | Orden, IDs, replay acotado y operación simple |
| Fan-out entre réplicas | Redis Pub/Sub | Una suscripción por sesión/réplica recibe el caption |
| Fan-out dentro de réplica | Colas `asyncio` acotadas | Miles de viewers no multiplican conexiones Redis |
| Audiencia | SSE | Flujo unidireccional, reconexión y `Last-Event-ID` |
| Video de producción | Media server/CDN | Los gateways de captions no deben transportar video |

## Escenarios revisados

### Un escenario, pocos espectadores

Una réplica de aplicación y una GPU alcanzan. Redis sigue siendo útil porque
permite demostrar reconexión y mantiene el diseño compatible con varias
réplicas.

### Cinco a diez escenarios simultáneos

Cada fuente tiene un `session_id`, buffer, contexto y secuencia independiente.
Los pedidos de ASR/traducción se distribuyen sobre el pool GPU. La batería de
aceptación envía audio a 2, 5 y 10 fuentes en paralelo y exige captions en menos
de cinco segundos.

### Muchos espectadores en una misma charla

El caption se produce una vez, se publica una vez y se entrega a todos los
gateways interesados. Los clientes usan SSE y reciben original y traducción en
el mismo evento. Cambiar el selector es una operación local del navegador.

Cada réplica abre una sola suscripción Pub/Sub por sesión activa y distribuye el
evento a colas locales acotadas. Un cliente lento pierde primero el caption más
viejo de su cola, sin frenar al stream ni al resto de la audiencia.

### Corte y reconexión

Redis Streams asigna un ID a cada caption. EventSource reconecta y envía
`Last-Event-ID`; el gateway reproduce los eventos posteriores antes de continuar
con Pub/Sub. Los captions quedan limitados a los últimos 2.000 eventos por
sesión para controlar memoria.

### Archivo final y auditoría

Los eventos finales del stream generan SRT/VTT/texto mediante
`GET /api/sessions/{id}/transcript/{format}?language=...`. Si en el futuro
se necesita retención multi-evento, reprocessing, data lake o varios equipos
consumidores, se agrega Kafka para los eventos finales, no para cada frame PCM.

## Kubernetes y KubeRay

El primer despliegue Kubernetes debe mantener unidades independientes:

- `caption-gateway`: FastAPI/SSE, CPU, réplicas horizontales.
- `redis`: servicio administrado o StatefulSet con persistencia.
- `asr-workers`: GPU, réplicas calientes dimensionadas por escenarios activos.
- `translation-workers`: GPU, batching y réplica independiente.
- `media-ingress`: SRT/RTMP/HLS/WebRTC fuera del camino de inferencia.

KubeRay/Ray Serve conviene cuando el evento opera varias GPU o tipos de
acelerador y necesita scheduling, colas y autoscaling coordinado. No reemplaza
al media ingress, al registro de sesiones ni al fan-out SSE. Para el MVP, los
servicios HTTP de inferencia existentes reducen riesgo y ya demostraron diez
sesiones concurrentes sobre una RTX 3090.

## Gates de producción

- Latencia p95 desde audio hasta caption SSE.
- Aislamiento: ningún caption puede aparecer en otra sesión.
- Una sola inferencia por evento aunque aumenten los espectadores.
- Backpressure por escenario y límite de memoria del buffer.
- Reconexión SSE sin perder captions confirmados.
- Health checks separados para broker, ASR y traducción.
- Capacidad GPU precalentada para el máximo de escenarios simultáneos.
- Autenticación y límites de carga en WebSocket, simulador e inyección externa.

## Resultados de fan-out local

El gate publica un único caption sintético y comprueba que todos los clientes
reciban exactamente el mismo `event_id`:

| Réplica FastAPI | Viewers | Entregados | p95 | p99 |
|---:|---:|---:|---:|---:|
| 1 | 1.000 | 1.000 | 135 ms | 138 ms |
| 1 | 5.000 | 5.000 | 1.169 ms | 1.183 ms |

La cola de un solo proceso se vuelve visible en 5.000 conexiones. El punto de
partida recomendado es un HPA de gateways con unas 1.000 conexiones SSE por
réplica, manteniendo GPU workers separados. La prueba debe repetirse en el
cluster real porque ingress, límites de archivos y red cambian el resultado.
