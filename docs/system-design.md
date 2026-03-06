# NestorAI — System Design & Technology Tradeoffs

**Audience:** Senior engineers, future maintainers, investors with technical backgrounds.
**Status:** Phase 2 — Cloud-Only, Web-First Architecture (as of 2026-03-06)

---

## 1. System Overview

NestorAI is a personal AI assistant that routes natural-language messages through a skill runtime to produce structured, actionable replies. The sole input channel is the web app — a Next.js PWA connected over a persistent WebSocket.

---

## 2. End-to-End Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  USER CLIENT                                                       │
│                                                                    │
│  Browser (Next.js PWA)                                            │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  /chat page                                                   │  │
│  │  Clerk auth + skill selector                                  │  │
│  │  WebSocket client (streaming token accumulation)             │  │
│  │  History loaded from REST on mount / skill change            │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │ WSS /chat?token=<clerk-jwt>          │
│                              │ GET /api/conversations/messages      │
└──────────────────────────────┼───────────────────────────────────-─┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  CLOUD API  (FastAPI — Railway)                                        │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Auth Layer (auth.py)                                            │  │
│  │  • Clerk JWT → JWKS verification (6h TTL cache)                 │  │
│  │  • get_current_user() / get_current_user_ws() dependencies      │  │
│  │  • Fernet-encrypted per-user API key storage                    │  │
│  └──────────────────────────┬──────────────────────────────────────┘  │
│                             │  user_id                                  │
│  ┌──────────────────────────▼──────────────────────────────────────┐  │
│  │  Context Engine (context.py)                                      │  │
│  │  • get_or_create_conversation()                                   │  │
│  │  • store_message()                                                │  │
│  │  • build_context_messages() → 12-turn window + rolling summary   │  │
│  │  • maybe_update_summary() → LLM summarization (async bg task)   │  │
│  └──────────────────────────┬──────────────────────────────────────┘  │
│                             │  context_messages[]                       │
│  ┌──────────────────────────▼──────────────────────────────────────┐  │
│  │  Skill Router (skills/router.py)                                  │  │
│  │  • dispatch_stream(user_id, text, skill_id, context, db)         │  │
│  │  • Resolves user LLM API key (Fernet decrypt) or system fallback │  │
│  │  • LLMError classification: 401 → auth msg, 429 → rate-limit,   │  │
│  │    5xx → unavailable                                             │  │
│  │  • Routes to:                                                     │  │
│  │    ├── general.py      → LLM stream pass-through                 │  │
│  │    └── budget_assistant.py → deterministic parse → PostgreSQL    │  │
│  │                             → LLM stream for explanation         │  │
│  │                             → deterministic fallback if LLM down │  │
│  └──────────────────────────┬──────────────────────────────────────┘  │
│                             │  token stream (SSE-style over WS)        │
│  ┌──────────────────────────▼──────────────────────────────────────┐  │
│  │  LLM API (OpenAI-compatible — BYOK)                              │  │
│  │  • User's key from Fernet-encrypted DB column                    │  │
│  │  • Fallback: OPENAI_API_KEY env var (demo/admin)                 │  │
│  │  • httpx async streaming client — 60s timeout                    │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
              │
     ┌────────┴────────┐
     ▼                 ▼
