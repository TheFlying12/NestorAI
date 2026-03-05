"""NestorAI Cloud Service — main FastAPI application.

Responsibilities:
- Device management (pairing, commands, WebSocket hub) — Phase 1, preserved
- Telegram webhook ingestion + reply — Phase 2
- Browser WebSocket chat endpoint (/chat) — Phase 2
- Cloud skill runtime dispatch via skills.router — Phase 2
- Auth endpoints (Clerk JWT + Fernet API key) — Phase 2
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from pydantic import BaseModel
from sqlalchemy import select, update
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
from cloud_service.app.models import Command, Device, PairingCode, TransferNonce, User
from cloud_service.app.skills import router as skill_router

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cloud")

# ─── Config ───────────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("CLOUD_SECRET_KEY", "")
COMMAND_TTL_HOURS = int(os.getenv("COMMAND_TTL_HOURS", "24"))
TRANSFER_NONCE_TTL_MINUTES = int(os.getenv("TRANSFER_NONCE_TTL_MINUTES", "10"))
HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "90"))
RETENTION_INTERVAL_SECONDS = int(os.getenv("RETENTION_INTERVAL_SECONDS", "86400"))

# Telegram config (optional — only needed if TELEGRAM_BOT_TOKEN is set)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
# Default skill for Telegram users who haven't set a preference
TELEGRAM_DEFAULT_SKILL = os.getenv("TELEGRAM_DEFAULT_SKILL", "general")

app = FastAPI(title="NestorAI Cloud Service", version="0.2.0")

# ─── In-memory WebSocket registry ────────────────────────────────────────────
# device_id -> WebSocket. Single-node MVP; replace with Redis pub/sub for multi-node.
_device_ws_sessions: Dict[str, WebSocket] = {}
# user_id -> WebSocket (browser chat sessions)
_browser_ws_sessions: Dict[str, WebSocket] = {}

_retention_task: Optional[asyncio.Task] = None


# ─── Security helpers ─────────────────────────────────────────────────────────

def _hash_secret(value: str) -> str:
    if not SECRET_KEY:
        raise RuntimeError("CLOUD_SECRET_KEY is not configured")
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _verify_token(raw_token: str, stored_hash: str) -> bool:
    expected = _hash_secret(raw_token)
    return hmac.compare_digest(expected, stored_hash)


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer "):]


async def _authenticate_device(authorization: Optional[str], db: AsyncSession) -> Device:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    parts = token.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed device token")
    device_id, raw_token = parts

    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if not device or not _verify_token(raw_token, device.device_token_hash):
        raise HTTPException(status_code=401, detail="Invalid device credentials")
    return device


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
    """Handle a Telegram message through the cloud skill runtime."""
    user_id = f"telegram:{msg.user_id}"
    channel_id = msg.chat_id
    text = msg.text

    # Ensure user row exists (Telegram users get a synthetic user_id)
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
        logger.exception("Failed to send Telegram reply to chat_id=%s", channel_id)

    # Non-critical background task
    asyncio.create_task(
        maybe_update_summary(conv_id, _make_system_llm_complete(), db)
    )


def _make_system_llm_complete():
    """System-level LLM callable for summarization (uses OPENAI_API_KEY)."""
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

    if not SECRET_KEY:
        logger.error("CLOUD_SECRET_KEY is not set — token operations will fail")

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
        "connected_devices": len(_device_ws_sessions),
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

class ChatInbound(BaseModel):
    type: str = "message"
    text: str = ""
    skill_id: str = "general"


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

            # Send typing indicator before dispatch
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
                logger.exception("Skill dispatch failed for user_id=%s", user_id)
                reply = "Something went wrong. Please try again."

            await store_message(conv_id, "assistant", reply, db)
            await websocket.send_json({"type": "reply", "text": reply})

            # Non-critical background summarization
            asyncio.create_task(
                maybe_update_summary(conv_id, _make_system_llm_complete(), db)
            )

    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected user_id=%s", user_id)
    except Exception:
        logger.exception("Browser WebSocket error user_id=%s", user_id)
    finally:
        _browser_ws_sessions.pop(user_id, None)


# ─── Pydantic models (device management) ──────────────────────────────────────

class PairClaimRequest(BaseModel):
    device_id: str
    pairing_code: str


class PairClaimResponse(BaseModel):
    device_token: str
    claimed_at: str


class TransferInitResponse(BaseModel):
    transfer_nonce: str
    expires_at: str


class TransferConfirmRequest(BaseModel):
    transfer_nonce: str
    physical_reset_code: str
    new_owner_id: str


class CreateCommandRequest(BaseModel):
    idempotency_key: str
    command_type: str
    payload: Dict[str, Any]
    expires_in_hours: int = COMMAND_TTL_HOURS


class CommandResponse(BaseModel):
    command_id: str
    status: str


# ─── Pairing endpoints ────────────────────────────────────────────────────────

@app.post("/api/pair/claim", response_model=PairClaimResponse)
async def pair_claim(req: PairClaimRequest, db: AsyncSession = Depends(get_db)) -> PairClaimResponse:
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PairingCode).where(
            PairingCode.code == req.pairing_code,
            PairingCode.device_id == req.device_id,
        )
    )
    pairing_code = result.scalar_one_or_none()
    if pairing_code is None:
        raise HTTPException(status_code=404, detail="Pairing code not found")
    if pairing_code.used:
        raise HTTPException(status_code=409, detail="Pairing code already used")
    if pairing_code.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=410, detail="Pairing code expired")

    result = await db.execute(select(Device).where(Device.device_id == req.device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    raw_token = secrets.token_hex(32)
    token_hash = _hash_secret(raw_token)
    device_token = f"{req.device_id}:{raw_token}"

    await db.execute(
        update(Device).where(Device.device_id == req.device_id).values(device_token_hash=token_hash)
    )
    await db.execute(
        update(PairingCode).where(PairingCode.code == req.pairing_code).values(used=True)
    )
    await db.commit()

    logger.info("Device claimed device_id=%s", req.device_id)
    return PairClaimResponse(device_token=device_token, claimed_at=now.isoformat())


@app.post("/api/devices/{device_id}/transfer/init", response_model=TransferInitResponse)
async def transfer_init(
    device_id: str,
    new_owner_id: str,
    db: AsyncSession = Depends(get_db),
) -> TransferInitResponse:
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Device not found")

    nonce = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TRANSFER_NONCE_TTL_MINUTES)
    db.add(TransferNonce(nonce=nonce, device_id=device_id, new_owner_id=new_owner_id, expires_at=expires_at))
    await db.commit()
    return TransferInitResponse(transfer_nonce=nonce, expires_at=expires_at.isoformat())


@app.post("/api/devices/{device_id}/transfer/confirm")
async def transfer_confirm(
    device_id: str,
    req: TransferConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(TransferNonce).where(
            TransferNonce.nonce == req.transfer_nonce,
            TransferNonce.device_id == device_id,
        )
    )
    nonce_row = result.scalar_one_or_none()
    if nonce_row is None:
        raise HTTPException(status_code=404, detail="Transfer nonce not found")
    if nonce_row.used:
        raise HTTPException(status_code=409, detail="Transfer nonce already used")
    if nonce_row.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=410, detail="Transfer nonce expired")

    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if not _verify_token(req.physical_reset_code, device.factory_secret_hash):
        raise HTTPException(status_code=403, detail="Invalid physical reset code")

    await db.execute(
        update(Device).where(Device.device_id == device_id).values(owner_id=nonce_row.new_owner_id)
    )
    await db.execute(
        update(TransferNonce).where(TransferNonce.nonce == req.transfer_nonce).values(used=True)
    )
    await db.commit()

    logger.info("Device transferred device_id=%s new_owner=%s", device_id, nonce_row.new_owner_id)
    return {"status": "transferred", "new_owner_id": nonce_row.new_owner_id}


@app.get("/api/devices/{device_id}/status")
async def device_status(device_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await db.execute(
        select(Command).where(Command.device_id == device_id, Command.status == "pending")
    )
    pending_commands = result.scalars().all()

    return {
        "device_id": device.device_id,
        "owner_id": device.owner_id,
        "connected": device_id in _device_ws_sessions,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "installed_skills": [s for s in device.installed_skills.split(",") if s],
        "pending_commands": len(pending_commands),
    }


@app.post("/api/devices/{device_id}/commands", response_model=CommandResponse)
async def create_command(
    device_id: str,
    req: CreateCommandRequest,
    db: AsyncSession = Depends(get_db),
) -> CommandResponse:
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Device not found")

    command_id = f"cmd_{secrets.token_hex(8)}"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=req.expires_in_hours)
    cmd = Command(
        command_id=command_id,
        idempotency_key=req.idempotency_key,
        device_id=device_id,
        type=req.command_type,
        payload=json.dumps(req.payload),
        expires_at=expires_at,
    )
    db.add(cmd)
    await db.commit()

    if device_id in _device_ws_sessions:
        asyncio.create_task(_push_command(device_id, cmd))

    logger.info("Command created id=%s device=%s type=%s", command_id, device_id, req.command_type)
    return CommandResponse(command_id=command_id, status="pending")


# ─── Device WebSocket hub ─────────────────────────────────────────────────────

async def _push_command(device_id: str, cmd: Command) -> None:
    ws = _device_ws_sessions.get(device_id)
    if ws is None or ws.client_state != WebSocketState.CONNECTED:
        return
    frame = {
        "type": "command",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "command_id": cmd.command_id,
            "idempotency_key": cmd.idempotency_key,
            "command_type": cmd.type,
            "expires_at": cmd.expires_at.isoformat(),
            "body": json.loads(cmd.payload),
        },
    }
    try:
        await ws.send_json(frame)
    except Exception:
        logger.warning("Failed to push command %s to device %s", cmd.command_id, device_id)


async def _replay_pending_commands(device_id: str, db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Command).where(Command.device_id == device_id, Command.status == "pending")
    )
    commands = result.scalars().all()
    for cmd in commands:
        expires = cmd.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            await db.execute(
                update(Command).where(Command.command_id == cmd.command_id).values(status="expired")
            )
        else:
            await _push_command(device_id, cmd)
    await db.commit()


@app.websocket("/devices/connect")
async def device_connect(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    authorization = websocket.headers.get("authorization")
    try:
        device = await _authenticate_device(authorization, db)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=exc.detail)
        return

    device_id = device.device_id
    await websocket.accept()
    _device_ws_sessions[device_id] = websocket
    logger.info("Device connected device_id=%s", device_id)

    await db.execute(
        update(Device).where(Device.device_id == device_id).values(last_seen=datetime.now(timezone.utc))
    )
    await db.commit()
    await _replay_pending_commands(device_id, db)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=HEARTBEAT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("Heartbeat timeout device_id=%s", device_id)
                break

            frame_type = raw.get("type")
            payload = raw.get("payload") or {}

            if frame_type == "hello":
                logger.info("Hello device_id=%s version=%s", device_id, payload.get("agent_version", "unknown"))

            elif frame_type == "heartbeat":
                await db.execute(
                    update(Device).where(Device.device_id == device_id).values(last_seen=datetime.now(timezone.utc))
                )
                await db.commit()

            elif frame_type == "command_ack":
                command_id = payload.get("command_id")
                status = payload.get("status")
                if command_id and status:
                    await db.execute(
                        update(Command).where(Command.command_id == command_id).values(status=status)
                    )
                    await db.commit()
                    logger.info("Command ack id=%s status=%s", command_id, status)

            else:
                logger.debug("Unknown frame type=%s from device_id=%s", frame_type, device_id)

    except WebSocketDisconnect:
        logger.info("Device disconnected device_id=%s", device_id)
    except Exception:
        logger.exception("WebSocket error device_id=%s", device_id)
    finally:
        _device_ws_sessions.pop(device_id, None)
