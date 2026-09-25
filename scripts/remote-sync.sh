#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:?Set REMOTE_HOST=user@gpu-host}"
REMOTE_SSH_PORT="${REMOTE_SSH_PORT:-22}"
REMOTE_ROOT="${REMOTE_ROOT:-vibeathon-benchmark}"
REMOTE_UV="${REMOTE_UV:-tools/uv}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ssh -p "$REMOTE_SSH_PORT" "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT/remote'"
scp -P "$REMOTE_SSH_PORT" "$PROJECT_ROOT/remote/asr_server.py" "$PROJECT_ROOT/remote/start-services.sh" "$PROJECT_ROOT/remote/stop-services.sh" "$REMOTE_HOST:$REMOTE_ROOT/remote/"
ssh -p "$REMOTE_SSH_PORT" "$REMOTE_HOST" "chmod +x '$REMOTE_ROOT/remote/start-services.sh' '$REMOTE_ROOT/remote/stop-services.sh'; cd '$REMOTE_ROOT'; '$REMOTE_UV' pip install --python .venv/bin/python fastapi==0.116.1 uvicorn==0.35.0 python-multipart==0.0.20 httpx==0.28.1"
echo "Remote files and dependencies synchronized."
