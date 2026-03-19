# NestorAI

Your personal AI assistant — available in the browser.

```
Browser (Next.js PWA)  ──WSS──▶  Cloud API (FastAPI)  ──▶  LLM (OpenAI-compatible)
                                         │
                                    PostgreSQL
                               (context + transactions)
```

---


## What You Can Do

NestorAI has two built-in skills:

| Skill | How to activate | What it does |
|-------|----------------|--------------|
| **General** | Default | Questions, summaries, writing help |
| **Budget Assistant** | Sidebar → Budget | Log spending, budget alerts, monthly summary |

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

### Commands

```
/forget   — clear all conversation history for the current skill
```

---

## Using the Web App

1. Open the web app and sign in with your email
2. Chat starts on the **General** skill
3. Switch skills using the sidebar (☰)
4. Add your OpenAI API key at **Settings → LLM API Key** (optional — a system key is used by default)
5. Your conversation history reloads automatically on page refresh

Responses stream token-by-token as the LLM generates them.

### Install as a mobile app (PWA)

- **iPhone/iPad:** Safari → Share → Add to Home Screen
- **Android:** Chrome → menu → Install app

No App Store required.

---

## Deployment

### Prerequisites

| Service | Purpose | Free tier |
|---------|---------|-----------|
| [Railway](https://railway.app) | FastAPI + PostgreSQL | $5/mo (Hobby) |
| [Clerk](https://clerk.com) | Auth (JWT) | Yes — 10k MAU |
| [Vercel](https://vercel.com) | Next.js web app | Yes |
| OpenAI / any OpenAI-compatible API | LLM (user BYOK or system key) | Pay per use |

---

### 1. Cloud Service (Railway)

```bash
# Set these environment variables in your Railway project:
# DATABASE_URL         — auto-injected by Railway PostgreSQL plugin
# CLERK_SECRET_KEY     — Clerk Dashboard > API Keys
# CLERK_JWKS_URL       — Clerk Dashboard > API Keys > Advanced
# FERNET_KEY           — generate below
# OPENAI_API_KEY       — system fallback LLM key (optional)

# Generate a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Run DB migration (Railway shell or one-off command):
alembic upgrade head

# Start command:
uvicorn cloud_service.app.main:app --host 0.0.0.0 --port 8080
```

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

### Chat (WebSocket)

```
WebSocket /chat?token=<clerk-jwt>

Client → Server:
  {"type": "message", "text": "I spent $20 at Trader Joes", "skill_id": "budget_assistant"}
  {"type": "ping"}

Server → Client:
  {"type": "typing"}                    — LLM started
  {"type": "token", "text": "Logged"}   — streaming token (one per LLM chunk)
  {"type": "reply", "text": "..."}      — full reply (end of stream)
  {"type": "pong"}
```

See [`docs/contracts/chat_websocket_protocol.md`](docs/contracts/chat_websocket_protocol.md) for the full protocol.

### Conversation History

```
GET /api/conversations/messages?skill_id=general&limit=50
  Auth: Bearer <clerk-jwt>

Response: {"messages": [{"role": "user"|"assistant", "content": "...", "created_at": "..."}]}
```

### Health

```
GET /health
```

---

## Configuration Reference

See [`.env.example`](.env.example) for all variables.

| Group | Variables |
|-------|-----------|
| Cloud service | `DATABASE_URL`, `AUTO_MIGRATE`, `LOG_LEVEL` |
| Auth | `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `FERNET_KEY` |
| LLM | `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
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
- **Skill isolation** — switching skills switches to a separate conversation context
- **Retention** — messages older than 90 days automatically deleted
- **`/forget`** — wipe current conversation immediately
- **History reload** — conversation history loads from DB on page refresh or skill change

---

## Security

- Never commit `.env`. Rotate secrets immediately if exposed.
- User LLM API keys are Fernet-encrypted before storage — never logged or readable in plaintext.
- Clerk JWTs verified via RS256 against the JWKS endpoint (6-hour TTL cache; refreshes on rotation).
- All queries are scoped `WHERE user_id = :current_user_id` — no cross-user data leakage.

---

## Further Reading

| Doc | Path |
|-----|------|
| System design + technology tradeoffs | [`docs/system-design.md`](docs/system-design.md) |
| Chat WebSocket protocol | [`docs/contracts/chat_websocket_protocol.md`](docs/contracts/chat_websocket_protocol.md) |
