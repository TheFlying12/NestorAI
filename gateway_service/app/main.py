import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiosqlite
import httpx
import psutil
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="Gateway Service", version="0.2.0")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gateway")
logging.getLogger("httpx").setLevel(logging.WARNING)

PROVIDER = os.getenv("PROVIDER", "telegram").lower()
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

DISPATCH_MAX_RETRIES = int(os.getenv("DISPATCH_MAX_RETRIES", "1"))
DISPATCH_INITIAL_DELAY = 1.0
DISPATCH_TIMEOUT_SECONDS = float(os.getenv("DISPATCH_TIMEOUT_SECONDS", "180"))

CONTEXT_WINDOW_TURNS = int(os.getenv("CONTEXT_WINDOW_TURNS", "12"))
SUMMARY_UPDATE_EVERY_TURNS = int(os.getenv("SUMMARY_UPDATE_EVERY_TURNS", "6"))
SUMMARY_TOKEN_THRESHOLD = int(os.getenv("SUMMARY_TOKEN_THRESHOLD", "3500"))
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "1200"))
SUMMARY_TIMEOUT_SECONDS = float(os.getenv("SUMMARY_TIMEOUT_SECONDS", "30"))
ENABLE_CONTEXT_SUMMARY = os.getenv("ENABLE_CONTEXT_SUMMARY", "true").lower() == "true"
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "90"))
RETENTION_INTERVAL_SECONDS = int(os.getenv("RETENTION_INTERVAL_SECONDS", "86400"))

provider_adapter: Optional["ProviderAdapter"] = None
retention_task: Optional[asyncio.Task] = None


@dataclass
class IncomingMessage:
    provider: str
    user_id: str
    chat_id: str
    text: str


class ProviderAdapter:
    name: str = "unknown"

    async def configure_webhook(self) -> None:
        return

    def validate_secret(self, secret_header: Optional[str]) -> None:
        return

    async def parse_webhook(self, request: Request) -> Optional[IncomingMessage]:
        raise NotImplementedError

    async def send_message(self, chat_id: str, text: str) -> None:
        raise NotImplementedError


