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

### `reply` — assistant response

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
3. Client sends `message` frames; server responds with `typing` then `reply`
4. Client sends `ping` every 30s to prevent timeout (server closes after 90s idle)
5. On disconnect: client reconnects with exponential backoff (max 5 attempts)

---

## Special Commands

| Text | Effect |
|------|--------|
| `/forget` | Deletes all conversation history for the current session |

---

## Error Handling

- **Missing/invalid token** → close code `1008` before accept
- **Skill error** → `{"type": "reply", "text": "Something went wrong. Please try again."}`
- **No LLM key configured** → reply explains how to add a key via Settings
