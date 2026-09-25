#!/usr/bin/env bash
set -euo pipefail
REMOTE_HOST="${REMOTE_HOST:?Set REMOTE_HOST=user@gpu-host}"
REMOTE_SSH_PORT="${REMOTE_SSH_PORT:-22}"
echo "SSH tunnel active on localhost:18080 and localhost:18081. Press Ctrl-C to stop."
exec ssh -N \
  -p "$REMOTE_SSH_PORT" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 18080:127.0.0.1:18080 \
  -L 18081:127.0.0.1:18081 \
  "$REMOTE_HOST"