class TelegramProviderAdapter(ProviderAdapter):
    name = "telegram"

    async def configure_webhook(self) -> None:
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

        logger.info("Telegram webhook configured")

    def validate_secret(self, secret_header: Optional[str]) -> None:
        if TELEGRAM_WEBHOOK_SECRET and secret_header != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    async def parse_webhook(self, request: Request) -> Optional[IncomingMessage]:
        update = await request.json()
        message = update.get("message") or update.get("edited_message")
        if not message:
            return None

        text = (message.get("text") or "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        user_id = str(message.get("from", {}).get("id", ""))

        if not text or not chat_id or not user_id:
            return None

        return IncomingMessage(provider=self.name, user_id=user_id, chat_id=chat_id, text=text)

    async def send_message(self, chat_id: str, text: str) -> None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()


def _build_provider() -> ProviderAdapter:
    if PROVIDER == "telegram":
        return TelegramProviderAdapter()
    raise RuntimeError(f"Unsupported PROVIDER '{PROVIDER}'")


def _auth_headers() -> Dict[str, str]:
    if OPENCLAW_GATEWAY_TOKEN:
        return {"Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}"}
    return {}


def _ensure_local_target(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "::1", "openclaw", "ollama", "localai"}
    if host not in allowed:
        raise RuntimeError(f"OPENCLAW_URL host '{host}' is not local. Refusing startup.")


def _estimate_tokens(text: str) -> int:
    # Fast approximation good enough for thresholding in MVP.
    return max(1, len(text) // 4)


def _log_resource_warnings() -> None:
    total_ram_gb = psutil.virtual_memory().total / (1024**3)
    if total_ram_gb < RAM_WARN_THRESHOLD_GB:
        logger.warning(
            "Low system RAM detected: %.2fGB < %.2fGB threshold",
            total_ram_gb,
            RAM_WARN_THRESHOLD_GB,
        )

    logger.info(
        "VRAM warning threshold set to %sMB (runtime GPU probing not enabled in MVP)",
        VRAM_WARN_MB,
    )


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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                turn_count INTEGER NOT NULL,
                token_estimate INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, chat_id)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_history_chat_ts ON message_history (chat_id, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_messages_chat_ts ON conversation_messages (chat_id, created_at)"
        )
        await db.commit()


async def _store_message_history(
    provider: str,
    user_id: str,
    chat_id: str,
    direction: str,
    text: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO message_history (provider, user_id, chat_id, direction, message_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, user_id, chat_id, direction, text, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def _store_conversation_message(
    provider: str,
    user_id: str,
    chat_id: str,
    role: str,
    content: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO conversation_messages (provider, user_id, chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, user_id, chat_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def _wait_for_openclaw() -> None:
    health_url = f"{OPENCLAW_URL.rstrip('/')}/health"
    max_attempts = 24
    for i in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(health_url, headers=_auth_headers())
                if response.status_code < 500:
                    logger.info("OpenClaw reachable after %d attempt(s)", i)
                    return
        except httpx.HTTPError:
            pass

        logger.info("Waiting for OpenClaw... attempt %d/%d", i, max_attempts)
        await asyncio.sleep(5)

    logger.error("OpenClaw not reachable after %ds — gateway may return errors", max_attempts * 5)


async def _fetch_summary(user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT summary_text, turn_count, token_estimate
            FROM conversation_summaries
            WHERE user_id = ? AND chat_id = ?
            """,
            (user_id, chat_id),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return {"summary_text": row[0], "turn_count": row[1], "token_estimate": row[2]}


async def _fetch_recent_turns(user_id: str, chat_id: str, limit: int) -> List[Dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT role, content
            FROM conversation_messages
            WHERE user_id = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, chat_id, limit),
        )
        rows = await cursor.fetchall()

    turns = [{"role": role, "content": content} for role, content in reversed(rows)]
    return turns


async def _count_conversation_turns(user_id: str, chat_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM conversation_messages
            WHERE user_id = ? AND chat_id = ?
            """,
            (user_id, chat_id),
        )
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _build_context_messages(user_id: str, chat_id: str, text: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []

    summary = await _fetch_summary(user_id, chat_id)
    if summary and summary["summary_text"].strip():
        messages.append(
            {
                "role": "system",
                "content": f"Conversation summary:\n{summary['summary_text']}",
            }
        )

    recent_turns = await _fetch_recent_turns(user_id, chat_id, CONTEXT_WINDOW_TURNS)
    messages.extend(recent_turns)
    messages.append({"role": "user", "content": text})

    return messages


async def _chat_completion(messages: List[Dict[str, str]], timeout_seconds: float) -> str:
    target = f"{OPENCLAW_URL.rstrip('/')}{OPENCLAW_ROUTE}"
    payload = {
        "model": OPENCLAW_MODEL,
        "stream": False,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(target, json=payload, headers=_auth_headers())
        response.raise_for_status()
        data: Dict[str, Any] = response.json()

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    return "I could not generate a response locally."


async def _dispatch_to_openclaw(user_id: str, chat_id: str, text: str) -> str:
    target = f"{OPENCLAW_URL.rstrip('/')}{OPENCLAW_ROUTE}"
    is_chat_completions = OPENCLAW_ROUTE.rstrip("/").endswith("/v1/chat/completions")
    delay = DISPATCH_INITIAL_DELAY

    for attempt in range(1, DISPATCH_MAX_RETRIES + 1):
        try:
            if is_chat_completions:
                context_messages = await _build_context_messages(user_id=user_id, chat_id=chat_id, text=text)
                return await _chat_completion(messages=context_messages, timeout_seconds=DISPATCH_TIMEOUT_SECONDS)

            async with httpx.AsyncClient(timeout=DISPATCH_TIMEOUT_SECONDS) as client:
                payload = {
                    "source": PROVIDER,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                response = await client.post(target, json=payload, headers=_auth_headers())
                response.raise_for_status()
                data: Dict[str, Any] = response.json()
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

    raise httpx.ConnectError("All retry attempts exhausted")


async def _summarize_conversation(user_id: str, chat_id: str, total_turn_count: int) -> None:
    if not ENABLE_CONTEXT_SUMMARY:
        return

    turns = await _fetch_recent_turns(user_id, chat_id, 40)
    if not turns:
        return

    transcript = "\n".join([f"{turn['role']}: {turn['content']}" for turn in turns])
    summarizer_messages = [
        {
            "role": "system",
            "content": (
                "Summarize this chat for future assistant context. "
                "Include user preferences, open tasks, and important facts. "
                f"Keep it under {SUMMARY_MAX_CHARS} characters."
            ),
        },
        {"role": "user", "content": transcript},
    ]

    try:
        summary_text = await _chat_completion(messages=summarizer_messages, timeout_seconds=SUMMARY_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        logger.warning("Conversation summarization skipped due to upstream error")
        return

    summary_text = summary_text[:SUMMARY_MAX_CHARS]
    token_estimate = _estimate_tokens(summary_text)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO conversation_summaries (user_id, chat_id, summary_text, turn_count, token_estimate, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id)
            DO UPDATE SET
                summary_text = excluded.summary_text,
                turn_count = excluded.turn_count,
                token_estimate = excluded.token_estimate,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                chat_id,
                summary_text,
                total_turn_count,
                token_estimate,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def _maybe_update_summary(user_id: str, chat_id: str) -> None:
    if not ENABLE_CONTEXT_SUMMARY:
        return

    total_turn_count = await _count_conversation_turns(user_id, chat_id)
    summary = await _fetch_summary(user_id, chat_id)
    summarized_turn_count = summary["turn_count"] if summary else 0

    recent_turns = await _fetch_recent_turns(user_id, chat_id, CONTEXT_WINDOW_TURNS)
    estimated_prompt_tokens = sum(_estimate_tokens(turn["content"]) for turn in recent_turns)
    if summary:
        estimated_prompt_tokens += summary["token_estimate"]

    should_refresh = (
        (total_turn_count - summarized_turn_count) >= SUMMARY_UPDATE_EVERY_TURNS
        or estimated_prompt_tokens >= SUMMARY_TOKEN_THRESHOLD
    )

    if should_refresh:
        await _summarize_conversation(user_id=user_id, chat_id=chat_id, total_turn_count=total_turn_count)


async def _forget_conversation(user_id: str, chat_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM conversation_messages WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        await db.execute(
            "DELETE FROM conversation_summaries WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        await db.execute(
            "DELETE FROM message_history WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        await db.commit()


async def _cleanup_old_messages() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MESSAGE_RETENTION_DAYS)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM message_history WHERE created_at < ?", (cutoff,))
        await db.execute("DELETE FROM conversation_messages WHERE created_at < ?", (cutoff,))
        await db.commit()


async def _retention_worker() -> None:
    while True:
        try:
            await _cleanup_old_messages()
        except Exception:
            logger.exception("Retention cleanup failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


async def _process_message(incoming: IncomingMessage) -> None:
    user_id = incoming.user_id
    chat_id = incoming.chat_id
    text = incoming.text

    if text.strip().lower() == "/forget":
        await _forget_conversation(user_id=user_id, chat_id=chat_id)
        try:
            assert provider_adapter is not None
            await provider_adapter.send_message(
                chat_id=chat_id,
                text="Conversation history cleared for this chat.",
            )
        except httpx.HTTPError:
            logger.exception("Provider send failed for forget confirmation")
        return

    await _store_message_history(incoming.provider, user_id, chat_id, "inbound", text)
    await _store_conversation_message(incoming.provider, user_id, chat_id, "user", text)

    try:
        reply = await _dispatch_to_openclaw(user_id=user_id, chat_id=chat_id, text=text)
    except httpx.HTTPError:
        logger.exception("OpenClaw dispatch failed after %d retries", DISPATCH_MAX_RETRIES)
        reply = "Local assistant is currently unavailable. Please try again shortly."

    await _store_message_history(incoming.provider, user_id, chat_id, "outbound", reply)
    await _store_conversation_message(incoming.provider, user_id, chat_id, "assistant", reply)
    await _maybe_update_summary(user_id=user_id, chat_id=chat_id)

    try:
        assert provider_adapter is not None
        await provider_adapter.send_message(chat_id=chat_id, text=reply)
    except httpx.HTTPError:
        logger.exception("Provider send failed")


@app.on_event("startup")
async def startup() -> None:
    global provider_adapter, retention_task

    _ensure_local_target(OPENCLAW_URL)
    provider_adapter = _build_provider()

    await _init_db()
    _log_resource_warnings()
    await _wait_for_openclaw()
    await provider_adapter.configure_webhook()
    await _cleanup_old_messages()

    retention_task = asyncio.create_task(_retention_worker())
    logger.info("Gateway startup complete (provider=%s)", provider_adapter.name)


@app.on_event("shutdown")
async def shutdown() -> None:
    global retention_task

    if retention_task and not retention_task.done():
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "gateway",
        "provider": PROVIDER,
        "context": {
            "window_turns": CONTEXT_WINDOW_TURNS,
            "summary_enabled": ENABLE_CONTEXT_SUMMARY,
            "summary_every_turns": SUMMARY_UPDATE_EVERY_TURNS,
            "retention_days": MESSAGE_RETENTION_DAYS,
        },
    }


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> Dict[str, str]:
    if provider_adapter is None:
        raise HTTPException(status_code=500, detail="Provider not initialized")

    provider_adapter.validate_secret(x_telegram_bot_api_secret_token)

    incoming = await provider_adapter.parse_webhook(request)
    if not incoming:
        return {"status": "ignored", "reason": "no_message"}

    logger.info("Incoming %s message user=%s chat=%s", incoming.provider, incoming.user_id, incoming.chat_id)
    asyncio.create_task(_process_message(incoming))
    return {"status": "accepted"}
