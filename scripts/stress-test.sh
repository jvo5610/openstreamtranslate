#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS="$ROOT/acceptance/latest-results"
mkdir -p "$RESULTS"

container_id="$(docker compose -f "$ROOT/compose.yaml" ps -q app 2>/dev/null)"
if [[ -z "$container_id" ]]; then
  printf 'La aplicación no está ejecutándose. Usá make up primero.\n' >&2
  exit 1
fi

docker cp "$ROOT/scripts/check_sse_scale.py" "$container_id:/tmp/check_sse_scale.py" >/dev/null

run_case() {
  local viewers="$1"
  local max_p95_ms="$2"
  local timeout="$3"
  local output="$RESULTS/sse-$viewers.json"

  printf 'Probando %s espectadores SSE (p95 máximo: %s ms)...\n' "$viewers" "$max_p95_ms"
  if docker exec "$container_id" python /tmp/check_sse_scale.py \
      --viewers "$viewers" \
      --max-p95-ms "$max_p95_ms" \
      --timeout "$timeout" >"$output"; then
    jq '{viewers,successful_viewers,publish_request_ms,delivery_p50_ms,delivery_p95_ms,delivery_p99_ms,delivery_max_ms,passed}' "$output"
  else
    jq . "$output" 2>/dev/null || true
    return 1
  fi
}

failed=0
run_case 100 100 20 || failed=1
run_case 1000 250 40 || failed=1

# Es una prueba de capacidad extrema de una sola réplica. El objetivo de 1,5 s
# en p95 permite detectar degradaciones sin afirmar que 5.000 conexiones deban
# servirse desde un único proceso en producción.
run_case 5000 1500 60 || failed=1

exit "$failed"
