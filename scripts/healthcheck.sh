#!/usr/bin/env bash
set -euo pipefail

failures=0

require_up() {
  local service="$1"
  local status
  status=$(docker compose ps "$service" 2>/dev/null | tail -n +2 || true)
  if echo "$status" | rg -q "Up"; then
    echo "PASS: service $service is up"
  else
    echo "FAIL: service $service is not up"
    failures=$((failures + 1))
  fi
}

check_from_gateway() {
  local name="$1"
  local url="$2"
  local expected="$3"
  local code
  code=$(docker compose exec -T gateway python -c "import httpx;print(httpx.get('${url}', timeout=10).status_code)" 2>/dev/null || true)
  if [[ "$code" == "$expected" ]]; then
    echo "PASS: $name ($code)"
  else
    echo "FAIL: $name expected=$expected actual=${code:-none}"
    failures=$((failures + 1))
  fi
}

require_up "gateway"
require_up "openclaw"
require_up "ollama"

check_from_gateway "gateway health" "http://127.0.0.1:9000/health" "200"
check_from_gateway "openclaw health" "http://openclaw:18789/health" "200"
check_from_gateway "ollama tags" "http://ollama:11434/api/tags" "200"

bot_token=$(docker compose exec -T gateway sh -lc 'printf "%s" "${TELEGRAM_BOT_TOKEN:-}"' 2>/dev/null || true)
if [[ -n "$bot_token" ]]; then
  ok=$(docker compose exec -T gateway python -c "import os,httpx;u=f\"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN')}/getWebhookInfo\";r=httpx.get(u,timeout=15);print('ok' if r.status_code==200 and r.json().get('ok') else 'bad')" 2>/dev/null || true)
  if [[ "$ok" == "ok" ]]; then
    echo "PASS: telegram webhook info"
  else
    echo "FAIL: telegram webhook info request"
    failures=$((failures + 1))
  fi
else
  echo "SKIP: telegram webhook info (TELEGRAM_BOT_TOKEN not set in gateway)"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "HEALTHCHECK: FAIL ($failures checks failed)"
  exit 1
fi

echo "HEALTHCHECK: PASS"
