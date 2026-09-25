# OpenStreamTranslate

Construí un servicio de subtítulos bilingües de baja latencia para conferencias.
Mi objetivo es ejecutar una sola inferencia por escenario, distribuir el
resultado a miles de espectadores y mantener una operación reproducible con
software abierto.

**Repositorio público:** <https://github.com/jvo5610/openstreamtranslate>

> **English summary:** OpenStreamTranslate turns live English or Spanish
> audio into original-language and translated captions. A GPU pipeline runs
> faster-whisper `large-v3-turbo` plus TranslateGemma 4B; FastAPI and Redis
> distribute each caption once to every viewer through reconnectable SSE. The
> repository includes real conference samples, a public player, an operator
> studio, OBS/vMix overlay, technical glossaries, SRT/VTT/TXT export,
> Prometheus metrics and repeatable quality/load gates.

## Por qué existe

Nerdearla necesita transcribir más de 30 charlas, varias en simultáneo. Las
soluciones comerciales actuales son costosas, requieren operación manual y
escalan por espectador. Por eso diseñé el proyecto alrededor de otra unidad
económica: **la GPU trabaja una vez por escenario activo** y distribuyo el
caption resultante a todos los espectadores sin reinferencia.

Mi solución cubre el MVP y cuatro opcionales de la
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
provienen de la batería que incluí en este repositorio y ejecuté contra una RTX
3090:

| Dimensión del jurado | Resultado medido |
|---|---|
| Calidad ASR inglesa | WER **3,70 %** / exactitud 96,30 % contra subtítulos humanos |
| Traducción EN→ES | chrF **0,6873** / F1 léxico **0,7208** contra referencia revisada |
| Calidad ASR española | WER orientativo **22,22 %** contra captions automáticos de origen |
| 10 sesiones en paralelo | primera leyenda p50 **3,47 s**, máximo **3,51 s** |
| 2 streams bilingües + 20 viewers | 20/20 clientes, aislamiento correcto |
| 100 viewers en una charla | p95 de fan-out **17,12 ms**, una sola inferencia |
| 1.000 viewers en una réplica | p95 **173,07 ms**, mismo `event_id` para todos |
| 5.000 viewers en una réplica | p95 **1,316 s**, prueba extrema con un solo proceso |
| Experiencia visual | atraso observado 0,1–2,4 s; cola pico de un bloque |
| Pausa del directo | video y caption congelados; al reanudar vuelven juntos al punto en vivo |

Presento estas cifras como mediciones de laboratorio, no como una promesa del
cluster de producción. Se pueden repetir con `make quality`, `make acceptance`
y `make stress`.

## Arquitectura

![Arquitectura de OpenStreamTranslate](docs/diagrams/architecture.png)

1. Recibo desde Studio, OBS o el media ingress audio PCM mono de 16 kHz por WebSocket.
2. Ejecuto `faster-whisper` para reconocer el idioma original con contexto y *hotwords*.
3. Uso TranslateGemma para producir el caption destino y aplicar el glosario de la charla.
4. Conservo un historial corto en Redis Streams y comparto eventos entre réplicas con Pub/Sub.
5. Mantengo una suscripción Redis por sesión y réplica; desde allí distribuyo
   localmente por SSE, con replay mediante `Last-Event-ID`.
6. Superpongo los subtítulos en el navegador. El cambio de idioma es local y no
   vuelve a ejecutar los modelos.

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

No hay hostnames personales en el repositorio. Indica tu servidor y, si no es
22, su puerto SSH:

```bash
export REMOTE_HOST=user@gpu-host
export REMOTE_SSH_PORT=22
export REMOTE_ROOT=vibeathon-benchmark
```

Sincroniza el servicio y enciende los modelos:

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

Abre:

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
Copia `.env.example` a `.env`, cambia `ASR_URL` y `TRANSLATION_URL`, y ejecuta
solamente `docker compose up --build -d`.

## Cómo probar el servicio localmente

1. Entra a <http://localhost:8080/studio>.
2. Elige **Main Stage** y la dirección EN→ES o ES→EN.
3. Abre **Glosario técnico** y agrega términos si la charla lo requiere.
4. Presiona **Simular con video** y elige uno de los archivos de `samples/`.
5. Abre <http://localhost:8080/>: el video y los captions se sincronizan en el
   mismo reproductor. El menú **CC** cambia idioma u oculta subtítulos.
6. Al terminar, despliega **Exportar transcripción** en Studio para descargar
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

## Cómo lo integraría con un stream real

Diseñé el front como una implementación de referencia, no como una dependencia obligatoria. En
producción mantendría el video en el media server o CDN y derivaría solamente el
audio hacia este servicio:

