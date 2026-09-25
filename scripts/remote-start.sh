#!/usr/bin/env bash
set -euo pipefail
REMOTE_HOST="${REMOTE_HOST:?Set REMOTE_HOST=user@gpu-host}"
REMOTE_SSH_PORT="${REMOTE_SSH_PORT:-22}"
REMOTE_ROOT="${REMOTE_ROOT:-openstreamtranslate-runtime}"
ssh -p "$REMOTE_SSH_PORT" "$REMOTE_HOST" "OPENSTREAMTRANSLATE_REMOTE_ROOT=\"\$HOME/$REMOTE_ROOT\" '$REMOTE_ROOT/remote/start-services.sh'"