┌──────────┐    ┌───────────────────────────────────────────────────┐
│PostgreSQL│    │  Redis (Upstash)                                   │
│          │    │  • WS session registry (future multi-node)        │
│ users    │    │  • Currently: in-memory set (single-node MVP)     │
│ convos   │    └───────────────────────────────────────────────────┘
│ messages │
│ summaries│
│ txns     │
│ skill_mem│
└──────────┘
```

---

## 3. Technology Decisions

### 3.1 Runtime: FastAPI (Python)

**Chosen over:** Flask, Express (Node), Go Fiber

| Factor | Decision |
|--------|----------|
| Async-native | FastAPI is built on Starlette + asyncio. WebSocket handling, LLM calls, and DB I/O are all I/O-bound — async prevents thread starvation without thread pool overhead. |
| Type safety | Pydantic models give request/response validation with zero boilerplate. Errors surface at the boundary, not deep in business logic. |
| Speed | FastAPI benchmarks within 10-15% of Go at typical LLM-bound workloads. The bottleneck is always the LLM call (1-10s), not the framework. |
| Ecosystem match | SQLAlchemy async, httpx, python-jose, cryptography — all Python-native. No FFI, no transpilation. |

**Tradeoff accepted:** Python GIL means CPU-bound operations (heavy NLP, image processing) would need worker processes. NestorAI's hot path is I/O-bound (LLM APIs + DB), so this is acceptable.

---

### 3.2 Database: PostgreSQL

**Chosen over:** SQLite, DynamoDB, MongoDB, PlanetScale (MySQL)

**Why PostgreSQL:**
- Relational integrity matters: `conversation_messages → conversations → users` must be consistent. A dropped conversation must cascade-delete messages.
- `asyncpg` driver gives native async Postgres without synchronous wrapper overhead.
- JSONB support available for future schema-less skill memory without separate key-value stores.
- Alembic migration discipline — schema changes are versioned, reviewed, and applied in order.

**Why not MongoDB:** Schemaless sounds appealing for conversations, but message ordering, cascaded deletes, and analytics queries (monthly spending by category) all want relational guarantees. Document stores require application-side joins for these patterns.

**Tradeoff:** Relational DB requires schema migrations. Discipline cost: every schema change needs an Alembic migration. Benefit: no data inconsistency surprises.

---

### 3.3 Auth: Clerk

**Chosen over:** Supabase Auth, Auth0, rolling our own (JWT + bcrypt)

| Factor | Decision |
|--------|----------|
| Time-to-working-login | Clerk's `<SignIn />` component + `clerkMiddleware` gives email/password + social login in ~1 hour. |
| JWKS-based verification | Backend verifies RS256 JWTs without roundtripping to Clerk on every request. Cache has a 6-hour TTL so key rotations propagate without a restart. |
| Free tier | 10,000 MAUs free — enough to reach early product-market fit without spending on auth. |
| Session management | Clerk handles refresh tokens, device sessions, MFA — features that take weeks to build correctly. |

**Tradeoff:** Vendor dependency on Clerk. Migration path: Clerk exports user data. If they raise prices, migration to Auth0 or Supabase Auth is ~2-3 engineer-days.

---

### 3.4 API Key Encryption: Fernet (symmetric)

**Chosen over:** Asymmetric RSA, HashiCorp Vault, AWS KMS, storing keys in plaintext with hashing

**Why Fernet:**
- The cloud service needs to *decrypt* keys to call LLM APIs on behalf of users. Hashing is one-way and won't work. Asymmetric encryption would require the private key to be present anyway.
- Fernet (AES-128-CBC + HMAC-SHA256) is authenticated encryption — it detects tampering.
- Key management: `FERNET_KEY` env var lives in Railway secrets. At scale, rotate to AWS KMS envelope encryption.

**Tradeoff:** Single `FERNET_KEY` means all user keys are decryptable with one secret. Risk is mitigated because: (a) DB and key are separate secrets, (b) key rotation is supported by Fernet (just add the new key to `MultiFernet`). **Follow-up:** Add KMS envelope encryption at 1k+ users.

---

### 3.5 Frontend: Next.js 14 (App Router) + PWA

**Chosen over:** Vite SPA, Remix, SvelteKit, native iOS/Android, React Native

**Why Next.js:**
- SSR for auth-protected routes (server-side `auth()` call avoids FOUC on redirect).
- App Router enables React Server Components — the auth/redirect logic runs server-side with zero client JS.
- Vercel deployment is trivial: `git push` → build → deploy. No Docker needed for frontend.
- `@clerk/nextjs` has first-class App Router support — middleware, `<ClerkProvider>`, server-side `auth()`.

**Why PWA over native apps:**
- PWA installs from Safari/Chrome to home screen — no App Store submission, no review time.
- App Store review takes 1-2 weeks for first submission and is unpredictable.
- React Native adds 3x build complexity with shared codebase benefits only if you have a large team.
- **Revisit native at 50-100 active users when mobile-specific patterns are identified.**

**Tradeoff:** PWAs have limited access to native APIs (push notifications on iOS require Safari 16.4+, background sync is restricted). For NestorAI's current use case (chat + budget), this is acceptable.

---

### 3.6 WebSocket: FastAPI native (Starlette) with streaming

**Chosen over:** Socket.io, Pusher, Ably, Server-Sent Events (SSE)

**Why raw WebSocket:**
- FastAPI/Starlette handles WebSocket natively — no additional library.
- For MVP, a single-node `Dict[user_id, Set[WebSocket]]` is sufficient and supports multiple browser tabs per user.
- SSE would work for server→client streaming but doesn't handle client→server bidirectionally without a separate HTTP endpoint.
- Socket.io adds protocol overhead and room-management complexity not needed for 1:1 chat.

**Streaming protocol:** Server sends `{type:"token"}` frames as each LLM chunk arrives, followed by a final `{type:"reply"}` with the complete assembled text. Clients accumulate tokens into a single message bubble. The `reply` frame canonicalizes the text and handles reconnect/race edge cases.

**Tradeoff:** Single-node WS registry breaks with horizontal scaling. Migration path: replace `_browser_ws_sessions` dict with Redis pub/sub (`user_id → channel_name`). FastAPI publishes to Redis; all nodes subscribe. This is a ~200 LOC change with no client-side impact.

---

### 3.7 LLM Strategy: BYOK (Bring Your Own Key) + Streaming

**Chosen over:** API key pooling, local Ollama, fine-tuned models

**Why BYOK:**
- Zero LLM cost to the product operator at MVP. Users fund their own inference.
- OpenAI and any OpenAI-compatible API are supported via the same `/chat/completions` endpoint.
- No rate-limit pooling complexity — each user's quota is isolated.

**Why OpenAI-compatible endpoint abstraction:**
- `SYSTEM_LLM_BASE_URL` + `LLM_MODEL` can point at OpenAI, Groq, Together, Ollama, or any compatible provider. No code change needed.

**Streaming:** `_make_llm_stream` uses `httpx.AsyncClient.stream()` with SSE line parsing (`data: ...` → JSON delta extraction). Budget assistant falls back to deterministic reply if the LLM stream fails mid-response.

**LLM error classification:** 401 → "Invalid API key" user message, 429 → "Rate limit reached", 5xx → "Temporarily unavailable". Avoids the generic "something went wrong" for actionable errors.

**Tradeoff:** Users must bring their own API key, which creates onboarding friction. Mitigation: `OPENAI_API_KEY` env var as a system-level fallback so users can start immediately.

---

### 3.8 Skill Architecture: Embedded vs Microservice

**Chosen:** Skills embedded in the cloud FastAPI process as Python modules.

**Considered:** Separate microservices per skill (like the original OpenClaw model).

**Why embedded:**
- OpenClaw added a network hop, serialization, retry logic, and a separate deployment for every skill call.
- Skills (budget_assistant, general) are tiny — budget_assistant is ~200 LOC. The indirection cost outweighs the isolation benefit.
- Embedding skills means zero serialization overhead — the DB session passes directly.
- Skills can still be extracted to microservices later when they grow or need separate scaling.

**Tradeoff:** Embedding means a bad skill can crash the whole process. Mitigation: every skill call is wrapped in try/except with graceful degradation and deterministic fallback text.

---

### 3.9 Context Engine: Rolling Window + Summary

**Design:** 12-turn rolling window + LLM-generated summary (refreshed every 6 turns or 3500 tokens).

**Why not full context:**
- GPT-4o-mini context limit is 128k tokens, but sending all history costs linearly. A 90-day conversation at 50 messages/day = 4500 messages × avg 100 tokens = 450k tokens per request. Unacceptable.

**Why not vector search (RAG):**
- RAG requires an embedding model + vector DB (pgvector or Pinecone). That's 2 additional services.
- For a personal assistant with one user per conversation, a rolling summary captures 95% of what RAG would retrieve anyway.
- **Revisit:** Add pgvector retrieval when context degrades noticeably (estimated: 6-12 months of heavy use).

**Tradeoff:** Rolling summary loses verbatim history. The summary is LLM-generated and can lose nuance. Mitigated by keeping 12 recent turns verbatim in context.

---

## 4. Data Model

```
users
  user_id (PK)        — Clerk user ID ("user_...")
  email               — nullable
  auth_provider       — "clerk"
  api_key_encrypted   — Fernet(user_openai_key) — nullable