```text
OBS / vMix
    │ SRT o RTMP
    ▼
Media server ───────── HLS/WebRTC ─────────► audiencia
    │
    └── FFmpeg: PCM mono 16 kHz
              │ WebSocket binario
              ▼
        OpenStreamTranslate
              │ SSE
              ├──► player con selector CC
              └──► overlay transparente para OBS/vMix
```

Para conectar una señal RTMP, SRT o HLS incluí un bridge que reinicia la
conexión si la fuente todavía no está disponible o se corta:

```bash
python scripts/media_stream_bridge.py \
  --input-url rtmp://media-server:1935/live/main \
  --caption-ws 'ws://captions:8080/api/sessions/main-stage/input?source=es&target=en'
```

El bridge usa FFmpeg para descartar el video, convertir el audio a PCM firmado
de 16 bits, mono y 16 kHz, y enviarlo en bloques binarios. Para otra charla uso
otro `session_id`; los espectadores adicionales no abren nuevas inferencias.

| Uso | Endpoint que expongo |
|---|---|
| Ingresar PCM mono 16 kHz | `WS /api/sessions/{id}/input?source=en&target=es` |
| Inyectar captions externos | `POST /api/sessions/{id}/captions` |
| Consumir captions y replay | `GET /api/sessions/{id}/events` |
| Overlay transparente | `/embed/{id}?lang=es` o `?lang=en` |
| Exportar transcripción | `/api/sessions/{id}/transcript/{srt\|vtt\|txt}?language=es` |

En OBS o vMix agregaría `/embed/main-stage?lang=es` como **Browser Source** o
**Fuente de navegador**. Si debo producir una única salida, puedo quemar ese
overlay en la composición. Si quiero que cada espectador elija idioma, no
quemo los subtítulos: conservo el video limpio y superpongo la pista elegida en
el player, como hace YouTube.

Para el laboratorio elegí HLS de baja latencia porque el stream RTMP transporta
audio AAC y MediaMTX puede entregarlo por HLS sin transcodificación adicional.
WebRTC sigue disponible; para usarlo con audio tendría que convertir AAC a Opus.
Prefiero hacer explícito ese costo antes que presentar una implementación WebRTC sin sonido.

## Decisiones técnicas que tomé

- Elegí **WebSocket** para la entrada porque necesito enviar audio binario de
  forma continua y recibir mensajes de control en la misma conexión.
- Elegí **SSE** para la audiencia porque el flujo es unidireccional, reconecta
  de forma nativa y soporta replay con `Last-Event-ID`.
- Elegí **Redis Streams + Pub/Sub** para historial corto y fan-out entre
  réplicas. No puse Kafka en el camino crítico porque no necesito retención
  larga para mostrar el caption; lo agregaría para auditoría o analítica.
- Separé el **plano de media** del **plano de captions**. Así, pausar, escalar o
  cambiar el CDN no obliga a transportar video por FastAPI.
- Dimensiono la GPU por **escenarios activos**, no por espectadores. Los
  gateways SSE escalan de manera independiente en CPU.
- Mantengo workers GPU calientes. En un despliegue con varias GPU usaría
  KubeRay/Ray Serve para colas y scheduling, pero no para reemplazar el media
  server ni Redis.

El análisis completo está en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Comportamiento en vivo

Por defecto calculo una hipótesis cada 1,5 s, intento confirmarla a los 3 s,
fuerzo el cierre a 4,5 s y conservo 750 ms de contexto. En la UI:

- estabiliza hipótesis parciales en lugar de apilar texto;
- limita el subtítulo a dos líneas y aproximadamente 20 caracteres por segundo;
- conserva bloques confirmados entre 1,8 y 3,2 s;
- usa el video como reloj maestro y acelera suavemente si el atraso supera 1,3 s;
- descarta parciales obsoletos antes de permitir que crezca una cola ilegible.

Cuando el espectador pausa, congelo también el caption visible y descarto los
eventos nuevos para esa vista. Cuando reanuda, vuelvo al punto en vivo, limpio
la cola acumulada y espero el siguiente caption. Elegí esta semántica porque es
un directo: reproducir subtítulos viejos sobre video actual sería peor que un
breve intervalo sin texto.

Estos parámetros pueden cambiarse en `.env`; sus valores y significado están
documentados en [`.env.example`](.env.example).

## Escalabilidad

Diseñé la capacidad GPU para escalar por **escenarios activos**, no por espectadores:

- Mantengo FastAPI stateless respecto de captions para replicarlo detrás de un
  ingress; Redis comparte sesiones e historial.
