#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENSTREAMTRANSLATE_REMOTE_ROOT:-$HOME/openstreamtranslate-runtime}"
for name in asr-server translate-server; do
  file="$ROOT/results/$name.pid"
  if [[ -f "$file" ]]; then
    pid="$(cat "$file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$file"
  fi
done
echo "Remote model services stopped."
