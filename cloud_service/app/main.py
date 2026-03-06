"""NestorAI Cloud Service — main FastAPI application.

Channels:
- Telegram webhook  →  POST /webhook/telegram
- Browser WebSocket →  WebSocket /chat (Clerk JWT auth)

Skill runtime and context engine are embedded in this process.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.auth import (
    ApiKeyRequest,
    MeResponse,
    get_current_user,
    get_current_user_ws,
    get_me,
    store_api_key,
)
from cloud_service.app.context import (
    build_context_messages,
    cleanup_old_messages,
    forget_conversation,
    get_or_create_conversation,
    maybe_update_summary,
    store_message,
)
from cloud_service.app.db import create_all_tables, get_db
from cloud_service.app.models import User
from cloud_service.app.skills import router as skill_router

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cloud")

# ─── Config ───────────────────────────────────────────────────────────────────

HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "90"))
RETENTION_INTERVAL_SECONDS = int(os.getenv("RETENTION_INTERVAL_SECONDS", "86400"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_DEFAULT_SKILL = os.getenv("TELEGRAM_DEFAULT_SKILL", "general")

app = FastAPI(title="NestorAI Cloud Service", version="0.2.0")

# Browser WebSocket sessions: user_id → WebSocket
_browser_ws_sessions: Dict[str, WebSocket] = {}
_retention_task: Optional[asyncio.Task] = None


# ─── Telegram adapter ─────────────────────────────────────────────────────────

@dataclass
class TelegramMessage:
    user_id: str
    chat_id: str
    text: str


async def _telegram_configure_webhook() -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_URL:
        logger.info("Telegram webhook not configured (missing token or URL)")
        return
    if not TELEGRAM_WEBHOOK_URL.startswith("https://"):
        logger.error("TELEGRAM_WEBHOOK_URL must use https://")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {
        "url": TELEGRAM_WEBHOOK_URL.rstrip("/") + "/webhook/telegram",
        "secret_token": TELEGRAM_WEBHOOK_SECRET or None,
        "allowed_updates": ["message", "edited_message"],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(api_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram webhook setup failed: %s", data)
            return
        logger.info("Telegram webhook configured url=%s", TELEGRAM_WEBHOOK_URL)
    except httpx.HTTPError:
        logger.exception("Failed to configure Telegram webhook")


async def _telegram_send(chat_id: str, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        response.raise_for_status()


def _parse_telegram_update(update: Dict[str, Any]) -> Optional[TelegramMessage]:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None
    text = (message.get("text") or "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))
    if not text or not chat_id or not user_id:
        return None
    return TelegramMessage(user_id=user_id, chat_id=chat_id, text=text)


async def _process_telegram_message(msg: TelegramMessage, db: AsyncSession) -> None:
    user_id = f"telegram:{msg.user_id}"
    channel_id = msg.chat_id
    text = msg.text

    result = await db.execute(select(User).where(User.user_id == user_id))
    if result.scalar_one_or_none() is None:
        db.add(User(user_id=user_id, auth_provider="telegram"))
        await db.commit()

    skill_id = TELEGRAM_DEFAULT_SKILL

    if text.strip().lower() == "/forget":
        conv_id = await get_or_create_conversation(user_id, "telegram", channel_id, skill_id, db)
        await forget_conversation(conv_id, db)
        await _telegram_send(channel_id, "Conversation history cleared.")
        return

    conv_id = await get_or_create_conversation(user_id, "telegram", channel_id, skill_id, db)
    await store_message(conv_id, "user", text, db)
    context_msgs = await build_context_messages(conv_id, text, db)

    try:
        reply = await skill_router.dispatch(
            user_id=user_id,
            text=text,
            skill_id=skill_id,
            context_messages=context_msgs,
            db=db,
        )
    except Exception:
        logger.exception("Skill dispatch failed for telegram user=%s", user_id)
        reply = "Something went wrong. Please try again shortly."

    await store_message(conv_id, "assistant", reply, db)

    try:
        await _telegram_send(channel_id, reply)
    except httpx.HTTPError:
        logger.exception("Failed to send Telegram reply chat_id=%s", channel_id)

    asyncio.create_task(maybe_update_summary(conv_id, _system_llm_complete(), db))


def _system_llm_complete():
    from cloud_service.app.skills.router import _make_llm_complete, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        async def _noop(messages):
            return ""
        return _noop
    return _make_llm_complete(api_key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)


# ─── Startup / Shutdown ────────────────────────────────────────────────────────

async def _retention_worker(db_factory) -> None:
    while True:
        try:
            async with db_factory() as db:
                await cleanup_old_messages(db)
        except Exception:
            logger.exception("Retention cleanup failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup() -> None:
    global _retention_task

    if os.getenv("AUTO_MIGRATE", "false").lower() == "true":
        await create_all_tables()
        logger.info("Database tables created (AUTO_MIGRATE=true)")

    await _telegram_configure_webhook()

    from cloud_service.app.db import AsyncSessionLocal
    _retention_task = asyncio.create_task(_retention_worker(AsyncSessionLocal))

    logger.info("Cloud service started v0.2.0")


@app.on_event("shutdown")
async def shutdown() -> None:
    global _retention_task
    if _retention_task and not _retention_task.done():
        _retention_task.cancel()
        try:
            await _retention_task
        except asyncio.CancelledError:
            pass


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "cloud",
        "version": "0.2.0",
        "connected_browsers": len(_browser_ws_sessions),
        "telegram_enabled": bool(TELEGRAM_BOT_TOKEN),
    }


# ─── Auth endpoints ───────────────────────────────────────────────────────────

app.post("/api/auth/apikey")(store_api_key)
app.get("/api/auth/me", response_model=MeResponse)(get_me)


# ─── Telegram webhook ─────────────────────────────────────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body = await request.json()
    msg = _parse_telegram_update(body)
    if not msg:
        return {"status": "ignored", "reason": "no_message"}

    logger.info("Telegram message user=%s chat=%s", msg.user_id, msg.chat_id)
    asyncio.create_task(_process_telegram_message(msg, db))
    return {"status": "accepted"}


# ─── Browser WebSocket chat ────────────────────────────────────────────────────

@app.websocket("/chat")
async def browser_chat(
    websocket: WebSocket,
    user_id: str = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    _browser_ws_sessions[user_id] = websocket
    logger.info("Browser WebSocket connected user_id=%s", user_id)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=HEARTBEAT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.info("Browser WS timeout user_id=%s", user_id)
                break

            frame_type = raw.get("type", "message")
            if frame_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if frame_type != "message":
                continue

            text = (raw.get("text") or "").strip()
            skill_id = raw.get("skill_id", "general")
            if not text:
                continue

            if text.lower() == "/forget":
                conv_id = await get_or_create_conversation(user_id, "web", user_id, skill_id, db)
                await forget_conversation(conv_id, db)
                await websocket.send_json({"type": "reply", "text": "Conversation history cleared."})
                continue

            await websocket.send_json({"type": "typing"})

            conv_id = await get_or_create_conversation(user_id, "web", user_id, skill_id, db)
            await store_message(conv_id, "user", text, db)
            context_msgs = await build_context_messages(conv_id, text, db)

            try:
                reply = await skill_router.dispatch(
                    user_id=user_id,
                    text=text,
                    skill_id=skill_id,
                    context_messages=context_msgs,
                    db=db,
                )
            except Exception:
                logger.exception("Skill dispatch failed user_id=%s", user_id)
                reply = "Something went wrong. Please try again."

            await store_message(conv_id, "assistant", reply, db)
            await websocket.send_json({"type": "reply", "text": reply})

            asyncio.create_task(maybe_update_summary(conv_id, _system_llm_complete(), db))

    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected user_id=%s", user_id)
    except Exception:
        logger.exception("Browser WebSocket error user_id=%s", user_id)
    finally:
        _browser_ws_sessions.pop(user_id, None)
