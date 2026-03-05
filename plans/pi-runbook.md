# Raspberry Pi 5 Runbook (Phase 1)

## Target
- Raspberry Pi 5 (4 GB or 8 GB)
- Raspberry Pi OS 64-bit (Bookworm)
- Docker + Docker Compose plugin (v2)

## Prerequisites

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker compose version
```

## Initial Setup

```bash
# 1. Clone repository
git clone https://github.com/your-org/NestorAI.git
cd NestorAI

# 2. Configure environment
cp .env.example .env
nano .env  # Set TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, DEVICE_ID, DEVICE_TOKEN, CLOUD_WS_URL

# 3. Start the stack (cloud LLM mode — recommended for Pi)
docker compose -f docker-compose.yml -f compose-pi.yml up -d --build
```

## LLM Strategy

**MVP default: Cloud LLM (BYOK)**
- Set `OPENCLAW_LLM_PROVIDER=openai` and `OPENAI_API_KEY` in `.env`.
- Fastest setup, no model download, < 5s response time target.

**Optional: Local LLM (Ollama)**
- Requires additional RAM (4 GB minimum for 1B model).
- Start with profile flag:
  ```bash
  docker compose -f docker-compose.yml -f compose-pi.yml --profile local up -d
  ```
- Recommended model: `llama3.2:1b-instruct-q4_K_M`

## Validation

```bash
./scripts/healthcheck.sh
```

Expected output:
```
PASS: service gateway is up
PASS: service openclaw is up
PASS: gateway health (200)
PASS: openclaw health (200)
HEALTHCHECK: PASS
```

## Pairing with Cloud

After cloud_service is deployed:

```bash
# 1. Generate pairing code (factory CLI or cloud admin panel)
# 2. Claim device — from the device or any machine with the pairing code:
curl -X POST https://your-cloud/api/pair/claim \
  -H "Content-Type: application/json" \
  -d '{"device_id": "YOUR_DEVICE_ID", "pairing_code": "PAIRING_CODE"}'

# 3. Set DEVICE_TOKEN from response into .env
# 4. Restart device_agent
docker compose restart device_agent
```

## Reboot Recovery

All services have `restart: unless-stopped`. After reboot, Docker daemon auto-starts containers if enabled:

```bash
sudo systemctl enable docker
```

Verify after reboot:
```bash
# Wait ~60s for services to start
docker compose ps
./scripts/healthcheck.sh
```

## Memory Tuning

Pi memory limits (from `compose-pi.yml`):
| Service      | Limit |
|--------------|-------|
| openclaw     | 512 MB |
| gateway      | 256 MB |
| device_agent | 128 MB |
| ollama       | 4 GB (local profile only) |

## Troubleshooting

**Services not starting after reboot:**
```bash
sudo systemctl start docker
docker compose -f docker-compose.yml -f compose-pi.yml up -d
```

**Restart individual services:**
```bash
docker compose restart gateway openclaw device_agent
```

**Recreate stack if config drift:**
```bash
docker compose down
docker compose -f docker-compose.yml -f compose-pi.yml up -d --build
```

**Check logs:**
```bash
docker compose logs -f gateway
docker compose logs -f device_agent
docker compose logs -f openclaw
```

**Check device agent connection:**
```bash
docker compose logs device_agent | grep -E "connected|hello|heartbeat|error"
```