- En cada réplica abro una sola suscripción Pub/Sub por sesión y hago fan-out a
  colas locales acotadas.
- Escalo los gateways SSE en CPU independientemente de ASR y traducción.
- Precaliento los workers GPU para el máximo de escenarios; el autoscaling
  reactivo suele llegar tarde por el tiempo de carga de modelos.
- Considero KubeRay/Ray Serve una evolución útil para varias GPU, colas y tipos de
  acelerador. Kafka sólo se agrega si se necesita retención larga, analítica o
  consumidores externos; no está en el camino crítico del caption.

El punto de partida recomendado es unas 1.000 conexiones SSE por réplica y un
pool GPU dimensionado por charlas simultáneas. Repite `make stress` detrás del
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
| `LIVE_CONTEXT_CHARACTERS` | `700` | Historial textual móvil enviado a ASR |
| `MODEL_MAX_ATTEMPTS` | `3` | Intentos ante fallas transitorias de ASR/traducción |
| `MODEL_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout total por intento de inferencia |
| `MODEL_RETRY_BASE_SECONDS` | `0.25` | Backoff inicial de inferencia |
| `MODEL_RETRY_MAX_SECONDS` | `2` | Tope del backoff de inferencia |
| `REDIS_URL` | `redis://redis:6379/0` | Broker compartido |
| `SIMULATOR_START_DELAY_SECONDS` | `2` | Margen para sincronizar reproductores |

## Observabilidad

- Expongo `/api/health` para revisar Redis, ASR y traducción por separado.
- Expongo `/metrics` para medir streams, SSE activos, captions, latencia de modelos, atraso del
  caption, tiempo de publicación al broker, reintentos, errores agotados y parciales descartados.
- Escribo en `docker compose logs app` JSON por sesión, idioma, secuencia, latencia,
  atraso, reintentos y cantidad de términos del glosario.

El audio confirmado se elimina del buffer conservando sólo el solapamiento
acústico, mientras un contador absoluto mantiene los timestamps de la charla.
El contexto textual también está acotado; por eso una sesión larga no acumula
todo el PCM ni toda la transcripción en memoria.

Las métricas no aparecen en la vista pública; están destinadas a Prometheus y
al equipo de producción.

## Verificación

```bash
make smoke       # salud + un archivo real
make quality     # ASR, traducción, dos idiomas y comportamiento en vivo
make acceptance  # requisitos, WER, concurrencia, fan-out y opcionales
make stress      # 100, 1.000 y 5.000 espectadores SSE
```

`make quality` procesa un video inglés con referencia humana y un fragmento
español con referencia automática, mide WER, chrF, F1 léxico, factor de tiempo
real y luego ejecuta ambas direcciones en simultáneo. Documento la metodología
y sus límites en [`docs/QUALITY.md`](docs/QUALITY.md).

`make acceptance` valida Compose, UI, glosario, exportación, audio real,
latencia, WER ≤ 8 %, 2/5/10 fuentes, dos idiomas simultáneos, 100/1.000 viewers
y replay SSE. Los resultados quedan en `acceptance/latest-results/`.

La trazabilidad completa requisito → prueba → estado está en
[`acceptance/CRITERIA.md`](acceptance/CRITERIA.md). Los controles manuales
restantes son la revisión humana de naturalidad y la evaluación de idiomas
adicionales.

## Estructura del repositorio

```text
app/                    FastAPI y front público/Studio/overlay
remote/                 servicios GPU de ASR y traducción
samples/                dos videos y referencias de calidad
scripts/                smoke, aceptación, carga y operación SSH
acceptance/              matriz oficial y resultados medidos
benchmarks/              comparación de modelos ASR
docs/                    arquitectura, setup GPU y metodología de calidad
compose.yaml             app + Redis
```

## Limitaciones conocidas

- Todavía no implementé alineación por palabra; los timestamps son por bloque.
- La muestra española posee subtítulos automáticos de origen, por lo que
  presento su WER sólo como orientación. El gate estricto usa la referencia
  humana inglesa.
- El simulador sirve video desde el contenedor para pruebas locales. En producción
  debe usar media server/CDN y enviar una derivación de audio al WebSocket.
- El prototipo soporta EN y ES. Antes de agregar portugués validaría ASR,
  traducción, velocidad de lectura y referencias humanas antes de declararlo.

## Licencia y atribuciones

El código es [MIT](LICENSE), una licencia aprobada por la OSI. Los medios de
prueba y sus fuentes están documentados en [`samples/README.md`](samples/README.md).
Whisper, TranslateGemma, llama.cpp y los pesos conservan sus licencias y términos
propios; no forman parte de la licencia MIT de este repositorio.
