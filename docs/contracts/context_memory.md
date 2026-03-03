# Context and Memory Contract (Phase 0)

## Context Assembly
For each incoming user message:
1. Load latest summary for `(user_id, chat_id)`.
2. Load most recent `CONTEXT_WINDOW_TURNS` messages.
3. Build prompt as:
- system summary context
- recent turns
- new user message

## Defaults
- `CONTEXT_WINDOW_TURNS=12`
- `SUMMARY_UPDATE_EVERY_TURNS=6`
- `SUMMARY_TOKEN_THRESHOLD=3500`
- `MESSAGE_RETENTION_DAYS=90`

## Summary Refresh Conditions
Summary refresh runs when either condition is true:
- new conversation turns since last summary >= `SUMMARY_UPDATE_EVERY_TURNS`
- estimated prompt token load >= `SUMMARY_TOKEN_THRESHOLD`

## Data Tables
- `conversation_messages`
- `conversation_summaries`
- `message_history`

## Privacy Controls
- `/forget` deletes:
- raw conversation messages for the current `(user_id, chat_id)`
- summary row for the current `(user_id, chat_id)`
- message history rows for the current `(user_id, chat_id)`

## Retention
- Daily cleanup removes rows older than `MESSAGE_RETENTION_DAYS` from:
- `conversation_messages`
- `message_history`
