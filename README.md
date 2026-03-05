# NestorAI

Local-first AI agent runtime for Raspberry Pi. Cloud is a control plane only.

**MVP Goal:** Device pairing + one useful agent (Budget Assistant) running reliably on Pi.

---

## Architecture

```
Raspberry Pi (device)              Cloud (control plane)
────────────────────────           ─────────────────────
gateway_service  (Telegram)   ←→   cloud_service (FastAPI + PostgreSQL)
openclaw runtime (skills)         ↑  WebSocket hub (command delivery)
device_agent     (WS client) ─────┘
```

- **LLM strategy (MVP):** Cloud LLM only (BYOK — device calls OpenAI/Gemini directly). No local Ollama required.
- **Local Ollama** is opt-in: `docker compose --profile local up`.

---

## Quick Start — Local Dev

```bash
# 1. Configure environment
cp .env.example .env
# Set: TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, OPENCLAW_GATEWAY_TOKEN

# 2. Start the stack (cloud LLM mode)
docker compose up --build

# 3. Health check
./scripts/healthcheck.sh
```

Gateway: `http://localhost:9000`
- `POST /webhook/telegram` — Telegram inbound
- `GET /health` — health

OpenClaw: `http://localhost:18789`

### Local LLM mode (opt-in)

```bash
# In .env: OPENCLAW_LLM_PROVIDER=ollama, OPENCLAW_LLM_MODEL=llama3.2:1b-instruct-q4_K_M
docker compose --profile local up
```

---

## Raspberry Pi Deploy (Phase 1)

See [`plans/pi-runbook.md`](plans/pi-runbook.md) for full instructions.

```bash
# Clone on Pi
git clone https://github.com/your-org/NestorAI.git && cd NestorAI
cp .env.example .env && nano .env

# Start with Pi-specific overrides
docker compose -f docker-compose.yml -f compose-pi.yml up -d --build

./scripts/healthcheck.sh
```

Pi uses `linux/arm64` images (set in `compose-pi.yml`) with memory limits tuned for Pi 5.

---

## Cloud Service Deploy (Phase 2)

```bash
cd cloud_service
# Set DATABASE_URL and CLOUD_SECRET_KEY in environment
pip install -r requirements.txt
AUTO_MIGRATE=true uvicorn cloud_service.app.main:app --port 8080

# Or with Alembic migrations:
alembic upgrade head
uvicorn cloud_service.app.main:app --port 8080
```

Cloud REST API:
- `POST /api/pair/claim` — claim a device with pairing code → returns `device_token`
- `GET /api/devices/{id}/status` — connection state, last_seen, installed skills
- `POST /api/devices/{id}/commands` — push a command to device
- `POST /api/devices/{id}/transfer/init` + `/confirm` — transfer ownership

WebSocket: `wss://<host>/devices/connect` — device agent connects here.

---

## Device Pairing

```bash
# 1. Add device + pairing code to cloud DB (admin/factory step)
# 2. Claim from any machine:
curl -X POST https://your-cloud/api/pair/claim \
  -H "Content-Type: application/json" \
  -d '{"device_id": "YOUR_DEVICE_ID", "pairing_code": "YOUR_CODE"}'
# Returns {"device_token": "...", "claimed_at": "..."}

# 3. Set DEVICE_TOKEN=<returned token> in .env on the Pi
# 4. Restart device_agent: docker compose restart device_agent
```

---

## Budget Assistant Skill

The Budget Assistant is the MVP skill. Send to Telegram:

- **Log a transaction:** `I spent $45 at Whole Foods`
- **Monthly summary:** `show my budget` or `what did I spend this month?`

Categorization and math are deterministic (local). LLM is used only for natural-language explanation.

---

## Testing

```bash
# Gateway tests (run from gateway_service/)
cd gateway_service
python -m unittest discover -s tests -p "test_*.py" -v

# Cloud service tests
python -m unittest discover -s cloud_service/tests -p "test_*.py" -v

# Device agent tests
cd device_agent
python -m unittest discover -s tests -p "test_*.py" -v
```

Or from inside a running container:
```bash
docker exec gateway-service python -m unittest discover -s /app/tests -p "test_*.py"
```

---

## Context Management

- 12-turn sliding window + rolling summary per conversation.
- Summary triggers: token threshold OR every 6 new turns.
- `/forget` command clears all history for a chat.
- Data retention: 90 days (configurable via `MESSAGE_RETENTION_DAYS`).

---

## Contracts and Runbooks

| Doc | Path |
|-----|------|
| Websocket protocol | `docs/contracts/websocket_protocol.md` |
| Command schema | `docs/contracts/command_schema.json` |
| Skill catalog schema | `docs/contracts/skill_catalog_schema.json` |
| Context/memory | `docs/contracts/context_memory.md` |
| Pi runbook | `plans/pi-runbook.md` |
| Architecture | `plans/NestorAI_MVP_Architecture.md` |

---

## Configuration Reference

See [`.env.example`](.env.example) for all variables. Key groups:

- **Messaging:** `PROVIDER`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_*`
- **LLM:** `OPENCLAW_LLM_PROVIDER`, `OPENAI_API_KEY`, `OPENCLAW_LLM_MODEL`
- **Device agent:** `DEVICE_ID`, `DEVICE_TOKEN`, `CLOUD_WS_URL`
- **Cloud:** `DATABASE_URL`, `CLOUD_SECRET_KEY`

---

## Security

- Never commit `.env`. Rotate tokens if exposed.
- `CLOUD_SECRET_KEY` is used for HMAC-SHA256 device token hashing — never store raw tokens.
- Skill installs require SHA256 verification; mismatches block install with no partial state.
- Device connectivity is outbound-only.
