# NestorAI

Your personal AI assistant — available in the browser and on Telegram.

> **Architecture:** Cloud-first. Skills, context, and LLM routing all run in the cloud.
> Telegram + web chat are both first-class channels. Raspberry Pi is an optional power-user feature.

---

## What You Can Do

NestorAI has two built-in skills:

| Skill | How to activate | What it does |
|-------|----------------|--------------|
| **General** | Default | Open-ended questions, summaries, writing help |
| **Budget Assistant** | Web: sidebar → Budget · Telegram: just talk | Log transactions, see spending summaries, budget alerts |

### Budget Assistant — example messages

```
I spent $45 at Whole Foods
Grabbed coffee for $6 at Starbucks
Paid $120 for electricity bill
show my budget
what did I spend this month?
```

### General assistant — example messages

```
Summarize the key points of my last meeting notes: [paste]
Write a subject line for this email: [paste]
What are the trade-offs between PostgreSQL and MongoDB?
```

### Universal commands (any channel)

```
/forget   — clear all conversation history for this chat
```

---

## Using the Web App

**URL:** your Vercel deployment (or `http://localhost:3000` in dev)

1. Open the web app and sign in with your email (Clerk handles auth)
2. The chat starts on the **General** skill
3. Switch skills using the sidebar (click ☰)
4. Store your OpenAI API key at **Settings → LLM API Key** (optional — a system key is used by default)

### PWA — install on your phone

- **iPhone/iPad:** Open in Safari → Share → Add to Home Screen
- **Android:** Open in Chrome → menu → Install app

The app installs as a standalone app — no App Store required.

---

## Using Telegram

1. Find your bot on Telegram (e.g. `@YourNestorBot`)
2. Send any message — the bot responds using the General skill by default
3. The Budget Assistant is always active — if your message contains a dollar amount, it's logged automatically

No setup required on your end once the bot is deployed.

---

## Deployment

### Prerequisites

