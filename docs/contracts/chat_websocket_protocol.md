# Browser Chat WebSocket Protocol

## Endpoint

```
WebSocket /chat?token=<clerk-jwt>
```

Authentication is via a Clerk-issued JWT passed as a query parameter. The server verifies the token before accepting the connection. Invalid tokens result in close code `1008`.

---

## Client → Server Frames

### `message` — send a user message

```json
{
  "type": "message",
  "text": "I spent $45 at Whole Foods",
  "skill_id": "budget_assistant"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | yes | Must be `"message"` |
| `text` | string | yes | User message text |
| `skill_id` | string | no | `"general"` (default) or `"budget_assistant"` |

### `ping` — keepalive

```json
{ "type": "ping" }
```

---

## Server → Client Frames

### `typing` — LLM processing started

Sent immediately after a message is received, before the reply is ready.

```json
{ "type": "typing" }
```

### `token` — streaming LLM token

Sent for each token as the LLM streams its response. Clients should append tokens
to the current in-progress message bubble. The final `reply` frame follows with the
complete canonical text.

```json
{ "type": "token", "text": "Logged" }
```

### `reply` — assistant response (complete)

Sent after all `token` frames. Contains the full assembled reply text. Clients
should use this to canonicalize the streamed message (handles race conditions /
reconnects cleanly).

```json
{
  "type": "reply",
  "text": "Logged $45.00 for food at Whole Foods."
}
```

### `pong` — keepalive response

```json
{ "type": "pong" }
```

---

## Session Lifecycle

1. Client connects: `wss://<host>/chat?token=<jwt>`
2. Server verifies JWT → accepts connection
3. Client sends `message` frames; server responds with `typing`, then one or more `token` frames, then a final `reply`
4. Client sends `ping` every 30s to prevent timeout (server closes after 90s idle)
5. On disconnect: client reconnects with exponential backoff (max 5 attempts)
6. On page load / skill change: client fetches history via `GET /api/conversations/messages`

---

## Conversation History REST Endpoint

```
GET /api/conversations/messages?skill_id=<skill>&limit=<n>
Authorization: Bearer <clerk-jwt>
```

Returns the last `limit` (default 50) user/assistant messages for the current user's
web conversation with the given skill.

```json
{
  "messages": [
    { "role": "user", "content": "I spent $45 at Whole Foods", "created_at": "2026-03-06T10:00:00Z" },
    { "role": "assistant", "content": "Logged $45.00 for food at Whole Foods.", "created_at": "2026-03-06T10:00:01Z" }
  ]
}
```

---

## Special Commands

| Text | Effect |
|------|--------|
| `/forget` | Deletes all conversation history for the current session |

---

## Error Handling

- **Missing/invalid token** → close code `1008` before accept
- **Skill error** → `{"type": "token", "text": "Something went wrong. Please try again."}` followed by `reply`
- **No LLM key configured** → token/reply explains how to add a key via Settings
- **Invalid API key (401)** → `"Invalid API key. Please update your key in Settings."`
- **Rate limit (429)** → `"LLM rate limit reached. Please try again in a moment."`
- **LLM unavailable (5xx)** → `"LLM service is temporarily unavailable."`
