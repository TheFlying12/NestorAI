# NestorAI Delivery Plan v3 (with Context Management Spec)

## Summary
Deliver NestorAI in ordered phases with hard stability gates:
1. Phase 0: local Docker runtime (Telegram + OpenClaw + Ollama) hardened and testable.
2. Phase 1: same runtime on Raspberry Pi 5 (headless, outbound-only).
3. Phase 2: cloud dashboard + outbound device agent for pairing, settings, and skills.
4. Phase 3: WhatsApp via Meta WhatsApp Cloud API.

This version adds a complete conversation context and memory strategy so implementation can start without ambiguity.

## Locked Decisions

### Platform and sequencing
- Raspberry Pi 5 target.
- Docker Compose runtime.
- Phase 2 starts only after Phase 0 + Phase 1 are green.
- Cloud stack: FastAPI + Postgres.
- Cloud account model (MVP): single admin account.

### Messaging and providers
- Telegram first.
- WhatsApp later, default provider: Meta WhatsApp Cloud API.
- Provider abstraction starts in Phase 0.

### Device/cloud control plane
- Device is headless and outbound-only.
- Pairing bootstrap: factory secret + derived code (prepacked like Ring).
- Device ownership: single owner with explicit transfer flow.
- Transfer auth: physical reset code on device.
- Command delivery: at-least-once + idempotency key.
- Command TTL: 24 hours.
- Heartbeat: 30 seconds.

### Skills
- Remote catalog from GitHub.
- Package format: versioned tar.gz.
- Integrity policy: SHA256 required (fail on mismatch).

### Context and memory
- Context scope: sliding window + rolling summary.
- Sliding window size: 12 recent turns.
- Summary trigger: token-threshold + every 6 turns.
- Memory store: on-device SQLite.
- Long-term memory: opt-in per skill (default off).
- Raw message retention: 90 days.

## Architecture

## Device Runtime
- `openclaw`: skill and runtime engine.
- `ollama`: local model inference.
- `gateway_service`: messaging adapters + OpenClaw dispatch.
- `device-agent` (new): outbound websocket client for cloud control commands.

## Cloud Runtime
- FastAPI API service.
- Websocket hub for device sessions.
- Postgres for devices, pairing, commands, catalog metadata, and audit events.

## Public APIs and Contracts

## Cloud REST
1. `POST /api/pair/claim`
- Input: `device_id`, `pairing_code`
- Output: `device_token`, `claimed_at`
- Behavior: one-time claim unless transfer/reset completed.

2. `POST /api/devices/{device_id}/transfer/init`
- Output: `transfer_nonce`, `expires_at`

3. `POST /api/devices/{device_id}/transfer/confirm`
- Input: `transfer_nonce`, `physical_reset_code`
- Output: ownership reset/rebind result.

4. `GET /api/skills/catalog`
- Output fields: `skill_id`, `version`, `archive_url`, `sha256`, `size_bytes`, `compat`.

5. `POST /api/devices/{device_id}/commands`
- Envelope: `command_id`, `idempotency_key`, `type`, `payload`, `expires_at`.

6. `GET /api/devices/{device_id}/status`
- Output: connection state, last seen, installed skills, pending commands.

## Device Websocket Protocol
- Connect: `wss://.../devices/connect` with `Bearer <device_token>`.
- Frame types:
  - `hello`: device metadata/capabilities.
  - `heartbeat`: every 30s.
  - `command`: from cloud.
  - `command_ack`: `received|running|succeeded|failed|expired`.
- Semantics:
  - Server retries unacked commands.
  - Device dedupes by `idempotency_key`.
  - Commands past TTL are rejected with `expired`.

## Skill Catalog Contract
- GitHub-hosted JSON index.
- Artifacts are versioned `tar.gz`.
- Install pipeline: download -> SHA256 verify -> extract -> activate.
- Install location:
  - immutable baseline skills from repo.
  - writable installed skills under `/data/skills_installed`.

## Context and Memory Spec

