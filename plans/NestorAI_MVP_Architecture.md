# NestorAI MVP Architecture

Version: 1.0 Audience: Codex Build Agents Goal: Validate device-based AI
agent runtime

------------------------------------------------------------------------

# 1. MVP Objective

Validate: - Device pairing works - One useful agent runs reliably - UX
feels stable

Not included: - Marketplace - Billing - Local LLM routing complexity -
WhatsApp - Multi-model orchestration

------------------------------------------------------------------------

# 2. MVP Scope

## Local (Raspberry Pi)

Services: - gateway_service (Telegram only) - openclaw_runtime -
context_service (SQLite) - device_agent

No local LLM required for MVP. Cloud LLM only.

------------------------------------------------------------------------

## Cloud

Services: - FastAPI - PostgreSQL - WebSocket Hub

Tables: - devices - pairing_codes - commands

Endpoints: - POST /pair/claim - POST /devices/{id}/commands - GET
/devices/{id}/status

------------------------------------------------------------------------

# 3. LLM Strategy

Cloud LLM only. Direct API call from device (BYOK allowed). No broker
required for MVP.

------------------------------------------------------------------------

# 4. Single Agent Strategy

Ship ONE agent only.

Recommended: Budget Assistant

Capabilities: - Categorize transactions - Monthly summaries - Budget
alerts - Natural language explanations

LLM used for explanation only. Math and logic local.

------------------------------------------------------------------------

# 5. Build Order

Week 1--2: - Docker stack stable - Telegram works - Agent runs

Week 3: - Pairing flow complete - WebSocket control channel stable

Week 4: - Install skill command works - Remote restart works

Week 5: - Logging + error handling

Then ship to early testers.

------------------------------------------------------------------------

# 6. Success Criteria

-   Device install \< 15 minutes
-   Stable uptime
-   Agent response \< 5 seconds average
-   Real user usage feedback

------------------------------------------------------------------------

# 7. Post-MVP Expansion

Add later: - Local LLM support - Skill catalog marketplace - LLM
broker - Usage metering - WhatsApp integration
