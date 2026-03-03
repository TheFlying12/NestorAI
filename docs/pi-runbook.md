# Raspberry Pi 5 Runbook (Phase 1)

## Target
- Raspberry Pi 5
- Raspberry Pi OS 64-bit
- Docker + Docker Compose plugin

## Setup
1. Install Docker and Compose plugin.
2. Clone repository on device.
3. Copy `.env.example` to `.env` and set required values.
4. Start stack:

```bash
docker compose up -d --build
```

## Validation
Run healthcheck:

```bash
./scripts/healthcheck.sh
```

Expected:
- `gateway`, `openclaw`, `ollama` are up
- local health endpoints return 200
- Telegram webhook info check passes when token is configured

## Ollama model notes
- Start with a 1B class model for latency/memory.
- Keep model quantized for Pi constraints.

## Recovery
- Restart services:

```bash
docker compose restart gateway openclaw ollama
```

- Recreate stack if config drift is suspected:

```bash
docker compose down
docker compose up -d --build
```
