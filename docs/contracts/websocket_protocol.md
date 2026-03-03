# Device Websocket Protocol (MVP)

## Endpoint
- `wss://<cloud-host>/devices/connect`

## Authentication
- Header: `Authorization: Bearer <device_token>`
- Invalid token: server closes with policy violation.

## Common Envelope
All frames are JSON objects with:
- `type` (string)
- `sent_at` (RFC3339 UTC)
- `payload` (object)

## Client -> Server Frames

### `hello`
```json
{
  "type": "hello",
  "sent_at": "2026-02-28T00:00:00Z",
  "payload": {
    "device_id": "dev_123",
    "agent_version": "0.1.0",
    "capabilities": ["skill_install", "config_reload"]
  }
}
```

### `heartbeat`
- Interval: every 30 seconds.
```json
{
  "type": "heartbeat",
  "sent_at": "2026-02-28T00:00:30Z",
  "payload": {
    "device_id": "dev_123",
    "runtime_health": "ok",
    "queue_depth": 0
  }
}
```

### `command_ack`
```json
{
  "type": "command_ack",
  "sent_at": "2026-02-28T00:01:00Z",
  "payload": {
    "command_id": "cmd_123",
    "idempotency_key": "idem_abc",
    "status": "succeeded",
    "error_code": null,
    "error_message": null
  }
}
```

Allowed statuses:
- `received`
- `running`
- `succeeded`
- `failed`
- `expired`

## Server -> Client Frames

### `command`
```json
{
  "type": "command",
  "sent_at": "2026-02-28T00:00:50Z",
  "payload": {
    "command_id": "cmd_123",
    "idempotency_key": "idem_abc",
    "command_type": "install_skill",
    "expires_at": "2026-02-29T00:00:50Z",
    "body": {
      "skill_id": "personal_finance",
      "version": "1.0.0",
      "archive_url": "https://example.com/personal_finance-1.0.0.tar.gz",
      "sha256": "<hex>"
    }
  }
}
```

## Delivery Semantics
- At-least-once delivery.
- Device must dedupe by `idempotency_key`.
- Server may retry until ack or `expires_at`.
- Device must return `expired` if command is received after TTL.
