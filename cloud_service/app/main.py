"""NestorAI Cloud Service — main FastAPI application.

Channels:
- Browser WebSocket →  WebSocket /chat (Clerk JWT auth)
- Conversation history REST → GET /api/conversations/messages
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.auth import get_current_user, store_user_llm_key, verify_ws_token
from cloud_service.app.context import (
    build_context_messages,
    cleanup_old_messages,
    forget_conversation,
    get_or_create_conversation,
    maybe_update_summary,
    store_message,
)
from cloud_service.app.db import AsyncSessionLocal, create_all_tables, get_db
from cloud_service.app.models import Conversation, ConversationMessage, NotificationLog, User, UserSkillChannel
from cloud_service.app.notifications import scheduler as notification_scheduler
from cloud_service.app.skills import router as skill_router
from cloud_service.app.skills.router import (
    LLMError,
    SYSTEM_LLM_BASE_URL,
    SYSTEM_LLM_MODEL,
    _make_llm_complete,
    _resolve_llm_complete,
    dispatch_stream,
)

_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cloud")

# ─── Config ───────────────────────────────────────────────────────────────────

HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "90"))
RETENTION_INTERVAL_SECONDS = int(os.getenv("RETENTION_INTERVAL_SECONDS", "86400"))
_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]

app = FastAPI(title="NestorAI Cloud Service", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# H4: multi-tab support — set of connections per user
_browser_ws_sessions: Dict[str, Set[WebSocket]] = {}
_retention_task: Optional[asyncio.Task] = None
_system_llm = None  # cached at startup


# ─── Startup / Shutdown ────────────────────────────────────────────────────────

async def _run_summary(conv_id: str, user_id: str) -> None:
    """Background summarization with its own DB session and BYOK-aware LLM resolution."""
    async with AsyncSessionLocal() as db:
        try:
            llm = await _resolve_llm_complete(user_id, db)
        except ValueError:
            if _system_llm is None:
                return
            llm = _system_llm
        await maybe_update_summary(conv_id, llm, db)


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
    notification_scheduler.start()

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
    notification_scheduler.shutdown(wait=False)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "cloud",
        "version": "0.3.0",
        "connected_browsers": sum(len(v) for v in _browser_ws_sessions.values()),
    }


# ─── Auth endpoints ───────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    api_key: str


@app.post("/api/auth/apikey")
async def store_api_key(
    body: ApiKeyRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if not body.api_key.strip():
        raise HTTPException(400, "api_key must not be empty")
    try:
        await store_user_llm_key(user_id, body.api_key.strip(), db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "ok"}


@app.get("/api/auth/me")
async def get_me(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    return {
        "user_id": user_id,
        "email": user.email if user else None,
        "has_llm_key": bool(user and user.api_key_encrypted),
        "phone_number": user.phone_number if user else None,
        "notification_email": user.notification_email if user else None,
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


# ─── Contact info endpoints ───────────────────────────────────────────────────

class PhoneUpdate(BaseModel):
    phone_number: str


class NotificationEmailUpdate(BaseModel):
    notification_email: str


@app.post("/api/me/phone")
async def set_phone(
    body: PhoneUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if not _E164_RE.match(body.phone_number):
        raise HTTPException(400, "Invalid phone number. Use E.164 format, e.g. +14155550100")
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.phone_number = body.phone_number
    await db.commit()
    return {"status": "ok"}


@app.post("/api/me/notification-email")
async def set_notification_email(
    body: NotificationEmailUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if not _EMAIL_RE.match(body.notification_email):
        raise HTTPException(400, "Invalid email address")
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.notification_email = body.notification_email
    await db.commit()
    return {"status": "ok"}


# ─── Skill channel preference endpoints ───────────────────────────────────────

_VALID_CHANNELS = {"web", "sms", "email"}


class SkillChannelUpdate(BaseModel):
    skill_id: str
    channel: str  # 'web' | 'sms' | 'email'


@app.get("/api/me/skill-channels")
async def get_skill_channels(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(
        select(UserSkillChannel).where(UserSkillChannel.user_id == user_id)
    )
    rows = result.scalars().all()
    return {
        "channels": [{"skill_id": r.skill_id, "channel": r.channel} for r in rows]
    }


@app.post("/api/me/skill-channel")
async def set_skill_channel(
    body: SkillChannelUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if body.channel not in _VALID_CHANNELS:
        raise HTTPException(400, f"channel must be one of: {', '.join(sorted(_VALID_CHANNELS))}")
    result = await db.execute(
        select(UserSkillChannel).where(
            UserSkillChannel.user_id == user_id,
            UserSkillChannel.skill_id == body.skill_id,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.channel = body.channel
    else:
        db.add(UserSkillChannel(user_id=user_id, skill_id=body.skill_id, channel=body.channel))
    await db.commit()
    return {"status": "ok"}


# ─── Twilio inbound SMS webhook ────────────────────────────────────────────────

_TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
_TWILIO_WEBHOOK_URL = os.environ.get("TWILIO_WEBHOOK_URL", "")
_TWIML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@app.post("/webhooks/twilio/sms")
async def twilio_sms_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    form = await request.form()
    from_number: str = form.get("From", "")
    body_text: str = form.get("Body", "")

    # Validate Twilio signature when credentials are configured
    if _TWILIO_ACCOUNT_SID:
        from cloud_service.app.integrations.twilio_client import validate_signature
        signature = request.headers.get("X-Twilio-Signature", "")
        webhook_url = _TWILIO_WEBHOOK_URL or str(request.url)
        params = {k: v for k, v in form.items()}
        if not validate_signature(webhook_url, params, signature):
            logger.warning("Invalid Twilio signature from=%s", from_number)
            raise HTTPException(403, "Invalid Twilio signature")

    from cloud_service.app.integrations.twilio_client import send_sms

    # Look up user by phone number
    result = await db.execute(select(User).where(User.phone_number == from_number))
    user = result.scalar_one_or_none()

    if not user:
        await send_sms(
            from_number,
            "This number isn't linked to a Nestor account. Visit the app to connect your phone.",
        )
        return Response(content=_TWIML_EMPTY, media_type="application/xml")

    if not body_text.strip():
        return Response(content=_TWIML_EMPTY, media_type="application/xml")

    # Route through context + skill dispatch (channel="sms" isolates SMS history from web)
    conv_id = await get_or_create_conversation(user.user_id, "sms", from_number, "general", db)
    context_msgs = await build_context_messages(conv_id, body_text, db)
    await store_message(conv_id, "user", body_text, db)

    reply_tokens: List[str] = []
    try:
        async for token in dispatch_stream(
            user_id=user.user_id,
            text=body_text,
            skill_id="general",
            context_messages=context_msgs,
            db=db,
        ):
            reply_tokens.append(token)
    except Exception:
        logger.exception("SMS dispatch failed user_id=%s", user.user_id)
        reply_tokens = ["Sorry, something went wrong. Please try again."]

    reply = "".join(reply_tokens)[:1600]
    await store_message(conv_id, "assistant", reply, db)

    await send_sms(from_number, reply)

    db.add(
        NotificationLog(
            user_id=user.user_id,
            channel="sms",
            type="inbound_reply",
            to_address=from_number,
            body=reply,
            status="sent",
        )
    )
    await db.commit()

    asyncio.create_task(_run_summary(conv_id, user.user_id))
    logger.info("SMS handled user_id=%s reply_len=%d", user.user_id, len(reply))

    return Response(content=_TWIML_EMPTY, media_type="application/xml")


# ─── Browser WebSocket chat ────────────────────────────────────────────────────

@app.websocket("/chat")
async def browser_chat(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Authenticate before accepting — closes with 1008 on failure
    try:
        user_id = await verify_ws_token(token, db)
    except HTTPException:
        await websocket.close(code=1008)
        return

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

            # Resolve delivery channel preference for this skill
            ch_result = await db.execute(
                select(UserSkillChannel).where(
                    UserSkillChannel.user_id == user_id,
                    UserSkillChannel.skill_id == skill_id,
                )
            )
            ch_row = ch_result.scalar_one_or_none()
            delivery_channel = ch_row.channel if ch_row else "web"

            conv_id = await get_or_create_conversation(user_id, "web", user_id, skill_id, db)
            # Build context BEFORE storing so the current user message isn't
            # fetched from DB and then appended a second time by build_context_messages.
            context_msgs = await build_context_messages(conv_id, text, db)
            await store_message(conv_id, "user", text, db)

            if delivery_channel == "web":
                # Default: stream tokens to WebSocket
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
                    logger.warning("LLM error user_id=%s skill=%s: %s", user_id, skill_id, exc)
                    accumulated = [str(exc)]
                    await websocket.send_json({"type": "token", "text": str(exc)})
                except Exception:
                    logger.exception("Skill dispatch_stream failed user_id=%s", user_id)
                    accumulated = ["Something went wrong. Please try again."]
                    await websocket.send_json({"type": "token", "text": accumulated[0]})

                full_reply = "".join(accumulated)
                await store_message(conv_id, "assistant", full_reply, db)
                await websocket.send_json({"type": "reply", "text": full_reply})

            else:
                # SMS or email: collect full reply, send out-of-band, notify web with redirect frame
                user_result = await db.execute(select(User).where(User.user_id == user_id))
                user_obj = user_result.scalar_one_or_none()

                if delivery_channel == "sms" and not (user_obj and user_obj.phone_number):
                    await websocket.send_json({"type": "error", "text": "No phone number on file. Add one in Account settings."})
                    continue
                if delivery_channel == "email" and not (user_obj and user_obj.notification_email):
                    await websocket.send_json({"type": "error", "text": "No notification email on file. Add one in Account settings."})
                    continue

                accumulated_offband: List[str] = []
                try:
                    async for token in dispatch_stream(
                        user_id=user_id,
                        text=text,
                        skill_id=skill_id,
                        context_messages=context_msgs,
                        db=db,
                    ):
                        accumulated_offband.append(token)
                except LLMError as exc:
                    logger.warning("LLM error (offband) user_id=%s skill=%s: %s", user_id, skill_id, exc)
                    accumulated_offband = [str(exc)]
                except Exception:
                    logger.exception("Skill dispatch_stream (offband) failed user_id=%s", user_id)
                    accumulated_offband = ["Something went wrong. Please try again."]

                full_reply = "".join(accumulated_offband)
                await store_message(conv_id, "assistant", full_reply, db)

                if delivery_channel == "sms":
                    from cloud_service.app.integrations.twilio_client import send_sms
                    phone = user_obj.phone_number
                    try:
                        await send_sms(phone, full_reply[:1600])
                    except Exception:
                        logger.exception("send_sms (offband) failed user_id=%s", user_id)
                    masked = phone[:3] + "..." + phone[-3:]
                    db.add(NotificationLog(
                        user_id=user_id,
                        channel="sms",
                        type="agent_send",
                        to_address=phone,
                        body=full_reply[:1600],
                        status="sent",
                    ))
                    await db.commit()
                    await websocket.send_json({"type": "channel_redirect", "channel": "sms", "masked_to": masked})

                else:  # email
                    from cloud_service.app.integrations.resend_client import send_email
                    notif_email = user_obj.notification_email
                    try:
                        await send_email(notif_email, "Nestor reply", f"<pre style='white-space:pre-wrap'>{full_reply}</pre>")
                    except Exception:
                        logger.exception("send_email (offband) failed user_id=%s", user_id)
                    db.add(NotificationLog(
                        user_id=user_id,
                        channel="email",
                        type="agent_send",
                        to_address=notif_email,
                        body=full_reply,
                        status="sent",
                    ))
                    await db.commit()
                    await websocket.send_json({"type": "channel_redirect", "channel": "email"})

            asyncio.create_task(_run_summary(conv_id, user_id))

    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected user_id=%s", user_id)
    except Exception:
        logger.exception("Browser WebSocket error user_id=%s", user_id)
    finally:
        sessions = _browser_ws_sessions.get(user_id, set())
        sessions.discard(websocket)
        if not sessions:
            _browser_ws_sessions.pop(user_id, None)
