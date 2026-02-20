# Bug Fix Report and Plan

## Summary of Changes
- Added an `ollama_init` one-shot service that pulls the configured model via Ollama HTTP API before OpenClaw starts.
- Mounted local `./skills` into OpenClaw at `/data/skills` and switched the gateway route to OpenClaw chat completions.
- Added explicit Ollama provider configuration in OpenClaw runtime config (`/data/openclaw.json`) to ensure model registration.
- Switched the default model to a smaller footprint model (`llama3.2:1b-instruct-q4_K_M`) and removed larger models from Ollama storage.
- Increased gateway OpenClaw dispatch timeout and made Telegram webhook handling async to avoid webhook timeouts during slow inference.

## Files Touched
- `docker-compose.yml`
  - `ollama_init` service
  - `OPENCLAW_LLM_MODEL` default
  - skills volume mount for OpenClaw
  - gateway `OPENCLAW_ROUTE`
- `gateway_service/app/main.py`
  - dispatch timeout configurable
  - async background processing for Telegram replies

## Current Known Behavior
- Telegram webhook reaches the gateway and returns immediately.
- OpenClaw and Ollama are healthy, but local inference is slow (2–3 minutes per response on current hardware).
- Replies are sent after model completion; users must wait for slow responses.

## Plan (Next Steps)
1. Verify end-to-end Telegram flow by sending a test message and confirming a reply within 3 minutes.
2. If response time is still too long, reduce inference load by lowering context and output tokens in OpenClaw model config.
3. Add a short “processing…” immediate response (optional) if long waits degrade UX.
4. Add a health-check script to validate OpenClaw + Ollama + Gateway + Telegram webhook in one pass.
5. Document recommended minimum hardware / expected latency for MVP.

