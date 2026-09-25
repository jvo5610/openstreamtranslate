#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENSTREAMTRANSLATE_REMOTE_ROOT:-$HOME/openstreamtranslate-runtime}"
RESULTS="$ROOT/results"
LLAMA_DIR="${LLAMA_DIR:-$ROOT/tools/llama/llama-b11175}"
CUDART_DIR="${CUDART_DIR:-$ROOT/tools/llama/cudart-llama-b11175-bin-ubuntu-cuda-12.8-x64}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$LLAMA_DIR/llama-server}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
MODEL="${TRANSLATION_MODEL_PATH:-$ROOT/models/translategemma-4b-it.Q8_0.gguf}"

for required in "$LLAMA_SERVER_BIN" "$PYTHON_BIN" "$MODEL"; do
  if [[ ! -e "$required" ]]; then
    echo "Missing required runtime file: $required" >&2
    echo "See docs/GPU_SETUP.md in the repository." >&2
    exit 1
  fi
done

mkdir -p "$RESULTS"
export LD_LIBRARY_PATH="$LLAMA_DIR:$CUDART_DIR:$ROOT/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:$ROOT/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

stop_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(cat "$file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$file"
  fi
}

stop_pid "$RESULTS/asr-server.pid"
stop_pid "$RESULTS/translate-server.pid"

cd "$ROOT"
nohup "$LLAMA_SERVER_BIN" \
  -m "$MODEL" -ngl 99 -c 16384 -np 8 --no-jinja \
  --host 127.0.0.1 --port 18080 \
  > "$RESULTS/translate-server.log" 2>&1 &
echo $! > "$RESULTS/translate-server.pid"

nohup env ASR_MODEL="${ASR_MODEL:-large-v3-turbo}" ASR_WORKERS="${ASR_WORKERS:-10}" \
  "$PYTHON_BIN" -m uvicorn remote.asr_server:app \
  --host 127.0.0.1 --port 18081 \
  > "$RESULTS/asr-server.log" 2>&1 &
echo $! > "$RESULTS/asr-server.pid"

for port in 18080 18081; do
  ready=false
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:$port/health" >/dev/null; then ready=true; break; fi
    sleep 1
  done
  if [[ "$ready" != true ]]; then
    echo "Service on port $port did not become healthy" >&2
    exit 1
  fi
done

"$PYTHON_BIN" - <<'PY'
import io
import wave
import httpx

audio = io.BytesIO()
with wave.open(audio, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b"\0\0" * 16000)
httpx.post(
    "http://127.0.0.1:18081/transcribe",
    files={"file": ("warmup.wav", audio.getvalue(), "audio/wav")},
    data={"language": "en"},
    timeout=120,
).raise_for_status()
httpx.post(
    "http://127.0.0.1:18080/completion",
    json={
        "prompt": "<start_of_turn>user\nTranslate from English to Spanish. Output only the translation.\nReady.<end_of_turn>\n<start_of_turn>model\n",
        "n_predict": 16,
        "temperature": 0,
        "stop": ["<end_of_turn>"],
        "cache_prompt": True,
    },
    timeout=120,
).raise_for_status()
PY

echo "ASR and translation services are healthy."
