#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is required."
  exit 1
fi

BASE="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

cmd="${1:-}"

case "$cmd" in
  set)
    if [[ -z "${TELEGRAM_WEBHOOK_URL:-}" ]]; then
      echo "TELEGRAM_WEBHOOK_URL is required for set."
      exit 1
    fi
    url="${TELEGRAM_WEBHOOK_URL%/}/webhook/telegram"
    secret="${TELEGRAM_WEBHOOK_SECRET:-}"
    payload=$(printf '{"url":"%s","secret_token":"%s","allowed_updates":["message","edited_message"]}' "$url" "$secret")
    curl -sS -X POST "${BASE}/setWebhook" -H "Content-Type: application/json" -d "$payload"
    echo
    ;;
  get)
    curl -sS "${BASE}/getWebhookInfo"
    echo
    ;;
  delete)
    curl -sS -X POST "${BASE}/deleteWebhook"
    echo
    ;;
  *)
    echo "Usage: TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_URL=... TELEGRAM_WEBHOOK_SECRET=... $0 {set|get|delete}"
    exit 1
    ;;
esac
