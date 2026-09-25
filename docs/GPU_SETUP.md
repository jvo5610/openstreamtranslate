# Preparación del host GPU

Esta guía deja los dos servicios de inferencia escuchando en loopback:

- `127.0.0.1:18081`: faster-whisper `large-v3-turbo`;
- `127.0.0.1:18080`: TranslateGemma 4B mediante `llama-server`.

No se necesitan credenciales de una API comercial. Sí se necesita acceso a los
pesos y aceptar las licencias correspondientes.

## Hardware probado

- Ubuntu Linux x86_64;
- NVIDIA RTX 3090 de 24 GB;
- driver NVIDIA 580.173.02;
- Python 3.12;
- TranslateGemma 4B IT Q8_0, aproximadamente 4,1 GB;
- `large-v3-turbo` FP16, aproximadamente 3,6 GB residentes en el servicio.

Una GPU menor puede funcionar reduciendo `ASR_WORKERS` o usando otra
cuantización. Para un evento conviene validar la misma combinación de driver,
CUDA, llama.cpp y pesos que se usará en producción.

## Layout esperado

Por defecto los scripts usan `~/vibeathon-benchmark`; se puede cambiar con
`REMOTE_ROOT` en el cliente y `VIBEATHON_REMOTE_ROOT` en el host:

```text
vibeathon-benchmark/
├── .venv/bin/python
├── models/translategemma-4b-it.Q8_0.gguf
├── remote/
├── results/
└── tools/
    ├── uv
    └── llama/
        ├── llama-b11175/llama-server
        └── cudart-llama-b11175-bin-ubuntu-cuda-12.8-x64/
```

Las rutas no son obligatorias. `remote/start-services.sh` acepta:

| Variable | Descripción |
|---|---|
| `VIBEATHON_REMOTE_ROOT` | raíz del runtime |
| `TRANSLATION_MODEL_PATH` | GGUF de TranslateGemma |
| `LLAMA_DIR` | bibliotecas de llama.cpp |
| `CUDART_DIR` | runtime CUDA usado por el build de llama.cpp |
| `LLAMA_SERVER_BIN` | ejecutable `llama-server` |
| `PYTHON_BIN` | Python del entorno con faster-whisper |
| `ASR_MODEL` | modelo CTranslate2; default `large-v3-turbo` |
| `ASR_WORKERS` | concurrencia del servicio; default `10` |

## Dependencias Python

Creá un entorno Python 3.11 o 3.12 e instalá:

```bash
python3 -m venv ~/vibeathon-benchmark/.venv
~/vibeathon-benchmark/.venv/bin/pip install \
  faster-whisper==1.2.0 \
  fastapi==0.116.1 \
  uvicorn==0.35.0 \
  python-multipart==0.0.20 \
  httpx==0.28.1
```

`faster-whisper` descarga `large-v3-turbo` en el primer arranque si no está en
la caché de Hugging Face. Para un evento, lo precargo y pruebo el arranque
sin depender de Internet.

## llama.cpp y TranslateGemma

Uso un build CUDA de `llama-server` compatible con el driver del host. Guardo
el GGUF en una ruta estable y la indico explícitamente si no coincide con el
layout predeterminado:

```bash
export LLAMA_SERVER_BIN=/opt/llama.cpp/bin/llama-server
export LLAMA_DIR=/opt/llama.cpp/lib
export CUDART_DIR=/usr/local/cuda/lib64
export TRANSLATION_MODEL_PATH=/models/translategemma-4b-it.Q8_0.gguf
```

El repositorio no fija una URL de pesos de terceros porque su disponibilidad y
condiciones pueden cambiar. Uso una conversión GGUF legítima de TranslateGemma
4B IT y conservo su aviso/licencia junto al modelo desplegado.

## Sincronizar e iniciar desde la máquina de operación

```bash
export REMOTE_HOST=user@gpu-host
export REMOTE_SSH_PORT=22
export REMOTE_ROOT=vibeathon-benchmark

make remote-sync
make remote-start
```

`remote-sync` espera `tools/uv` en el runtime remoto. Si está en otra ruta:

```bash
export REMOTE_UV=/usr/local/bin/uv
make remote-sync
```

El arranque espera ambos health checks, calienta Whisper con un segundo de
silencio y falla con un mensaje concreto si falta el modelo o un binario.

## Verificación en el host GPU

```bash
curl -fsS http://127.0.0.1:18081/health
curl -fsS http://127.0.0.1:18080/health
nvidia-smi
```

Los logs quedan en:

```text
~/vibeathon-benchmark/results/asr-server.log
~/vibeathon-benchmark/results/translate-server.log
```

## Seguridad

- Los servicios se ligan a `127.0.0.1`, no a `0.0.0.0`.
- El acceso desde la aplicación local usa un túnel SSH.
- No guardes claves SSH, tokens de Hugging Face ni pesos en el repositorio.
- Si despliego los workers dentro de una red de cluster, uso NetworkPolicy,
  autenticación de servicio y TLS en vez de publicar los puertos de inferencia.

## Ajuste de capacidad

`ASR_WORKERS=10` es el valor probado en la RTX 3090 y representa concurrencia
de requests, no diez copias del modelo. Lo reduzco si aparecen errores de
memoria o si el host comparte GPU. Mido `make acceptance` con la concurrencia
real del evento antes de definir el número de escenarios por GPU.
