# NestorAI

Your personal AI assistant — available in the browser and on Telegram.

```
Browser (Next.js PWA)  ──WSS──▶  Cloud API (FastAPI)  ──▶  LLM (OpenAI / Gemini)
Telegram               ──────▶  Cloud API (FastAPI)  ──▶  PostgreSQL (context + data)
```

---

## What You Can Do

NestorAI has two built-in skills:

| Skill | Web | Telegram | What it does |
|-------|-----|----------|--------------|
| **General** | Default | Default | Questions, summaries, writing help |
| **Budget Assistant** | Sidebar → Budget | Always active | Log spending, budget alerts, monthly summary |

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
Summarize these notes: [paste]
What are the trade-offs between PostgreSQL and MongoDB?
Draft a subject line for this email: [paste]
```

### Universal commands (any channel)

```
/forget   — clear all conversation history for this chat
```

---

## Using the Web App

1. Open the web app and sign in with your email
2. Chat starts on the **General** skill
3. Switch skills using the sidebar (☰)
4. Add your OpenAI API key at **Settings → LLM API Key** (optional — a system key is used by default)

### Install as a mobile app (PWA)

- **iPhone/iPad:** Safari → Share → Add to Home Screen
- **Android:** Chrome → menu → Install app

No App Store required.

---

## Using Telegram

1. Find your bot (e.g. `@YourNestorBot`) and send any message
2. Budget transactions are logged automatically when your message contains a dollar amount
3. `/forget` clears conversation history

---

## Deployment

### Prerequisites

| Service | Purpose | Free tier |
|---------|---------|-----------|
| [Railway](https://railway.app) | FastAPI + PostgreSQL | $5/mo (Hobby) |
| [Clerk](https://clerk.com) | Auth (JWT) | Yes — 10k MAU |
| [Vercel](https://vercel.com) | Next.js web app | Yes |
| OpenAI / Gemini | LLM (user BYOK or system key) | Pay per use |

---

### 1. Cloud Service (Railway)

```bash
# Set these environment variables in your Railway project:
# DATABASE_URL         — auto-injected by Railway PostgreSQL plugin
# CLERK_SECRET_KEY     — Clerk Dashboard > API Keys
# CLERK_JWKS_URL       — Clerk Dashboard > API Keys > Advanced
# FERNET_KEY           — generate below
# OPENAI_API_KEY       — system fallback LLM key (optional)
# TELEGRAM_BOT_TOKEN   — from @BotFather (optional)
# TELEGRAM_WEBHOOK_URL — https://<your-railway-url>

# Generate a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Run DB migration (Railway shell or one-off command):
alembic upgrade head

# Start command:
uvicorn cloud_service.app.main:app --host 0.0.0.0 --port 8080
```

Telegram webhook is registered automatically on startup.

---

### 2. Web App (Vercel)

```bash
cd web_app && vercel link

# Set in Vercel Dashboard > Settings > Environment Variables:
# NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY  — Clerk Dashboard
# NEXT_PUBLIC_API_URL                — https://<your-railway-url>
# NEXT_PUBLIC_WS_URL                 — wss://<your-railway-url>

vercel --prod
```

---

### 3. Local Development

```bash
# 1. Configure
cp .env.example .env
# Fill in: DATABASE_URL, CLERK_SECRET_KEY, CLERK_JWKS_URL, FERNET_KEY, OPENAI_API_KEY

# 2. Start cloud service
AUTO_MIGRATE=true uvicorn cloud_service.app.main:app --port 8080 --reload

# 3. Start web app (separate terminal)
cd web_app && npm install && npm run dev

# Cloud API:   http://localhost:8080
# API docs:    http://localhost:8080/docs
# Web app:     http://localhost:3000

# Health check:
curl http://localhost:8080/health

# Or via Docker:
docker compose up --build
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

See [`docs/contracts/chat_websocket_protocol.md`](docs/contracts/chat_websocket_protocol.md) for the full protocol.

### Webhooks

```
POST /webhook/telegram     Telegram bot webhook (called by Telegram servers)
GET  /health               Service health + connected sessions
```

---

## Configuration Reference

See [`.env.example`](.env.example) for all variables.

| Group | Variables |
|-------|-----------|
| Cloud service | `DATABASE_URL`, `AUTO_MIGRATE`, `LOG_LEVEL` |
| Auth | `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `FERNET_KEY` |
| LLM | `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` |
| Context | `CONTEXT_WINDOW_TURNS`, `ENABLE_CONTEXT_SUMMARY`, `MESSAGE_RETENTION_DAYS` |
| Budget skill | `SKILL_BUDGETS` (JSON: `{"food":400,"transport":150}`) |
| Web app (Vercel) | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` |

---

## Testing

```bash
python -m unittest discover -s cloud_service/tests -p "test_*.py" -v
```

---

## How Context Works

- **12-turn sliding window** — last 12 messages always sent verbatim
- **Rolling summary** — older messages compressed into a summary (every 6 turns or ~3500 tokens)
- **Skill isolation** — Telegram and web conversations are separate; switching skills starts a new context
- **Retention** — messages older than 90 days automatically deleted
- **`/forget`** — wipe current conversation immediately

---

## Security

- Never commit `.env`. Rotate secrets immediately if exposed.
- User LLM API keys are Fernet-encrypted before storage — never logged or readable in plaintext.
- Telegram webhook validated via `X-Telegram-Bot-Api-Secret-Token` header.
- Clerk JWTs verified via RS256 against the JWKS endpoint.

---

## Further Reading

| Doc | Path |
|-----|------|
| System design + technology tradeoffs | [`docs/system-design.md`](docs/system-design.md) |
| Chat WebSocket protocol | [`docs/contracts/chat_websocket_protocol.md`](docs/contracts/chat_websocket_protocol.md) |
