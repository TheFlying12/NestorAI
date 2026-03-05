import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.db import get_db, create_all_tables
from cloud_service.app.models import Command, Device, PairingCode, TransferNonce

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cloud")

SECRET_KEY = os.environ.get("CLOUD_SECRET_KEY", "")
COMMAND_TTL_HOURS = int(os.getenv("COMMAND_TTL_HOURS", "24"))
TRANSFER_NONCE_TTL_MINUTES = int(os.getenv("TRANSFER_NONCE_TTL_MINUTES", "10"))
HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "90"))

app = FastAPI(title="NestorAI Cloud Service", version="0.1.0")

# ─── In-memory WebSocket registry ────────────────────────────────────────────
# device_id -> WebSocket.  Single-node MVP; replace with Redis pub/sub for multi-node.
_ws_sessions: Dict[str, WebSocket] = {}


# ─── Security helpers ─────────────────────────────────────────────────────────

def _hash_secret(value: str) -> str:
    """HMAC-SHA256 of value using CLOUD_SECRET_KEY. Never store raw tokens."""
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

    # token format: "<device_id>:<raw_token>"
    parts = token.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed device token")
    device_id, raw_token = parts

    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if not device or not _verify_token(raw_token, device.device_token_hash):
        raise HTTPException(status_code=401, detail="Invalid device credentials")
    return device


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    if not SECRET_KEY:
        logger.error("CLOUD_SECRET_KEY is not set — token operations will fail")
    # In production, run: alembic upgrade head
    # For dev/test, auto-create tables from ORM metadata.
    if os.getenv("AUTO_MIGRATE", "false").lower() == "true":
        await create_all_tables()
        logger.info("Database tables created (AUTO_MIGRATE=true)")
    logger.info("Cloud service started")


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "cloud",
        "connected_devices": len(_ws_sessions),
    }


# ─── Pydantic request/response models ─────────────────────────────────────────

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

    # Generate a new device token
    raw_token = secrets.token_hex(32)
    token_hash = _hash_secret(raw_token)
    device_token = f"{req.device_id}:{raw_token}"

    await db.execute(
        update(Device)
        .where(Device.device_id == req.device_id)
        .values(device_token_hash=token_hash)
    )
    await db.execute(
        update(PairingCode)
        .where(PairingCode.code == req.pairing_code)
        .values(used=True)
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
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    nonce = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TRANSFER_NONCE_TTL_MINUTES)

    db.add(TransferNonce(
        nonce=nonce,
        device_id=device_id,
        new_owner_id=new_owner_id,
        expires_at=expires_at,
    ))
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

    # Validate physical reset code against factory_secret_hash
    if not _verify_token(req.physical_reset_code, device.factory_secret_hash):
        raise HTTPException(status_code=403, detail="Invalid physical reset code")

    await db.execute(
        update(Device)
        .where(Device.device_id == device_id)
        .values(owner_id=nonce_row.new_owner_id)
    )
    await db.execute(
        update(TransferNonce)
        .where(TransferNonce.nonce == req.transfer_nonce)
        .values(used=True)
    )
    await db.commit()

    logger.info("Device ownership transferred device_id=%s new_owner=%s", device_id, nonce_row.new_owner_id)
    return {"status": "transferred", "new_owner_id": nonce_row.new_owner_id}


# ─── Device status & commands ─────────────────────────────────────────────────

@app.get("/api/devices/{device_id}/status")
async def device_status(device_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await db.execute(
        select(Command).where(
            Command.device_id == device_id,
            Command.status == "pending",
        )
    )
    pending_commands = result.scalars().all()

    return {
        "device_id": device.device_id,
        "owner_id": device.owner_id,
        "connected": device_id in _ws_sessions,
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

    # Push immediately if device is connected.
    if device_id in _ws_sessions:
        asyncio.create_task(_push_command(device_id, cmd))

    logger.info("Command created command_id=%s device_id=%s type=%s", command_id, device_id, req.command_type)
    return CommandResponse(command_id=command_id, status="pending")


# ─── WebSocket hub ────────────────────────────────────────────────────────────

async def _push_command(device_id: str, cmd: Command) -> None:
    ws = _ws_sessions.get(device_id)
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
        select(Command).where(
            Command.device_id == device_id,
            Command.status == "pending",
        )
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
    _ws_sessions[device_id] = websocket
    logger.info("Device connected device_id=%s", device_id)

    # Update last_seen on connect
    await db.execute(
        update(Device)
        .where(Device.device_id == device_id)
        .values(last_seen=datetime.now(timezone.utc))
    )
    await db.commit()

    # Replay any pending commands
    await _replay_pending_commands(device_id, db)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=HEARTBEAT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("Heartbeat timeout for device_id=%s — closing", device_id)
                break

            frame_type = raw.get("type")
            payload = raw.get("payload") or {}

            if frame_type == "hello":
                logger.info(
                    "Hello from device_id=%s version=%s",
                    device_id,
                    payload.get("agent_version", "unknown"),
                )

            elif frame_type == "heartbeat":
                await db.execute(
                    update(Device)
                    .where(Device.device_id == device_id)
                    .values(last_seen=datetime.now(timezone.utc))
                )
                await db.commit()

            elif frame_type == "command_ack":
                command_id = payload.get("command_id")
                status = payload.get("status")
                if command_id and status:
                    await db.execute(
                        update(Command)
                        .where(Command.command_id == command_id)
                        .values(status=status)
                    )
                    await db.commit()
                    logger.info("Command ack command_id=%s status=%s", command_id, status)

            else:
                logger.debug("Unknown frame type=%s from device_id=%s", frame_type, device_id)

    except WebSocketDisconnect:
        logger.info("Device disconnected device_id=%s", device_id)
    except Exception:
        logger.exception("WebSocket error for device_id=%s", device_id)
    finally:
        _ws_sessions.pop(device_id, None)
