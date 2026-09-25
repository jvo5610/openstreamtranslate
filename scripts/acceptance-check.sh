#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8080}"
SAMPLE="$ROOT/samples/ibm-future-computing-360p.webm"
SPANISH_SAMPLE="$ROOT/samples/nerdearla-kubernetes-es.mp4"
REPORT_DIR="$ROOT/acceptance"
RESULTS="$REPORT_DIR/latest-results"
mkdir -p "$RESULTS"

passed=0
failed=0
manual=0

pass() { printf 'PASS  %s\n' "$1"; passed=$((passed + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; failed=$((failed + 1)); }
todo() { printf 'MANUAL %s\n' "$1"; manual=$((manual + 1)); }
check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}

printf '== Entrega y documentación ==\n'
check 'Licencia MIT presente' rg -q '^MIT License' "$ROOT/LICENSE"
check 'README contiene instrucciones de inicio' rg -qi 'Inicio rápido|docker compose|make up' "$ROOT/README.md"
check 'README declara modelos y requisitos' rg -qi 'large-v3|Nemotron|TranslateGemma|modelo' "$ROOT/README.md"
check 'README explica el escalado de sesiones simultáneas' rg -qi 'escalabilidad|escalar|concurren|sesiones simult[aá]neas|workers|r[eé]plicas' "$ROOT/README.md"
check 'README incluye resumen accesible para jurados en inglés' rg -q 'English summary' "$ROOT/README.md"
check 'Diagrama de arquitectura versionado' test -s "$ROOT/docs/diagrams/architecture.png"
check 'Compose válido' docker compose -f "$ROOT/compose.yaml" config -q
check 'Hay material de prueba importable' test -s "$SAMPLE"
check 'Hay material de prueba en español' test -s "$SPANISH_SAMPLE"

if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  && git -C "$ROOT" remote get-url origin >/dev/null 2>&1 \
  && git -C "$ROOT" ls-remote --exit-code origin HEAD >/dev/null 2>&1; then
  pass 'Repositorio Git con remoto público configurado'
else
  fail 'Repositorio Git con remoto público configurado'
fi

if rg -qi 'youtube\.com|youtu\.be' "$ROOT/SUBMISSION.md" 2>/dev/null; then
  pass 'Video demo de 1–2 minutos enlazado'
else
  fail 'Video demo de 1–2 minutos enlazado'
fi
if first_commit="$(git -C "$ROOT" rev-list --max-parents=0 HEAD 2>/dev/null | tail -1)" \
  && [[ -n "$first_commit" ]] \
  && first_date="$(git -C "$ROOT" show -s --format=%cs "$first_commit" 2>/dev/null)" \
  && [[ "$first_date" =~ ^2026-09-(24|25)$ ]]; then
  pass 'Primer commit dentro del período 24–25/09/2026'
else
  fail 'Primer commit dentro del período 24–25/09/2026'
fi
if rg -n '(jvidelaolmos@ubuntu|/Users/[^/]+/|BEGIN [A-Z ]+PRIVATE KEY)' \
    "$ROOT" --glob '!.git/**' --glob '!acceptance/latest-results/**' --glob '!*.srt' \
    --glob '!scripts/acceptance-check.sh' >/dev/null 2>&1; then
  fail 'Repositorio sin hostnames personales, rutas locales ni claves privadas'
else
  pass 'Repositorio sin hostnames personales, rutas locales ni claves privadas'
fi
todo 'Enviar el proyecto en Devpost antes de las 15:00 UTC'
todo 'Confirmar que cada integrante estaba registrado en Nerdearla antes del cierre'

printf '\n== MVP técnico ==\n'
if curl -fsS "$BASE_URL/api/health" >"$RESULTS/health.json"; then
  if jq -e '.ok and .asr.ok and .translation.ok' "$RESULTS/health.json" >/dev/null; then
    pass 'ASR y traducción disponibles'
  else
    fail 'ASR y traducción disponibles'
  fi
else
  fail 'ASR y traducción disponibles'
fi

if curl -fsS "$BASE_URL/" >"$RESULTS/index.html" \
  && curl -fsS "$BASE_URL/studio" >"$RESULTS/studio.html"; then
  check 'La web ofrece micrófono' rg -q 'id="mic"' "$RESULTS/studio.html"
  check 'La web ofrece importación/simulación' rg -q 'id="stream-file"' "$RESULTS/studio.html"
  check 'Studio permite configurar el glosario técnico' rg -q 'id="glossary-entries"' "$RESULTS/studio.html"
  check 'La web muestra captions dentro del video' rg -q 'id="video-caption"' "$RESULTS/index.html"
else
  fail 'La interfaz web responde'
fi

glossary_session="acceptance-glossary"
if curl -fsS "$BASE_URL/api/sessions/$glossary_session/glossary?source_language=es&target_language=en" \
    >"$RESULTS/glossary-default.json" \
  && jq -e '.source_language == "es" and .target_language == "en" and any(.entries[]; .source == "Kubernetes")' \
    "$RESULTS/glossary-default.json" >/dev/null; then
  pass 'El glosario ofrece términos técnicos predeterminados por dirección'
else
  fail 'El glosario ofrece términos técnicos predeterminados por dirección'
fi

if curl -fsS -X PUT "$BASE_URL/api/sessions/$glossary_session/glossary" \
    -H 'Content-Type: application/json' \
    --data '{"source_language":"es","target_language":"en","entries":[{"source":"CloudNativePG","target":"CloudNativePG"},{"source":"base de datos","target":"database"},{"source":"cloudnativepg","target":"duplicado"}]}' \
    >"$RESULTS/glossary-custom.json" \
  && jq -e '.entries | length == 2' "$RESULTS/glossary-custom.json" >/dev/null \
  && jq -e 'any(.entries[]; .source == "base de datos" and .target == "database")' \
    "$RESULTS/glossary-custom.json" >/dev/null; then
  pass 'El glosario persiste equivalencias y elimina duplicados'
else
  fail 'El glosario persiste equivalencias y elimina duplicados'
fi
curl -fsS -X DELETE "$BASE_URL/api/sessions/$glossary_session" >/dev/null 2>&1 || true

if curl -fsS -X POST "$BASE_URL/api/process" -F "file=@$SAMPLE" >"$RESULTS/process.json"; then
  if jq -e '(.original | length > 20) and (.translation | length > 20)' "$RESULTS/process.json" >/dev/null; then
    pass 'Archivo real produce transcripción y traducción'
  else
    fail 'Archivo real produce transcripción y traducción'
  fi
  if jq -e '.latency.total < 5' "$RESULTS/process.json" >/dev/null; then
    pass 'Inferencia de archivo debajo de 5 segundos'
  else
    fail 'Inferencia de archivo debajo de 5 segundos'
  fi
  if python3 "$ROOT/scripts/score_asr.py" "$ROOT/samples/ibm-future-computing.en.srt" "$RESULTS/process.json" --json-field original >"$RESULTS/asr-quality.json" \
    && jq -e '.wer <= 0.08' "$RESULTS/asr-quality.json" >/dev/null; then
    pass 'Calidad ASR: WER menor o igual a 8%'
  else
    fail 'Calidad ASR: WER menor o igual a 8%'
  fi
else
  fail 'Archivo real produce transcripción y traducción'
fi

container_id="$(docker compose -f "$ROOT/compose.yaml" ps -q app 2>/dev/null)"
if [[ -n "$container_id" ]]; then
  docker cp "$ROOT/scripts/check_concurrency.py" "$container_id:/tmp/check_concurrency.py" >/dev/null
  docker cp "$ROOT/scripts/check_session_fanout.py" "$container_id:/tmp/check_session_fanout.py" >/dev/null
  docker cp "$ROOT/scripts/check_sse_scale.py" "$container_id:/tmp/check_sse_scale.py" >/dev/null
  docker cp "$ROOT/scripts/check_sse_reconnect.py" "$container_id:/tmp/check_sse_reconnect.py" >/dev/null
  docker cp "$ROOT/scripts/check_bilingual_streams.py" "$container_id:/tmp/check_bilingual_streams.py" >/dev/null
  docker cp "$SAMPLE" "$container_id:/tmp/acceptance-sample.webm" >/dev/null
  docker cp "$SPANISH_SAMPLE" "$container_id:/tmp/acceptance-spanish.mp4" >/dev/null
  if docker exec "$container_id" python /tmp/check_concurrency.py \
      --sample /tmp/acceptance-sample.webm --sessions 2 5 10 \
      >"$RESULTS/concurrency.json"; then
    pass '2, 5 y 10 sesiones simultáneas reciben captions en menos de 5 s'
  else
    fail '2, 5 y 10 sesiones simultáneas reciben captions en menos de 5 s'
  fi
  if docker exec "$container_id" python /tmp/check_session_fanout.py \
      --sample /tmp/acceptance-sample.webm --sessions 2 --viewers-per-session 10 \
      >"$RESULTS/session-fanout.json"; then
    pass '2 streams distribuyen por SSE a 20 espectadores sin duplicar inferencia'
  else
    fail '2 streams distribuyen por SSE a 20 espectadores sin duplicar inferencia'
  fi
  if docker exec "$container_id" python /tmp/check_session_fanout.py \
      --sample /tmp/acceptance-sample.webm --sessions 1 --viewers-per-session 100 \
      >"$RESULTS/fanout-100.json"; then
    pass '1 stream distribuye el mismo caption a 100 espectadores SSE'
  else
    fail '1 stream distribuye el mismo caption a 100 espectadores SSE'
  fi
  if docker exec "$container_id" python /tmp/check_sse_scale.py \
      --viewers 1000 --max-p95-ms 250 --timeout 40 \
      >"$RESULTS/sse-1000.json"; then
    pass '1 stream distribuye a 1.000 espectadores con p95 menor o igual a 250 ms'
  else
    fail '1 stream distribuye a 1.000 espectadores con p95 menor o igual a 250 ms'
  fi
  if docker exec "$container_id" python /tmp/check_sse_reconnect.py \
      >"$RESULTS/sse-reconnect.json"; then
    pass 'La reconexión SSE recupera eventos desde Last-Event-ID'
  else
    fail 'La reconexión SSE recupera eventos desde Last-Event-ID'
  fi
  if docker exec "$container_id" python /tmp/check_bilingual_streams.py \
      --english-sample /tmp/acceptance-sample.webm \
      --spanish-sample /tmp/acceptance-spanish.mp4 \
      --viewers-per-stream 10 \
      >"$RESULTS/bilingual-streams.json"; then
    pass 'Streams EN→ES y ES→EN simultáneos generan captions aislados'
  else
    fail 'Streams EN→ES y ES→EN simultáneos generan captions aislados'
  fi
else
  fail 'Contenedor de aplicación disponible para prueba concurrente'
fi

printf '\n== Producto y operación ==\n'
if rg -q 'id="session|session-select|stage-select' "$ROOT/app/static/watch.html"; then
  pass 'La audiencia puede elegir sesión'
else
  fail 'La audiencia puede elegir sesión'
fi
if rg -q 'id="(language|lang|target-language|language-select)|id="caption-language-button' "$ROOT/app/static/watch.html"; then
  pass 'La audiencia puede elegir idioma'
else
  fail 'La audiencia puede elegir idioma'
fi
if rg -q 'SOURCE_LANGUAGE|TARGET_LANGUAGE' "$ROOT/.env.example"; then
  pass 'Idiomas configurables por entorno'
else
  fail 'Idiomas configurables por entorno'
fi
todo 'Evaluar manualmente naturalidad de la traducción española'
todo 'Grabar recuperación ante caída de ASR o traductor'

printf '\n== Opcionales ==\n'
rg -qi 'OBS|vMix' "$ROOT/README.md" && rg -qi 'browser source|fuente.*navegador|overlay' "$ROOT/README.md" \
  && pass 'Integración OBS/vMix documentada' || todo 'Integración OBS/vMix'
rg -qi 'glossary|glosario' "$ROOT/app" "$ROOT/.env.example" \
  && pass 'Glosario implementado' || todo 'Glosario técnico'
export_session="acceptance-export"
if curl -fsS -X POST "$BASE_URL/api/sessions/$export_session/captions" \
    -H 'Content-Type: application/json' \
    --data '{"original":"Kubernetes escala sesiones.","translation":"Kubernetes scales sessions.","source_language":"es","target_language":"en","sequence":1,"final":true,"audio_start_seconds":0,"audio_end_seconds":2.5}' \
    >/dev/null \
  && curl -fsS "$BASE_URL/api/sessions/$export_session/transcript/srt?language=en" >"$RESULTS/export.srt" \
  && curl -fsS "$BASE_URL/api/sessions/$export_session/transcript/vtt?language=es" >"$RESULTS/export.vtt" \
  && curl -fsS "$BASE_URL/api/sessions/$export_session/transcript/txt?language=en" >"$RESULTS/export.txt" \
  && rg -q '^1$|Kubernetes scales sessions' "$RESULTS/export.srt" \
  && rg -q '^WEBVTT' "$RESULTS/export.vtt" \
  && rg -q 'Kubernetes scales sessions' "$RESULTS/export.txt"; then
  pass 'Exportación SRT, VTT y texto desde captions confirmados'
else
  fail 'Exportación SRT, VTT y texto desde captions confirmados'
fi
curl -fsS -X DELETE "$BASE_URL/api/sessions/$export_session" >/dev/null 2>&1 || true
rg -qi 'prometheus|/metrics' "$ROOT/app" "$ROOT/compose.yaml" \
  && pass 'Métricas operativas Prometheus' || todo 'Métricas operativas Prometheus'
rg -qi 'pt-BR|portugu[eé]s|Portuguese' "$ROOT/app" "$ROOT/.env.example" "$ROOT/README.md" \
  && pass 'Idiomas adicionales' || todo 'Idiomas adicionales (por ejemplo, portugués)'

printf '\nRESULTADO: %d PASS · %d FAIL · %d MANUAL/PENDIENTE\n' "$passed" "$failed" "$manual"
printf '{"passed":%d,"failed":%d,"manual":%d}\n' "$passed" "$failed" "$manual" >"$RESULTS/summary.json"
exit "$failed"
