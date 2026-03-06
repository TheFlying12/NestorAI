#!/usr/bin/env bash
# Health check for the NestorAI cloud service.
# Usage: ./scripts/healthcheck.sh [http://localhost:8080]
set -euo pipefail

BASE="${1:-http://localhost:8080}"
failures=0

check() {
  local name="$1"
  local url="$2"
  local expected="${3:-200}"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" || echo "000")
  if [[ "$code" == "$expected" ]]; then
    echo "PASS: $name ($code)"
  else
    echo "FAIL: $name — expected $expected, got $code"
    failures=$((failures + 1))
  fi
}

echo "Checking $BASE ..."
check "health"     "$BASE/health"
check "api docs"   "$BASE/docs"   "200"

if [[ "$failures" -gt 0 ]]; then
  echo "HEALTHCHECK: FAIL ($failures checks failed)"
  exit 1
fi

echo "HEALTHCHECK: PASS"
