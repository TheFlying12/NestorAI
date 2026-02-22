import asyncio
import logging
import os
import tempfile
import time
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

START_TIME = time.monotonic()

PROVIDER = os.getenv("PROVIDER", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:8080")
OPENCLAW_ROUTE = os.getenv("OPENCLAW_ROUTE", "/v1/skills/dispatch")
DB_PATH = os.getenv("DB_PATH", "/data/gateway.db")
RAM_WARN_THRESHOLD_GB = float(os.getenv("RAM_WARN_THRESHOLD_GB", "2.0"))
VRAM_WARN_MB = int(os.getenv("VRAM_WARN_MB", "2048"))


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


def _validate_telegram_config() -> None:
    if PROVIDER.lower() != "telegram":
        return

    if TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN present")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN missing for telegram provider")

    if "TELEGRAM_WEBHOOK_URL" in os.environ:
        if TELEGRAM_WEBHOOK_URL:
            parsed = urlparse(TELEGRAM_WEBHOOK_URL)
            if parsed.scheme != "https" or not parsed.netloc:
                logger.warning("TELEGRAM_WEBHOOK_URL must be https:// and include a host")
            else:
                logger.info("TELEGRAM_WEBHOOK_URL present")
        else:
            logger.warning("TELEGRAM_WEBHOOK_URL set but empty")

    if "TELEGRAM_WEBHOOK_SECRET" in os.environ:
        if TELEGRAM_WEBHOOK_SECRET:
            logger.info("TELEGRAM_WEBHOOK_SECRET present")
        else:
            logger.warning("TELEGRAM_WEBHOOK_SECRET set but empty")


async def _store_message(provider: str, user_id: str, chat_id: str, direction: str, text: str) -> None:
    try:
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
    except Exception:
        logger.exception("Failed to store message in gateway DB")


async def _check_openclaw_reachable() -> bool:
    base = OPENCLAW_URL.rstrip("/")
    targets = [base, f"{base}{OPENCLAW_ROUTE}"]
    timeout = httpx.Timeout(1.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for target in targets:
            try:
                await client.head(target)
                return True
            except httpx.HTTPError:
                try:
                    await client.get(target)
                    return True
                except httpx.HTTPError:
                    continue
    return False


async def _check_db_writable() -> bool:
    def _try_write_temp(path: str) -> bool:
        directory = os.path.dirname(path) or "."
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=True):
                return True
        except OSError:
            return False

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
    except Exception:
        return False

    return await asyncio.to_thread(_try_write_temp, DB_PATH)


async def _dispatch_to_openclaw(user_id: str, chat_id: str, text: str) -> str:
    payload = {
        "source": "telegram",
        "user_id": user_id,
        "chat_id": chat_id,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    target = f"{OPENCLAW_URL.rstrip('/')}{OPENCLAW_ROUTE}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(target, json=payload)
        response.raise_for_status()
        data: Dict[str, Any] = response.json()

    # Support a few common response shapes for compatibility.
    return (
        data.get("reply")
        or data.get("message")
        or data.get("output")
        or "I could not generate a response locally."
    )


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
    _validate_telegram_config()
    logger.info("Gateway startup complete")


@app.get("/health")
async def health() -> Dict[str, Any]:
    # Health stays 200 to enable basic liveness even if dependencies are degraded.
    openclaw_reachable, db_writable = await asyncio.gather(
        _check_openclaw_reachable(),
        _check_db_writable(),
    )
    return {
        "status": "ok",
        "uptime_s": round(time.monotonic() - START_TIME, 3),
        "provider": PROVIDER or "unknown",
        "openclaw_reachable": openclaw_reachable,
        "db_writable": db_writable,
    }


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
        logger.exception("OpenClaw dispatch failed")
        reply = "Local assistant is currently unavailable. Please try again shortly."

    await _store_message("telegram", user_id, chat_id, "outbound", reply)

    try:
        await _send_telegram_message(chat_id=chat_id, text=reply)
    except httpx.HTTPError:
        logger.exception("Telegram send failed")
        raise HTTPException(status_code=502, detail="Failed to send Telegram response")

    return {"status": "ok"}