## Data model (SQLite, on device)
Tables:
- `conversation_messages`
  - `id`, `provider`, `user_id`, `chat_id`, `role`, `content`, `created_at`
- `conversation_summaries`
  - `id`, `user_id`, `chat_id`, `summary_text`, `turn_count`, `token_estimate`, `updated_at`
- `skill_memories` (opt-in skills only)
  - `id`, `skill_id`, `user_id`, `key`, `value_json`, `created_at`, `updated_at`

## Prompt assembly for each request
1. Load latest summary for `(user_id, chat_id)`.
2. Load last 12 turns.
3. Build prompt in order:
- system policy
- summary checkpoint
- recent turns
- latest user message

## Summary update policy
Trigger summarization when either is true:
- estimated prompt tokens exceed threshold, or
- 6 new turns since last summary.

Summary update behavior:
- write new summary checkpoint.
- keep recent raw turns for continuity.
- older turns stay in DB until retention cleanup.

## Retention and cleanup
- Raw messages retained for 90 days.
- Daily cleanup job deletes expired raw rows.
- Summary rows retained longer unless user deletion is requested.
- Skill memories follow skill policy; default is disabled.

## User privacy controls
- Add `/forget` command (Telegram, later WhatsApp):
  - delete raw conversation history for that user/chat.
  - delete summary checkpoints for that user/chat.
  - delete opt-in skill memory for that user (or scoped by skill if requested).
- Expose equivalent action in cloud dashboard for admin operations.

## Phase Plan and Deliverables

## Phase 0: Local hardening
Deliver:
- Provider abstraction in gateway (Telegram adapter implemented).
- Health and smoke script with strict exit code.
- Log redaction for tokens and secrets.
- Context subsystem with SQLite tables, prompt builder, summarizer, retention job.
Acceptance:
- Reliable Telegram round-trip with local Ollama.
- Healthcheck command returns PASS/FAIL.
- No token leakage in logs.
- Context behavior matches 12-turn + summary policy.

## Phase 1: Pi runtime
Deliver:
- Pi setup and runbook.
- Compose parity and reboot resilience.
Acceptance:
- `docker compose up -d` works on Pi.
- Telegram round-trip from Pi inference.
- Reboot recovery without manual repair.

## Phase 2: Cloud + device agent
Deliver:
- Pairing, ownership, command queue, websocket hub.
- Agent command executor and status reporting.
- Catalog download/install with SHA256 verification.
Acceptance:
- Device claim end-to-end with prepacked pairing code.
- Command replay/idempotency validated.
- Skill install/update visible in status and effective on runtime.

## Phase 3: WhatsApp
Deliver:
- Meta WhatsApp Cloud API adapter on shared provider boundary.
Acceptance:
- WhatsApp inbound/outbound path works with no Telegram regressions.

## Test Cases

## Unit
- Pairing code verify/derive.
- Idempotency dedupe logic.
- SHA256 verify pass/fail.
- Prompt assembly (summary + 12 turns).
- Summary trigger logic (threshold + every 6 turns).
- Retention cleanup and `/forget` deletion behavior.

## Integration
- Telegram webhook -> OpenClaw -> reply.
- Device websocket reconnect + command replay.
- Skill install pipeline from catalog.
- Transfer flow requiring physical reset code.

## Failure scenarios
- Hash mismatch blocks install.
- Duplicate command does not duplicate side effects.
- Offline >24h expires commands cleanly.
- Cloud outage does not break local messaging runtime.
- Model timeout gracefully returns fallback and logs actionable error.

## Documentation Updates Required
- Update `PLAN.md` to this v3 plan.
- Update `README.md` into phase-aware sections (local, Pi, cloud).
- Add `docs/contracts/`:
  - websocket protocol
  - command schema
  - skill catalog schema
  - context and memory schema and retention rules
- Update `.env.example` for context, agent, and cloud vars.

## Assumptions
- OpenClaw continues as skill/runtime engine.
- Device factory process can inject per-device secret material.
- Token estimation can be approximate for summarization threshold in MVP.
- Single-admin model is acceptable until post-MVP multi-tenant work.
