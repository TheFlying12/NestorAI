"""NestorAI Cloud Service — main FastAPI application.

Channels:
- Browser WebSocket →  WebSocket /chat (Clerk JWT auth)
- Conversation history REST → GET /api/conversations/messages
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.auth import get_current_user, get_current_user_ws
from cloud_service.app.context import (
    build_context_messages,
    cleanup_old_messages,
    forget_conversation,
    get_or_create_conversation,
    maybe_update_summary,
    store_message,
)
from cloud_service.app.db import AsyncSessionLocal, create_all_tables, get_db
from cloud_service.app.models import Conversation, ConversationMessage
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

app = FastAPI(title="NestorAI Cloud Service", version="0.3.0")

# H4: multi-tab support — set of connections per user
_browser_ws_sessions: Dict[str, Set[WebSocket]] = {}
_retention_task: Optional[asyncio.Task] = None
_system_llm = None  # cached at startup


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

    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        _system_llm = _make_llm_complete(api_key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)
    else:
        async def _noop(messages):
            return ""
        _system_llm = _noop

    _retention_task = asyncio.create_task(_retention_worker(AsyncSessionLocal))

    logger.info("Cloud service started v0.3.0")


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
        "version": "0.3.0",
        "connected_browsers": sum(len(v) for v in _browser_ws_sessions.values()),
    }


# ─── Conversation history endpoint ────────────────────────────────────────────

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
        sessions = _browser_ws_sessions.get(user_id, set())
        sessions.discard(websocket)
        if not sessions:
            _browser_ws_sessions.pop(user_id, None)
