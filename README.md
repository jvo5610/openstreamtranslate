# Vibeathon Live Captions

Subtítulos bilingües de baja latencia para conferencias: una inferencia por
escenario, distribución a miles de espectadores y operación reproducible con
software abierto.

**Repositorio público:** <https://github.com/jvo5610/vibeathon-live-captions>

> **English summary:** Vibeathon Live Captions turns live English or Spanish
> audio into original-language and translated captions. A GPU pipeline runs
> faster-whisper `large-v3-turbo` plus TranslateGemma 4B; FastAPI and Redis
> distribute each caption once to every viewer through reconnectable SSE. The
> repository includes real conference samples, a public player, an operator
> studio, OBS/vMix overlay, technical glossaries, SRT/VTT/TXT export,
> Prometheus metrics and repeatable quality/load gates.

## Por qué existe

Nerdearla necesita transcribir más de 30 charlas, varias en simultáneo. Las
soluciones comerciales actuales son costosas, requieren operación manual y
escalan por espectador. Este proyecto cambia esa unidad económica: **la GPU
trabaja una vez por escenario activo** y el caption resultante se reparte a
todos los espectadores sin reinferencia.

La solución cubre el MVP y cuatro opcionales de la
[Nerdearla Vibeathon 2026](https://nerdearla26.devpost.com/):

- audio real desde micrófono, archivo o adaptador de stream;
- transcripción original y traducción EN ↔ ES en vivo;
- 2, 5 y 10 sesiones simultáneas verificadas;
- selector de escenario e idioma dentro del reproductor;
- overlay transparente para OBS/vMix;
- glosario técnico por sesión y dirección;
- exportación final SRT, VTT y texto;
- métricas Prometheus, health checks y logs estructurados.

## Evidencia rápida

Los resultados versionados en [`acceptance/latest-results`](acceptance/latest-results/)
provienen de la batería incluida en este repositorio, ejecutada contra una RTX
3090:

| Dimensión del jurado | Resultado medido |
|---|---|
| Calidad ASR inglesa | WER **3,70 %** / exactitud 96,30 % contra subtítulos humanos |
| 10 sesiones en paralelo | primera leyenda p50 **2,62 s**, máximo **2,72 s** |
| 2 streams bilingües + 20 viewers | 20/20 clientes, aislamiento correcto |
| 100 viewers en una charla | p95 de fan-out **24,75 ms**, una sola inferencia |
| 1.000 viewers en una réplica | p95 **133,1 ms**, mismo `event_id` para todos |
| Experiencia visual | atraso observado 0,1–2,4 s; cola pico de un bloque |

Son mediciones de laboratorio, no una promesa del cluster de producción. Los
gates pueden repetirse con `make acceptance` y `make stress`.

## Arquitectura

![Arquitectura de Vibeathon Live Captions](docs/diagrams/architecture.png)

1. Studio, OBS o el media ingress envían PCM mono de 16 kHz por WebSocket.
2. `faster-whisper` reconoce el idioma original usando contexto y *hotwords*.
3. TranslateGemma produce el caption destino aplicando el glosario de la charla.
4. Redis Streams conserva el historial corto; Pub/Sub lo comparte entre réplicas.
5. Cada réplica mantiene una suscripción Redis por sesión y distribuye
   localmente por SSE, con replay mediante `Last-Event-ID`.
6. El navegador superpone los subtítulos sobre el video; cambiar idioma es
   local y no vuelve a invocar los modelos.

La fuente editable del diagrama está en
[`docs/diagrams/architecture.py`](docs/diagrams/architecture.py). Para regenerar
el PNG se necesita Graphviz:

```bash
uv run --with diagrams python docs/diagrams/architecture.py
```

Las decisiones de WebSocket vs. SSE, Redis vs. Kafka y la evolución a
Kubernetes/KubeRay están en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Componentes

| Componente | Implementación | Responsabilidad |
|---|---|---|
| ASR | `faster-whisper` + `large-v3-turbo`, FP16 | Reconocimiento ES/EN, VAD y hotwords |
| Traducción | TranslateGemma 4B IT Q8_0 + `llama.cpp` | Traducción concisa EN ↔ ES y glosario |
| API | FastAPI | WebSocket de entrada, SSE, sesiones y exportación |
| Broker | Redis 7 | Streams, Pub/Sub, replay y glosarios |
| Media | FFmpeg | Normalización y simulación a reloj real con `-re` |
| Front | HTML/CSS/JS sin framework | Player público, Studio y overlay OBS |

El código no requiere claves de Gemini, OpenAI ni OpenRouter. Los pesos de los
modelos no se redistribuyen; cada operador debe aceptar y respetar sus licencias.

## Inicio rápido

### Requisitos

- Docker Desktop o Docker Engine con Compose v2;
- `make`, `curl`, `jq`, SSH y FFmpeg;
- un host Linux con GPU NVIDIA y acceso SSH;
- aproximadamente 8 GB de VRAM libres para la configuración actual; se
  recomienda una GPU de 16–24 GB para concurrencia y margen operativo;
- `large-v3-turbo`, TranslateGemma 4B GGUF y `llama-server` preparados según
  [`docs/GPU_SETUP.md`](docs/GPU_SETUP.md).

### 1. Configurar el host GPU

No hay hostnames personales en el repositorio. Indicá tu servidor y, si no es
22, su puerto SSH:

```bash
export REMOTE_HOST=user@gpu-host
export REMOTE_SSH_PORT=22
export REMOTE_ROOT=vibeathon-benchmark
```

Sincronizá el servicio y encendé los modelos:

```bash
make remote-sync
make remote-start
```

### 2. Abrir el túnel privado

En otra terminal:

```bash
export REMOTE_HOST=user@gpu-host
export REMOTE_SSH_PORT=22
make tunnel
```

Los modelos escuchan sólo en `127.0.0.1` del host GPU. El túnel publica
temporalmente `localhost:18080` (traducción) y `localhost:18081` (ASR); no hace
falta exponer esos puertos a Internet.

### 3. Iniciar aplicación y Redis

```bash
docker compose up --build -d
make smoke
```

El smoke test usa `samples/ibm-future-computing-360p.webm`, incluido en el repo;
no depende de archivos privados ni rutas externas.

Abrí:

- audiencia: <http://localhost:8080/>;
- operación: <http://localhost:8080/studio>;
- salud: <http://localhost:8080/api/health>;
- métricas: <http://localhost:8080/metrics>.

Para apagar:

```bash
docker compose down
make remote-stop
```

### Servicios de inferencia ya existentes

Si ASR y traducción ya están desplegados, no se necesitan los scripts SSH.
Copiá `.env.example` a `.env`, cambiá `ASR_URL` y `TRANSLATION_URL`, y ejecutá
solamente `docker compose up --build -d`.

## Cómo probar la demo

1. Entrá a <http://localhost:8080/studio>.
2. Elegí **Main Stage** y la dirección EN→ES o ES→EN.
3. Abrí **Glosario técnico** y agregá términos si la charla lo requiere.
4. Presioná **Simular con video** y elegí uno de los archivos de `samples/`.
5. Abrí <http://localhost:8080/>: el video y los captions se sincronizan en el
   mismo reproductor. El menú **CC** cambia idioma u oculta subtítulos.
6. Al terminar, desplegá **Exportar transcripción** en Studio para descargar
   SRT, VTT o texto.

También se puede usar **Usar micrófono**. El navegador pedirá permiso sólo para
esa fuente local.

## Glosario técnico

El glosario se guarda en Redis por sesión y dirección. Una línea simple sesga
el reconocimiento y preserva la grafía:

```text
Kubernetes
CloudNativePG
KubeRay
```

Una equivalencia agrega además una regla exacta de traducción:

```text
base de datos = database
aprendizaje automático = machine learning
```

Los glosarios ES→EN y EN→ES son independientes porque una traducción inversa
no siempre es simétrica. Se aceptan hasta 100 entradas. Los cambios se aplican
al próximo stream para que una charla activa mantenga reglas consistentes.

API equivalente:

```text
GET /api/sessions/{id}/glossary?source_language=es&target_language=en
PUT /api/sessions/{id}/glossary
```

## Integración con streaming

El front demuestra el recurso, pero no es una dependencia del pipeline:

| Uso | Endpoint |
|---|---|
| Ingresar PCM mono 16 kHz | `WS /api/sessions/{id}/input?source=en&target=es` |
| Inyectar captions externos | `POST /api/sessions/{id}/captions` |
| Consumir captions/replay | `GET /api/sessions/{id}/events` |
| Overlay transparente | `/embed/{id}?lang=es` o `?lang=en` |
| Exportar transcripción | `/api/sessions/{id}/transcript/{srt\|vtt\|txt}?language=es` |

Ejemplo de caption externo:

```bash
curl -X POST http://localhost:8080/api/sessions/main-stage/captions \
  -H 'content-type: application/json' \
  -d '{
    "original":"We are live from Nerdearla.",
    "translation":"Estamos en vivo desde Nerdearla.",
    "source_language":"en",
    "target_language":"es",
    "sequence":1,
    "final":true,
    "audio_start_seconds":0,
    "audio_end_seconds":2.5
  }'
```

En OBS o vMix agregá `/embed/main-stage?lang=es` como Browser Source/Fuente de
navegador. En producción, el media server o CDN transporta el video; este
servicio procesa sólo audio y captions.

## Comportamiento en vivo

Por defecto se calcula una hipótesis cada 1,5 s, se intenta confirmar a los 3 s,
se fuerza el cierre a 4,5 s y se conservan 750 ms de contexto. La UI:

- estabiliza hipótesis parciales en lugar de apilar texto;
- limita el subtítulo a dos líneas y aproximadamente 20 caracteres por segundo;
- conserva bloques confirmados entre 1,8 y 3,2 s;
- usa el video como reloj maestro y acelera suavemente si el atraso supera 1,3 s;
- descarta parciales obsoletos antes de permitir que crezca una cola ilegible.

Estos parámetros pueden cambiarse en `.env`; sus valores y significado están
documentados en [`.env.example`](.env.example).

## Escalabilidad

La capacidad GPU escala por **escenarios activos**, no por espectadores:

- FastAPI es stateless respecto de captions y puede replicarse detrás de un
  ingress; Redis comparte sesiones e historial.
- Cada réplica abre una sola suscripción Pub/Sub por sesión y hace fan-out a
  colas locales acotadas.
- Los gateways SSE escalan en CPU independientemente de ASR y traducción.
- Los workers GPU se precalientan para el máximo de escenarios; el autoscaling
  reactivo suele llegar tarde por el tiempo de carga de modelos.
- KubeRay/Ray Serve es una evolución útil para varias GPU, colas y tipos de
  acelerador. Kafka sólo se agrega si se necesita retención larga, analítica o
  consumidores externos; no está en el camino crítico del caption.

El punto de partida recomendado es unas 1.000 conexiones SSE por réplica y un
pool GPU dimensionado por charlas simultáneas. Repetí `make stress` detrás del
ingress real antes de fijar capacidad de producción.

## Configuración

| Variable | Default | Uso |
|---|---|---|
| `ASR_URL` | `http://host.docker.internal:18081` | Servicio faster-whisper |
| `TRANSLATION_URL` | `http://host.docker.internal:18080` | Servicio llama.cpp |
| `SOURCE_LANGUAGE` | `en` | Idioma fuente predeterminado |
| `TARGET_LANGUAGE` | `es` | Idioma destino predeterminado |
| `LIVE_UPDATE_SECONDS` | `1.5` | Frecuencia de parciales |
| `LIVE_FINAL_SECONDS` | `3` | Objetivo de bloque confirmado |
| `LIVE_MAX_FINAL_SECONDS` | `4.5` | Cierre forzado |
| `LIVE_OVERLAP_SECONDS` | `0.75` | Contexto acústico solapado |
| `REDIS_URL` | `redis://redis:6379/0` | Broker compartido |
| `SIMULATOR_START_DELAY_SECONDS` | `2` | Margen para sincronizar reproductores |

## Observabilidad

- `/api/health`: Redis, ASR y traducción por separado.
- `/metrics`: streams, SSE activos, captions, latencia de modelos, atraso del
  caption, tiempo de publicación al broker y parciales descartados.
- `docker compose logs app`: JSON por sesión, idioma, secuencia, latencia,
  atraso y cantidad de términos del glosario.

Las métricas no aparecen en la vista pública; están destinadas a Prometheus y
al equipo de producción.

## Verificación

```bash
make smoke       # salud + un archivo real
make acceptance  # requisitos, WER, concurrencia, fan-out y opcionales
make stress      # 100, 1.000 y 5.000 espectadores SSE
```

`make acceptance` valida Compose, UI, glosario, exportación, audio real,
latencia, WER ≤ 8 %, 2/5/10 fuentes, dos idiomas simultáneos, 100/1.000 viewers
y replay SSE. Los resultados quedan en `acceptance/latest-results/`.

La trazabilidad completa requisito → prueba → estado está en
[`acceptance/CRITERIA.md`](acceptance/CRITERIA.md). Los únicos pasos que no puede
resolver una batería local son publicar el repositorio, subir el video de 1–2
minutos y enviar el formulario de Devpost.

## Estructura del repositorio

```text
app/                    FastAPI y front público/Studio/overlay
remote/                 servicios GPU de ASR y traducción
samples/                dos videos y referencias de calidad
scripts/                smoke, aceptación, carga y operación SSH
acceptance/              matriz oficial y resultados medidos
benchmarks/              comparación de modelos ASR
docs/                    arquitectura, setup GPU y guion de demo
compose.yaml             app + Redis
```

## Limitaciones conocidas

- No hay alineación por palabra; los timestamps son por bloque.
- La muestra española posee subtítulos automáticos de origen, por lo que su WER
  sólo puede usarse como orientación. El gate estricto usa referencia humana
  inglesa.
- El simulador sirve video desde el contenedor sólo para la demo. Producción
  debe usar media server/CDN y enviar una derivación de audio al WebSocket.
- El prototipo soporta EN y ES. Agregar portugués requiere validar ASR,
  traducción, velocidad de lectura y referencias humanas antes de declararlo.

## Licencia y atribuciones

El código es [MIT](LICENSE), una licencia aprobada por la OSI. Los medios de
prueba y sus fuentes están documentados en [`samples/README.md`](samples/README.md).
Whisper, TranslateGemma, llama.cpp y los pesos conservan sus licencias y términos
propios; no forman parte de la licencia MIT de este repositorio.
