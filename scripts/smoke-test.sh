#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE="${SAMPLE:-$ROOT/samples/ibm-future-computing-360p.webm}"

curl -fsS "$BASE_URL/api/health"
echo
curl -fsS -X POST "$BASE_URL/api/process" -F "file=@$SAMPLE"
echo
