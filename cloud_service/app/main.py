"""NestorAI Cloud Service — main FastAPI application.

Channels:
- Telegram webhook  →  POST /webhook/telegram
- Browser WebSocket →  WebSocket /chat (Clerk JWT auth)

Skill runtime and context engine are embedded in this process.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

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
from cloud_service.app.db import AsyncSessionLocal, create_all_tables, get_db
from cloud_service.app.models import Conversation, ConversationMessage, SkillMemory, User
from cloud_service.app.skills import router as skill_router
from cloud_service.app.skills.router import (
    LLMError,
    SYSTEM_LLM_BASE_URL,
    SYSTEM_LLM_MODEL,
    _make_llm_complete,
    dispatch_stream,
)

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

TELEGRAM_SKILL_ALIASES: Dict[str, str] = {
    "general": "general",
    "budget": "budget_assistant",
    "budget_assistant": "budget_assistant",
}

app = FastAPI(title="NestorAI Cloud Service", version="0.2.0")

# H4: multi-tab support — set of connections per user instead of single WebSocket
_browser_ws_sessions: Dict[str, Set[WebSocket]] = {}
_retention_task: Optional[asyncio.Task] = None
_system_llm = None  # M3: cached at startup


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


# ─── Telegram skill preference helpers (M4) ───────────────────────────────────

async def _get_telegram_skill(user_id: str, db: AsyncSession) -> str:
    result = await db.execute(
        select(SkillMemory).where(
            SkillMemory.user_id == user_id,
            SkillMemory.skill_id == "telegram",
            SkillMemory.key == "preferred_skill",
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return json.loads(row.value_json)
    return TELEGRAM_DEFAULT_SKILL


async def _set_telegram_skill(user_id: str, skill_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(SkillMemory).where(
            SkillMemory.user_id == user_id,
            SkillMemory.skill_id == "telegram",
            SkillMemory.key == "preferred_skill",
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.value_json = json.dumps(skill_id)
    else:
        db.add(SkillMemory(
            user_id=user_id,
            skill_id="telegram",
            key="preferred_skill",
            value_json=json.dumps(skill_id),
        ))
    await db.commit()


# M2: fresh DB session created per background task (no request-scoped db arg)
async def _process_telegram_message(msg: TelegramMessage) -> None:
    async with AsyncSessionLocal() as db:
        user_id = f"telegram:{msg.user_id}"
        channel_id = msg.chat_id
        text = msg.text

        result = await db.execute(select(User).where(User.user_id == user_id))
        if result.scalar_one_or_none() is None:
            db.add(User(user_id=user_id, auth_provider="telegram"))
            await db.commit()

        # Handle /skills command
        if text.strip().lower() == "/skills":
            skills_list = "\n".join(f"\u2022 {k}" for k in TELEGRAM_SKILL_ALIASES.keys())
            await _telegram_send(channel_id, f"Available skills:\n{skills_list}")
            return

        # Handle /skill <name> command
        if text.strip().lower().startswith("/skill"):
            parts = text.strip().split(maxsplit=1)
            requested = parts[1].strip().lower() if len(parts) > 1 else ""
            resolved = TELEGRAM_SKILL_ALIASES.get(requested)
            if resolved:
                await _set_telegram_skill(user_id, resolved, db)
                await _telegram_send(channel_id, f"Switched to skill: {resolved}")
            else:
                skills_list = ", ".join(TELEGRAM_SKILL_ALIASES.keys())
                await _telegram_send(channel_id, f"Unknown skill. Available: {skills_list}")
            return

        skill_id = await _get_telegram_skill(user_id, db)

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

        # Await directly — we're already in a background task, db is still open
        await maybe_update_summary(conv_id, _system_llm, db)


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
    global _retention_task, _system_llm

    if os.getenv("AUTO_MIGRATE", "false").lower() == "true":
        await create_all_tables()
        logger.info("Database tables created (AUTO_MIGRATE=true)")

    await _telegram_configure_webhook()

    # M3: cache system LLM callable once at startup rather than rebuilding per message
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        _system_llm = _make_llm_complete(api_key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)
    else:
        async def _noop(messages):
            return ""
        _system_llm = _noop

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
        "connected_browsers": sum(len(v) for v in _browser_ws_sessions.values()),
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
) -> Dict[str, str]:
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body = await request.json()
    msg = _parse_telegram_update(body)
    if not msg:
        return {"status": "ignored", "reason": "no_message"}

    logger.info("Telegram message user=%s chat=%s", msg.user_id, msg.chat_id)
    asyncio.create_task(_process_telegram_message(msg))
    return {"status": "accepted"}


# ─── Conversation history endpoint (M5) ───────────────────────────────────────

@app.get("/api/conversations/messages")
async def get_conversation_messages(
    skill_id: str = "general",
    limit: int = 50,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.channel == "web",
            Conversation.skill_id == skill_id,
        )
    )
    convo = result.scalar_one_or_none()
    if not convo:
        return {"messages": []}

    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == convo.conversation_id)
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
    )
    msgs = result.scalars().all()
    return {
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in reversed(msgs)
            if m.role in ("user", "assistant")
        ]
    }


# ─── Browser WebSocket chat ────────────────────────────────────────────────────

@app.websocket("/chat")
async def browser_chat(
    websocket: WebSocket,
    user_id: str = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    # H4: support multiple tabs — store all connections for this user in a set
    _browser_ws_sessions.setdefault(user_id, set()).add(websocket)
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

            # H1: stream tokens to client as they arrive
            accumulated: List[str] = []
            try:
                async for token in dispatch_stream(
                    user_id=user_id,
                    text=text,
                    skill_id=skill_id,
                    context_messages=context_msgs,
                    db=db,
                ):
                    accumulated.append(token)
                    await websocket.send_json({"type": "token", "text": token})
            except LLMError as exc:
                accumulated = [str(exc)]
                await websocket.send_json({"type": "token", "text": str(exc)})
            except Exception:
                logger.exception("Skill dispatch_stream failed user_id=%s", user_id)
                accumulated = ["Something went wrong. Please try again."]
                await websocket.send_json({"type": "token", "text": accumulated[0]})

            full_reply = "".join(accumulated)
            await store_message(conv_id, "assistant", full_reply, db)
            await websocket.send_json({"type": "reply", "text": full_reply})

            asyncio.create_task(maybe_update_summary(conv_id, _system_llm, db))

    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected user_id=%s", user_id)
    except Exception:
        logger.exception("Browser WebSocket error user_id=%s", user_id)
    finally:
        # H4: remove only this connection, not all connections for this user
        sessions = _browser_ws_sessions.get(user_id, set())
        sessions.discard(websocket)
        if not sessions:
            _browser_ws_sessions.pop(user_id, None)
