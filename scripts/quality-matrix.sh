#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8080}"
RESULTS="$ROOT/acceptance/latest-results"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openstreamtranslate-quality.XXXXXX")"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

mkdir -p "$RESULTS"

for command in curl docker ffmpeg jq python3; do
  command -v "$command" >/dev/null || { echo "Falta el comando requerido: $command" >&2; exit 1; }
done

health="$(curl -fsS "$BASE_URL/api/health")"
jq -e '.ok and .asr.ok and .translation.ok and .broker.ok' <<<"$health" >/dev/null

printf '1/5 Procesando referencia inglesa completa...\n'
curl -fsS -X POST "$BASE_URL/api/process" \
  -F "file=@$ROOT/samples/ibm-future-computing-360p.webm" \
  -F 'source_language=en' \
  -F 'target_language=es' \
  >"$RESULTS/quality-process-en-es.json"

printf '2/5 Preparando y procesando 30 segundos de referencia española...\n'
ffmpeg -hide_banner -loglevel error \
  -i "$ROOT/samples/nerdearla-kubernetes-es.mp4" \
  -t 30 -vn -ac 1 -ar 16000 -c:a pcm_s16le \
  "$TEMP_DIR/nerdearla-es-30.wav"
curl -fsS -X POST "$BASE_URL/api/process" \
  -F "file=@$TEMP_DIR/nerdearla-es-30.wav" \
  -F 'source_language=es' \
  -F 'target_language=en' \
  >"$RESULTS/quality-process-es-en.json"

printf '3/5 Midiendo reconocimiento y traducción...\n'
python3 "$ROOT/scripts/score_asr.py" \
  "$ROOT/samples/ibm-future-computing.en.srt" \
  "$RESULTS/quality-process-en-es.json" --json-field original \
  >"$RESULTS/quality-asr-en.json"
python3 "$ROOT/scripts/score_asr.py" \
  "$ROOT/samples/nerdearla-kubernetes-es.es.srt" \
  "$RESULTS/quality-process-es-en.json" --json-field original --end-seconds 30 \
  >"$RESULTS/quality-asr-es.json"
python3 "$ROOT/scripts/score_translation.py" \
  "$ROOT/samples/ibm-future-computing.es.srt" \
  "$RESULTS/quality-process-en-es.json" --json-field translation \
  >"$RESULTS/quality-translation-en-es.json"

printf '4/5 Ejecutando streams simultáneos EN→ES y ES→EN...\n'
container_id="$(docker compose -f "$ROOT/compose.yaml" ps -q app)"
test -n "$container_id"
docker cp "$ROOT/scripts/check_bilingual_streams.py" "$container_id:/tmp/check_bilingual_streams.py" >/dev/null
docker cp "$ROOT/samples/ibm-future-computing-360p.webm" "$container_id:/tmp/quality-en.webm" >/dev/null
docker cp "$ROOT/samples/nerdearla-kubernetes-es.mp4" "$container_id:/tmp/quality-es.mp4" >/dev/null
live_exit=0
docker exec "$container_id" python /tmp/check_bilingual_streams.py \
  --english-sample /tmp/quality-en.webm \
  --spanish-sample /tmp/quality-es.mp4 \
  --viewers-per-stream 3 \
  --audio-seconds 10 \
  >"$RESULTS/quality-live-bilingual.json" || live_exit=$?

printf '5/5 Consolidando gates...\n'
jq -n \
  --slurpfile en_asr "$RESULTS/quality-asr-en.json" \
  --slurpfile es_asr "$RESULTS/quality-asr-es.json" \
  --slurpfile translation "$RESULTS/quality-translation-en-es.json" \
  --slurpfile en_process "$RESULTS/quality-process-en-es.json" \
  --slurpfile es_process "$RESULTS/quality-process-es-en.json" \
  --slurpfile live "$RESULTS/quality-live-bilingual.json" \
  --argjson live_exit "$live_exit" \
  '{
    generated_at: (now | todate),
    cases: [
      {
        id: "english-to-spanish",
        media: "IBM Research — A lab for the future of computing",
        source_language: "en",
        target_language: "es",
        asr: $en_asr[0],
        translation: $translation[0],
        latency_seconds: $en_process[0].latency,
        audio_seconds: 70.6,
        real_time_factor: ((($en_process[0].latency.total / 70.6) * 10000 | round) / 10000),
        gates: {
          asr_wer_max_0_08: ($en_asr[0].wer <= 0.08),
          translation_chrf_min_0_60: ($translation[0].chrf >= 0.60),
          translation_token_f1_min_0_65: ($translation[0].token_f1 >= 0.65),
          real_time_factor_max_0_12: (($en_process[0].latency.total / 70.6) <= 0.12)
        }
      },
      {
        id: "spanish-to-english",
        media: "Nerdearla — Kubernetes y bases de datos (primeros 30 s)",
        source_language: "es",
        target_language: "en",
        asr: $es_asr[0],
        translation: {
          hypothesis_characters: ($es_process[0].translation | length),
          non_empty: (($es_process[0].translation | length) > 20)
        },
        latency_seconds: $es_process[0].latency,
        audio_seconds: 30,
        real_time_factor: ((($es_process[0].latency.total / 30) * 10000 | round) / 10000),
        notes: "La referencia española proviene de captions automáticos; uso este WER como orientación, no como ground truth humano.",
        gates: {
          asr_wer_max_0_30_orientative: ($es_asr[0].wer <= 0.30),
          translation_non_empty: (($es_process[0].translation | length) > 20),
          real_time_factor_max_0_12: (($es_process[0].latency.total / 30) <= 0.12)
        }
      }
    ],
    live_bilingual: $live[0],
    live_bilingual_exit_code: $live_exit
  }
  | .passed = (
      ([.cases[].gates[]] | all)
      and (.live_bilingual.passed == true)
      and (.live_bilingual_exit_code == 0)
    )' >"$RESULTS/quality-matrix.json"

jq '{passed, cases: [.cases[] | {id, asr, translation, latency_seconds, gates}], live_bilingual: {passed: .live_bilingual.passed, streams: .live_bilingual.streams}}' \
  "$RESULTS/quality-matrix.json"
jq -e '.passed == true' "$RESULTS/quality-matrix.json" >/dev/null
