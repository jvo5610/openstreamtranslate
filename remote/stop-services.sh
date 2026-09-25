#!/usr/bin/env bash
set -euo pipefail

ROOT="${VIBEATHON_REMOTE_ROOT:-$HOME/vibeathon-benchmark}"
for name in asr-server translate-server; do
  file="$ROOT/results/$name.pid"
  if [[ -f "$file" ]]; then
    pid="$(cat "$file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$file"
  fi
done
echo "Remote model services stopped."