conversations
  conversation_id (PK)
  user_id (FK → users)
  channel             — "web"
  channel_id          — Clerk user_id (browser session)
  skill_id            — "general" | "budget_assistant"

conversation_messages
  id (PK, autoincrement)
  conversation_id (FK → conversations, CASCADE DELETE)
  role                — "user" | "assistant" | "system"
  content             — TEXT
  created_at

conversation_summaries
  id (PK)
  conversation_id (FK UNIQUE — one summary per conversation)
  summary_text        — LLM-generated rolling summary
  turn_count          — how many turns the summary covers
  token_estimate      — estimated tokens in summary

transactions
  id (PK)
  user_id (FK → users)
  amount (NUMERIC 12,2)
  category, merchant, note, currency
  timestamp

skill_memories
  id (PK)
  skill_id, user_id (FK → users), key
  value_json          — arbitrary JSON blob
  UNIQUE(skill_id, user_id, key)
```

---

## 5. Deployment Architecture

### MVP ($10-20/month)

```
Vercel (free)          Railway ($5-10/mo)
  Next.js 14      →      FastAPI + PostgreSQL plugin
  @clerk/nextjs   →      Alembic auto-migrate on deploy
  PWA manifest           CLOUD_SECRET_KEY, CLERK_SECRET_KEY,
                         FERNET_KEY, OPENAI_API_KEY (optional)