| Service | What for | Free tier? |
|---------|----------|-----------|
| [Railway](https://railway.app) | FastAPI + PostgreSQL | $5/mo (Hobby) |
| [Clerk](https://clerk.com) | Auth (JWT) | Yes — 10k MAU |
| [Vercel](https://vercel.com) | Next.js web app | Yes |
| [Upstash](https://upstash.com) | Redis (optional, multi-node WS) | Yes |
| OpenAI / Gemini | LLM (user BYOK or system key) | Pay per use |

---

### 1. Cloud Service (Railway)

```bash
# Clone the repo
git clone https://github.com/your-org/NestorAI.git && cd NestorAI

# Create a Railway project, add a PostgreSQL plugin, then set env vars:
# DATABASE_URL         — auto-injected by Railway PostgreSQL plugin
# CLOUD_SECRET_KEY     — random secret for device token HMAC
# CLERK_SECRET_KEY     — from Clerk Dashboard > API Keys
# CLERK_JWKS_URL       — from Clerk Dashboard > API Keys > Advanced
# FERNET_KEY           — generate below
# OPENAI_API_KEY       — system fallback LLM key
# TELEGRAM_BOT_TOKEN   — from @BotFather (if using Telegram)
# TELEGRAM_WEBHOOK_URL — https://<your-railway-url>

# Generate a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Run migrations (Railway shell or one-off command):
alembic upgrade head

# Start command (Railway detects this automatically via Procfile or Dockerfile):
uvicorn cloud_service.app.main:app --host 0.0.0.0 --port 8080
```

The cloud service registers the Telegram webhook automatically on startup when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_URL` are set.

---

### 2. Web App (Vercel)

```bash
cd web_app
# Link to your Vercel project:
vercel link

# Set environment variables in Vercel Dashboard > Settings > Environment Variables:
# NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY  — from Clerk Dashboard
# NEXT_PUBLIC_API_URL                — https://<your-railway-url>
# NEXT_PUBLIC_WS_URL                 — wss://<your-railway-url>

# Deploy:
vercel --prod
```

---

### 3. Local Development

```bash
# 1. Copy and fill in env vars
cp .env.example .env
# Required for local: DATABASE_URL, CLOUD_SECRET_KEY, CLERK_SECRET_KEY,
#                     CLERK_JWKS_URL, FERNET_KEY, OPENAI_API_KEY

# 2. Start the cloud service
AUTO_MIGRATE=true uvicorn cloud_service.app.main:app --port 8080 --reload

# 3. Start the web app (separate terminal)
cd web_app && npm install && npm run dev
# Web app: http://localhost:3000
# Cloud API: http://localhost:8080
# API docs: http://localhost:8080/docs

# 4. Health check
curl http://localhost:8080/health
```

---

### 4. Raspberry Pi (optional, power users)

See [`plans/pi-runbook.md`](plans/pi-runbook.md). The Pi runs `device_agent`, which connects to the cloud WebSocket and receives commands.

```bash
# On the Pi:
git clone https://github.com/your-org/NestorAI.git && cd NestorAI
cp .env.example .env
# Set: DEVICE_ID, DEVICE_TOKEN (from pairing), CLOUD_WS_URL

docker compose -f docker-compose.yml -f compose-pi.yml up -d --build
```

---

## API Reference

Base URL: `https://<your-cloud-service>`

### Auth

```
POST /api/auth/apikey      Store your LLM API key (encrypted at rest)
  Body: {"api_key": "sk-...", "provider": "openai"}
  Auth: Bearer <clerk-jwt>

GET  /api/auth/me          Current user info
  Auth: Bearer <clerk-jwt>
  Returns: {user_id, email, has_api_key, auth_provider}
```

### Chat (browser)

```
WebSocket /chat?token=<clerk-jwt>

Client → Server:
  {"type": "message", "text": "I spent $20 at Trader Joes", "skill_id": "budget_assistant"}
  {"type": "ping"}

Server → Client:
  {"type": "typing"}
  {"type": "reply", "text": "Logged $20.00 for food at Trader Joe's..."}
  {"type": "pong"}
```

### Webhooks

```
POST /webhook/telegram     Telegram bot webhook (called by Telegram servers)
```

### Device management (Pi users)

```
POST /api/pair/claim                              Claim device with pairing code
GET  /api/devices/{id}/status                     Device status + pending commands
POST /api/devices/{id}/commands                   Push command to device
POST /api/devices/{id}/transfer/init              Start ownership transfer
POST /api/devices/{id}/transfer/confirm           Complete ownership transfer
WebSocket /devices/connect                        Device agent persistent connection
```

---

## Configuration Reference

See [`.env.example`](.env.example) for all variables. Key groups:

| Group | Variables |
|-------|-----------|
| Cloud service | `DATABASE_URL`, `CLOUD_SECRET_KEY`, `AUTO_MIGRATE` |
| Auth | `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `FERNET_KEY` |
| LLM | `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` |
| Context | `CONTEXT_WINDOW_TURNS`, `ENABLE_CONTEXT_SUMMARY`, `MESSAGE_RETENTION_DAYS` |
| Budget skill | `SKILL_BUDGETS` (JSON: `{"food":400,"transport":150}`) |
| Pi device | `DEVICE_ID`, `DEVICE_TOKEN`, `CLOUD_WS_URL` |
| Web app | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` |

---

## Testing

```bash
# Cloud service invariants (12 tests)
python -m unittest discover -s cloud_service/tests -p "test_*.py" -v

# Gateway service tests (legacy)
cd gateway_service && python -m unittest discover -s tests -p "test_*.py" -v

# Device agent tests
cd device_agent && python -m unittest discover -s tests -p "test_*.py" -v
```

---

## How Context Works

- **12-turn sliding window** — the last 12 messages are always sent verbatim
- **Rolling summary** — older messages are compressed into a summary (triggers every 6 turns or ~3500 tokens)
- **Skill isolation** — your Telegram conversation and web conversation are separate; switching skills starts a new context
- **Data retention** — messages older than 90 days are automatically deleted
- **`/forget`** — wipe everything for the current conversation immediately

---

## Security Notes

- Never commit `.env`. Rotate tokens immediately if exposed.
- User API keys are encrypted with Fernet (AES-128) before being stored — never logged or visible in plaintext.
- `CLOUD_SECRET_KEY` is used for HMAC-SHA256 device token hashing — keep it secret.
- All external calls have explicit timeouts. No secrets appear in logs.

---

## Further Reading

| Doc | Path |
|-----|------|
| System design + technology tradeoffs | [`docs/system-design.md`](docs/system-design.md) |
| WebSocket protocol | [`docs/contracts/websocket_protocol.md`](docs/contracts/websocket_protocol.md) |
| Command schema | [`docs/contracts/command_schema.json`](docs/contracts/command_schema.json) |
| Pi runbook | [`plans/pi-runbook.md`](plans/pi-runbook.md) |
