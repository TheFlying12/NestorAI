# NestorAI Gateway MVP (Phase 0)

This repo contains a FastAPI gateway that receives Telegram webhooks and forwards messages to a local OpenClaw instance. The gateway persists conversation history in SQLite, builds context windows with rolling summaries, and replies to Telegram.

## Quick Start (Local Docker)
1. Create `.env` from `.env.example` and fill in the values.
2. Start the stack:

```bash
docker compose up --build
```

The gateway listens on `http://localhost:9000` and exposes provider webhook endpoints:
- Telegram: `POST /webhook/telegram`
- WhatsApp: `GET /webhook/whatsapp` (Meta verify), `POST /webhook/whatsapp` (messages)

3. Run the health and smoke check:

```bash
./scripts/healthcheck.sh
```

## Telegram Webhook Setup
Telegram requires a public HTTPS URL. Use a tunnel (ngrok, cloudflared) and set:

```
TELEGRAM_WEBHOOK_URL=https://your-public-domain
```

On startup, the gateway calls Telegram `setWebhook` with:

- URL: `TELEGRAM_WEBHOOK_URL + /webhook/telegram`
- Secret: `TELEGRAM_WEBHOOK_SECRET` (header `x-telegram-bot-api-secret-token`)

To verify the webhook:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

## WhatsApp Webhook Setup (Meta Cloud API)
Set these vars in `.env`:

```
PROVIDER=whatsapp
WHATSAPP_ACCESS_TOKEN=<meta-permanent-token>
WHATSAPP_PHONE_NUMBER_ID=<phone-number-id>
WHATSAPP_WEBHOOK_VERIFY_TOKEN=<verify-token-you-set-in-meta>
```

Configure Meta webhook callback URL to:

```
https://your-public-domain/webhook/whatsapp
```

Meta verification calls `GET /webhook/whatsapp` with `hub.*` query params; gateway returns the challenge when verify token matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN`.

## Local Development
Run just the gateway locally from `gateway_service/`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 9000
```

## Context Management
- The gateway sends a context window of the most recent turns (`CONTEXT_WINDOW_TURNS`, default `12`).
- A rolling summary is maintained and injected into prompts when enabled (`ENABLE_CONTEXT_SUMMARY=true`).
- Summaries refresh on token threshold or every `SUMMARY_UPDATE_EVERY_TURNS` turns.
- Conversation data retention defaults to `90` days (`MESSAGE_RETENTION_DAYS`).
- Users can clear memory for the current chat by sending `/forget`.
- `ASSISTANT_SYSTEM_PROMPT` sets a hard response policy to keep replies user-focused and avoid unsolicited runtime/file disclosures.

## Contracts and Runbooks
- Device websocket protocol: `docs/contracts/websocket_protocol.md`
- Command envelope schema: `docs/contracts/command_schema.json`
- Skill catalog schema: `docs/contracts/skill_catalog_schema.json`
- Context/memory contract: `docs/contracts/context_memory.md`
- Raspberry Pi runbook: `docs/pi-runbook.md`

## Configuration Notes
- `OPENCLAW_URL` must be a local host (`openclaw`, `localhost`, etc.). The gateway refuses remote targets.
- `OPENCLAW_GATEWAY_TOKEN` should match the token configured for OpenClaw.
- SQLite data is stored at `/data/gateway.db` inside the container.
- `PROVIDER` supports `telegram` and `whatsapp`.
- `OPENCLAW_ROUTE` should be `/v1/chat/completions` for chat payloads.

## Troubleshooting
- No replies in Telegram: confirm the bot has a webhook, and the URL is reachable via HTTPS.
- 401 from gateway: the Telegram webhook secret does not match.
- OpenClaw errors: check `docker compose logs openclaw` and ensure the health check passes.
- Run `./scripts/healthcheck.sh` to identify failing edges quickly.

## Test (Fast Path)
From the gateway container:

```bash
docker exec gateway-service python -m unittest discover -s /app/tests -p "test_*.py"
```

## Security
Never commit `.env` or secrets. Rotate tokens if they were exposed.