Clerk (free: 10k MAU)  Upstash Redis (free tier)
  JWT issuance           WS session registry (future)
  JWKS endpoint

LLM: User BYOK (OpenAI-compatible) — $0 to operator
```

### Growth Path (500-5k users, ~$50-100/mo)

- Railway → 2 replicas with Redis pub/sub for WS fan-out
- Supabase connection pooler (PgBouncer) to handle concurrent connections
- Upstash Redis paid tier for WS session registry
- Clerk Pro for advanced auth features

### Scale (5k+ users, ~$200-500/mo)

- AWS ECS Fargate (auto-scaling FastAPI, 2+ tasks)
- RDS PostgreSQL Multi-AZ
- ElastiCache Redis cluster mode
- ALB with sticky sessions for WebSocket
- CloudFront + S3 for Next.js static assets

---

## 6. Security Model

| Concern | Mitigation |
|---------|-----------|
| User API keys in DB | Fernet symmetric encryption; key in Railway secrets |
| Clerk JWT forgery | RS256 verification via JWKS; 6h TTL cache; `sub` claim required |
| SQL injection | SQLAlchemy ORM — parameterized queries only |
| Secrets in logs | No logging of token values, API keys, or message payloads |
| Multi-tenant data isolation | All queries scoped `WHERE user_id = :current_user_id` |

---

## 7. Observability

**Current (MVP):**
- Structured logs via Python logging: component, user_id (not token), event type
- `/health` endpoint: connected browser sessions count, service version
- FastAPI auto-generated OpenAPI docs at `/docs` (disable in prod)

**Planned:**
- Sentry for exception tracking (add `sentry-sdk[fastapi]`)
- Railway metrics for CPU/memory baseline
- Custom events: `skill_dispatched`, `llm_call_latency_ms`, `ws_connection_opened`

---

## 8. Explicit Assumptions

1. MVP user count is <500; single Railway instance is sufficient.
2. Web app (PWA) is the sole input channel. Additional channels (WhatsApp, Slack) deferred.
3. All LLM calls use OpenAI-compatible streaming (`stream: true`); tokens arrive incrementally.
4. Users are trusted with their own API keys; no per-user rate limiting on LLM calls yet.
5. Conversation isolation is by `(user_id, channel, channel_id, skill_id)`. Switching skills starts a separate conversation context.

---

## 9. Deferred / Follow-up Work

| Item | Priority | Trigger |
|------|----------|---------|
| Redis pub/sub for WS multi-node | High | Second Railway replica |
| KMS envelope encryption for API keys | Medium | 1k users |
| pgvector RAG for long-term memory | Low | Context degradation reports |
| Native iOS/Android | Low | 50-100 active users with identified mobile use cases |
| Rate limiting per user (LLM calls) | Medium | First abuse incident |
| Additional skills | Low | User demand |
| Additional input channels (WhatsApp, Slack) | Low | User demand |
