# NestorAI MVP — Tradeoffs & Deferred Decisions

_Last updated: 2026-03-05. This document records what was chosen, what was deliberately left out, and what needs revisiting before or after the early-tester ship._

---

## 1. LLM Strategy: Cloud-only (BYOK) vs Local Ollama

**Decision:** MVP defaults to cloud LLM (OpenAI/Gemini), called directly from the device. Ollama is opt-in via `--profile local`.

| | Cloud LLM (chosen) | Local Ollama |
|---|---|---|
| Setup time | < 2 min | 10–25 min (model download) |
| Pi RAM impact | ~0 MB (LLM off-device) | 1–4 GB (1B–8B model) |
| Response latency | 2–5s (network) | 3–15s (Pi 5 inference) |
| Privacy | Data leaves device | Fully local |
| Cost | API usage cost | Free after setup |
| Offline resilience | Requires internet | Works offline |

**What we give up:** Full offline capability. Users must provide an API key. Data is processed by a third party.

**Mitigation:** Local LLM support is fully scaffolded (Ollama in compose, env vars ready). Switch to local is one config change.

**Revisit when:** Early testers report API costs are significant, or offline-first becomes a hard requirement.

---

## 2. WebSocket Hub: In-Memory Registry vs Redis Pub/Sub

**Decision:** `_ws_sessions: Dict[str, WebSocket]` — simple in-memory dict in `cloud_service/app/main.py`.

| | In-memory (chosen) | Redis pub/sub |
|---|---|---|
| Complexity | None | Medium (Redis infra) |
| Horizontal scale | Single instance only | Multi-node |
| MVP fit | Perfect | Overkill |
| Risk | Loses sessions on restart | Survives restarts |

**What we give up:** Cannot run cloud service with more than one replica. A cloud restart drops all active device connections (devices reconnect within seconds via backoff).

**Mitigation:** Reconnect + command replay logic is already in device_agent. Cloud restart is a minor blip, not data loss.

**Revisit when:** Need >1 cloud replica or cloud restarts become frequent.

---

## 3. Device Token Security: HMAC-SHA256 vs Full JWT

**Decision:** Device token is `"{device_id}:{raw_token}"` stored as `HMAC-SHA256(SECRET_KEY, raw_token)` in DB.

| | HMAC-SHA256 (chosen) | JWT (signed) |
|---|---|---|
| Revocability | Immediate (delete/rotate hash in DB) | Requires blocklist |
| Statefulness | Stateful (DB lookup on every auth) | Stateless |
| Complexity | Minimal | Medium (key management) |
| Expiry | None (permanent until rotated) | Built-in exp claim |

**What we give up:** Tokens never expire automatically. If `CLOUD_SECRET_KEY` is rotated, all devices need re-pairing.

**Mitigation:** Token rotation requires only a re-claim. Key rotation is a rare admin event.

**Revisit when:** Multi-tenant / user-facing token management is needed.

---

## 4. Command Delivery: At-Least-Once vs Exactly-Once

**Decision:** At-least-once with client-side idempotency deduplication (SQLite `executed_commands` table).

**What we give up:** A command may be sent twice (e.g., device reconnects before ack is received). The device deduplicates by `idempotency_key`, but the second delivery does consume a WebSocket round trip.

**Mitigation:** Handlers are designed to be idempotent (install to same path, config update is overwrite). Dedup check is the first thing in `handle_frame`.

**Risk:** If `gateway.db` is corrupted or deleted, idempotency history is lost and a replay could double-execute a command. Skill installs are safe (overwrite is fine); `reload_runtime` would restart OpenClaw again (acceptable).

---

## 5. Budget Assistant: Regex Categorization vs LLM Categorization

**Decision:** Deterministic regex + keyword matching for categorization; LLM used only for natural-language explanation.

| | Local regex (chosen) | LLM categorization |
|---|---|---|
| Latency | <1ms | 1–5s additional |
| Reliability | 100% (no network) | Depends on LLM availability |
| Accuracy | Good for common merchants | Better for edge cases |
| Cost | Free | API call per transaction |

**What we give up:** Edge-case merchants may be miscategorized. "Spent $30 at my landlord's restaurant" → `other` instead of `food`.

**Mitigation:** User can override via follow-up message (future feature). Category keywords are easy to extend in `_CATEGORY_KEYWORDS`.

**Revisit when:** Miscategorization becomes a frequent tester complaint.

---

## 6. Skill Install: Full Replace vs Delta Patch

**Decision:** `install_skill` extracts the full archive into `/data/skills_installed/{skill_id}/`, replacing all files.

**What we give up:** No incremental updates — every install downloads and re-extracts the full archive even if one file changed.

**Mitigation:** Skills are small (< 1 MB expected). Full replace eliminates partial-state corruption risk.

---

## 7. Cloud DB: PostgreSQL ORM vs Raw SQL

**Decision:** SQLAlchemy async + asyncpg. Alembic for migrations.

**What we give up:** More abstraction overhead than raw SQL. `async with session:` patterns are slightly more complex.

**Why chosen:** Alembic migrations give us auditable, reversible schema evolution from day one. SQLAlchemy prevents SQL injection at the boundary.

---

## 8. Single Admin Account vs Multi-Tenant

**Decision:** MVP treats the first claimer of a pairing code as the sole owner. No user auth layer on the cloud service.

**What we give up:** No multi-user support. No web UI for account management.

**Mitigation:** Transfer flow (`/transfer/init` + `/confirm`) allows ownership handoff with physical confirmation. Admin can create pairing codes directly in the DB.

**Revisit when:** Early testers want to share a device or the cloud service needs a real auth layer.

---

## 9. Docker Socket Mount in device_agent

**Decision:** Mount `/var/run/docker.sock` in `device_agent` to allow `handle_reload_runtime` to restart OpenClaw via Docker API.

**Security tradeoff:** A compromised `device_agent` process could control all containers on the host.

**Mitigation:**
- `device_agent` is a read-only outbound client — it only opens a WS connection to the cloud; it does not accept inbound network connections.
- The Docker socket is used only in `handle_reload_runtime`, which is triggered only by authenticated cloud commands.
- `device_agent` is not exposed to the network (no ports).

**Alternative considered:** SIGHUP to OpenClaw via shared PID namespace — more complex, same trust boundary.

**Revisit when:** Security audit requires reducing device attack surface.

---

## 10. What Is Explicitly Deferred

| Feature | Reason deferred |
|---|---|
| Factory pairing code CLI | Testers can insert codes directly into DB for now |
| Skill catalog (GitHub-hosted JSON index) | Budget Assistant is pre-installed; no dynamic catalog needed yet |
| WhatsApp adapter | Phase 3; provider boundary is already in place |
| Local LLM routing / LLM broker | Post-MVP; complexity outweighs value at this scale |
| Multi-node cloud (Redis hub) | Single instance sufficient for early testers |
| Web dashboard | CLI + Telegram is sufficient for early feedback |
| Usage metering / billing | No revenue model finalized |
| End-to-end integration test suite | Manual testing first; automate after patterns stabilize |
