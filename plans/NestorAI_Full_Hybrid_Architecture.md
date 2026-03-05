# NestorAI Full Hybrid Architecture

Version: 1.0 Audience: Engineers, Codex, AI Agents Purpose:
Production-ready hybrid local-first AI agent platform

------------------------------------------------------------------------

# 1. System Philosophy

NestorAI is a local-first AI agent runtime deployed on user-owned
Raspberry Pi devices. The cloud acts strictly as a control plane.

Design Principles: - Device continues functioning if cloud is
unavailable - User conversation data remains local by default - Cloud
provides orchestration, pairing, and optional LLM routing - Hybrid
inference: local + cloud

------------------------------------------------------------------------

# 2. High-Level Architecture

## 2.1 Data Plane (Raspberry Pi)

Services (Docker Compose):

-   gateway_service
-   openclaw_runtime
-   context_service (SQLite)
-   device_agent (WebSocket client)
-   optional: ollama (local LLM)

Responsibilities:

gateway_service: - Telegram/WhatsApp adapters - Normalize inbound
messages - Assemble prompt bundle - Return final response

openclaw_runtime: - Agent orchestration - Skill execution - Tool calls -
LLM routing

context_service: - SQLite database - Tables: - conversation_messages -
conversation_summaries - skill_memories - Prompt assembly: - latest
summary - last N messages - user input - Summarization policy: - token
threshold OR fixed turn count

device_agent: - Outbound-only WebSocket client - Connects to cloud hub -
Receives control commands - Reports status

ollama (optional): - Local quantized LLM inference - Tier 0 inference
only

------------------------------------------------------------------------

# 3. Control Plane (Cloud)

Services:

-   FastAPI API Service
-   PostgreSQL
-   WebSocket Hub
-   Skill Catalog (GitHub or S3)
-   Optional LLM Broker

Responsibilities:

FastAPI: - Pairing/claim endpoints - Device command API - Status
endpoints - Skill catalog metadata

PostgreSQL: - devices - pairing_codes - commands - audit_events -
skills_metadata

WebSocket Hub: - Maintains device sessions - Delivers commands - Retries
until acknowledged - At-least-once delivery

Skill Catalog: - Tar archives - SHA256 hash required - Versioned
releases

Optional LLM Broker: - Centralized cloud LLM calls - Policy
enforcement - Usage metering - Redaction controls

------------------------------------------------------------------------

# 4. Hybrid LLM Routing Policy

Tier 0 (Local Preferred): - Intent classification - Tool routing - Short
summarization - Extraction

Tier 1 (Cloud Preferred): - Planning - Travel optimization - Budget
coaching insights - Long-context reasoning

Auto Mode: 1. Attempt local inference 2. On timeout or overflow →
escalate to cloud

------------------------------------------------------------------------

# 5. Core Flows

## Chat Flow

User → Telegram → gateway_service → context_service → openclaw_runtime →
(local LLM OR cloud LLM) → gateway_service → Telegram

## Pairing Flow

Device ships with secret → pairing code derived User calls /pair/claim
Cloud returns device_token device_agent connects via WebSocket

## Command Flow

Admin → POST /devices/{id}/commands Stored in DB WebSocket hub pushes
command Device acknowledges: - received - running - succeeded - failed -
expired

------------------------------------------------------------------------

# 6. Failure Handling

Cloud outage: - Device continues local operation

Device offline: - Commands expire via TTL

Duplicate commands: - Idempotency key enforced

Skill hash mismatch: - Install blocked

Local LLM timeout: - Escalate to cloud

------------------------------------------------------------------------

# 7. Security Model

-   Device outbound-only connections
-   Token-based authentication
-   Command idempotency keys
-   Skill SHA verification
-   Optional encrypted SQLite at rest

------------------------------------------------------------------------

# 8. Extension Roadmap

-   Marketplace
-   Multi-device ownership
-   Usage billing
-   Advanced RBAC
-   Enterprise mode
