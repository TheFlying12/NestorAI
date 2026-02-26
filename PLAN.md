# NestorAI Plan

## Vision
Headless Raspberry Pi running local LLM (Ollama) + OpenClaw skills engine, with all user interaction through Telegram (first) and WhatsApp (later). No UI on the device. An external cloud dashboard manages device pairing, skill installs, and settings.

## Phased Roadmap

### Phase 0 — Local LLM on Dev Machine (Docker)
Goal: reliable Telegram + OpenClaw + Ollama loop on dev machine.
- Health + smoke script for webhook, OpenClaw, Ollama
- Stable model + timeout settings
- Clear env var configuration

Acceptance:
- Telegram message receives a local response reliably
- Single command health check reports PASS/FAIL

### Phase 1 — Headless Pi Runtime
Goal: same Docker Compose stack on Raspberry Pi 5.
- Raspberry Pi OS 64-bit + Docker + Compose
- Small model target (1B class) for latency
- Document setup and model download size/time

Acceptance:
- `docker compose up -d` works on Pi
- Telegram message returns response from Pi

### Phase 2 — Cloud Dashboard + Device Agent (MVP)
Goal: external web UI manages skills/settings. Device connects outbound.

Architecture:
- Cloud: FastAPI + Postgres
- Device: outbound websocket agent + device token

Pairing flow:
1. Device has printed pairing code (no QR).
2. User enters pairing code in dashboard.
3. Cloud issues device token.
4. Device agent connects and receives commands.

Skill catalog:
- GitHub-hosted index (JSON)
- Device downloads, verifies, installs into `/data/skills`
- Update OpenClaw config and reload

Security:
- Pairing code expires (10 minutes)
- Device token rotates on re-pair

Acceptance:
- Pairing works end-to-end
- Skill install/update works from dashboard
- Device reconnects after reboot

### Phase 3 — WhatsApp
Add WhatsApp provider after Telegram MVP.
- Introduce provider abstraction in gateway
- Implement WhatsApp Cloud API or Twilio (decision later)

## Defaults / Assumptions
- Raspberry Pi 5 target
- Docker Compose runtime
- Telegram first, WhatsApp later
- Cloud dashboard hosted on Fly.io/Render
- External UI; device remains headless
