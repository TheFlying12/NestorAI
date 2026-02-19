import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiosqlite
import httpx
import psutil
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="Gateway Service", version="0.1.0")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gateway")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:8080")
OPENCLAW_ROUTE = os.getenv("OPENCLAW_ROUTE", "/v1/skills/dispatch")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw")
DB_PATH = os.getenv("DB_PATH", "/data/gateway.db")
RAM_WARN_THRESHOLD_GB = float(os.getenv("RAM_WARN_THRESHOLD_GB", "2.0"))
VRAM_WARN_MB = int(os.getenv("VRAM_WARN_MB", "2048"))

DISPATCH_MAX_RETRIES = 3
DISPATCH_INITIAL_DELAY = 1.0


def _auth_headers() -> Dict[str, str]:
    if OPENCLAW_GATEWAY_TOKEN:
        return {"Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}"}
    return {}


def _ensure_local_target(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "::1", "openclaw", "ollama", "localai"}
    if host not in allowed:
        raise RuntimeError(f"OPENCLAW_URL host '{host}' is not local. Refusing startup.")


async def _init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


def _log_resource_warnings() -> None:
    total_ram_gb = psutil.virtual_memory().total / (1024**3)
    if total_ram_gb < RAM_WARN_THRESHOLD_GB:
        logger.warning(
            "Low system RAM detected: %.2fGB < %.2fGB threshold",
            total_ram_gb,
            RAM_WARN_THRESHOLD_GB,
        )

    # GPU/VRAM detection is platform-dependent and optional in MVP.
    logger.info(
        "VRAM warning threshold set to %sMB (runtime GPU probing not enabled in MVP)",
        VRAM_WARN_MB,
    )


async def _store_message(provider: str, user_id: str, chat_id: str, direction: str, text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO message_history (provider, user_id, chat_id, direction, message_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                user_id,
                chat_id,
                direction,
                text,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def _wait_for_openclaw() -> None:
    """Block startup until OpenClaw is reachable (up to ~120s)."""
    health_url = f"{OPENCLAW_URL.rstrip('/')}/health"
    max_attempts = 24
    for i in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(health_url, headers=_auth_headers())
                if r.status_code < 500:
                    logger.info("OpenClaw reachable after %d attempt(s)", i)
                    return
        except httpx.HTTPError:
            pass
        logger.info("Waiting for OpenClaw... attempt %d/%d", i, max_attempts)
        await asyncio.sleep(5)
    logger.error("OpenClaw not reachable after %ds — gateway may return errors", max_attempts * 5)


async def _configure_telegram_webhook() -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_URL:
        logger.info("Telegram webhook not configured (missing token or webhook URL).")
        return

    if not TELEGRAM_WEBHOOK_URL.startswith("https://"):
        logger.error("TELEGRAM_WEBHOOK_URL must be https:// for Telegram webhooks.")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {
        "url": TELEGRAM_WEBHOOK_URL.rstrip("/") + "/webhook/telegram",
        "secret_token": TELEGRAM_WEBHOOK_SECRET or None,
        "allowed_updates": ["message", "edited_message"],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        logger.exception("Failed to configure Telegram webhook")
        return

    if not data.get("ok"):
        logger.error("Telegram webhook configuration failed: %s", data)
        return

    logger.info("Telegram webhook configured: %s", payload["url"])


async def _dispatch_to_openclaw(user_id: str, chat_id: str, text: str) -> str:
    target = f"{OPENCLAW_URL.rstrip('/')}{OPENCLAW_ROUTE}"
    is_chat_completions = OPENCLAW_ROUTE.rstrip("/").endswith("/v1/chat/completions")
    delay = DISPATCH_INITIAL_DELAY

    for attempt in range(1, DISPATCH_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if is_chat_completions:
                    payload = {
                        "model": OPENCLAW_MODEL,
                        "stream": False,
                        "messages": [{"role": "user", "content": text}],
                    }
                else:
                    payload = {
                        "source": "telegram",
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "text": text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                response = await client.post(target, json=payload, headers=_auth_headers())
                response.raise_for_status()
                data: Dict[str, Any] = response.json()

            if is_chat_completions:
                choices = data.get("choices") or []
                if choices:
                    message = choices[0].get("message") or {}
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                return "I could not generate a response locally."

            # Support a few common response shapes for compatibility.
            return (
                data.get("reply")
                or data.get("message")
                or data.get("output")
                or "I could not generate a response locally."
            )
        except httpx.HTTPError:
            if attempt == DISPATCH_MAX_RETRIES:
                raise
            logger.warning(
                "OpenClaw dispatch attempt %d/%d failed, retrying in %.1fs",
                attempt,
                DISPATCH_MAX_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

    # Should never reach here, but satisfy the type checker.
    raise httpx.ConnectError("All retry attempts exhausted")


async def _send_telegram_message(chat_id: str, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(api_url, json=payload)
        response.raise_for_status()


@app.on_event("startup")
async def startup() -> None:
    _ensure_local_target(OPENCLAW_URL)
    await _init_db()
    _log_resource_warnings()
    await _wait_for_openclaw()
    await _configure_telegram_webhook()
    logger.info("Gateway startup complete")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> Dict[str, str]:
    if TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    text = (message.get("text") or "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))

    if not text or not chat_id or not user_id:
        return {"status": "ignored", "reason": "incomplete_message"}

    logger.info("Incoming telegram message user=%s chat=%s", user_id, chat_id)
    await _store_message("telegram", user_id, chat_id, "inbound", text)

    try:
        reply = await _dispatch_to_openclaw(user_id=user_id, chat_id=chat_id, text=text)
    except httpx.HTTPError:
        logger.exception("OpenClaw dispatch failed after %d retries", DISPATCH_MAX_RETRIES)
        reply = "Local assistant is currently unavailable. Please try again shortly."

    await _store_message("telegram", user_id, chat_id, "outbound", reply)

    try:
        await _send_telegram_message(chat_id=chat_id, text=reply)
    except httpx.HTTPError:
        logger.exception("Telegram send failed")
        raise HTTPException(status_code=502, detail="Failed to send Telegram response")

    return {"status": "ok"}
