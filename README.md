# NestorAI Gateway MVP

This repo contains a small FastAPI gateway that receives Telegram webhooks and forwards messages to a local OpenClaw instance. The gateway persists a minimal message history in SQLite and replies to the Telegram chat with the OpenClaw response.

## Quick Start
1. Create `.env` from `.env.example` and fill in the values.
2. Start the stack:

```bash
docker compose up --build
```

The gateway listens on `http://localhost:9000` and exposes `POST /webhook/telegram`.

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

## Local Development
Run just the gateway locally from `gateway_service/`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 9000
```

## Configuration Notes
- `OPENCLAW_URL` must be a local host (`openclaw`, `localhost`, etc.). The gateway refuses remote targets.
- `OPENCLAW_GATEWAY_TOKEN` should match the token configured for OpenClaw.
- SQLite data is stored at `/data/gateway.db` inside the container.

## Troubleshooting
- No replies in Telegram: confirm the bot has a webhook, and the URL is reachable via HTTPS.
- 401 from gateway: the Telegram webhook secret does not match.
- OpenClaw errors: check `docker compose logs openclaw` and ensure the health check passes.

## Security
Never commit `.env` or secrets. Rotate tokens if they were exposed.
