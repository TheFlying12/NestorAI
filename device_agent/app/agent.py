"""WebSocket frame protocol handler and command dispatcher for device_agent."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

import aiosqlite
import websockets

from app.handlers import handle_config_reload, handle_install_skill, handle_reload_runtime

logger = logging.getLogger("device_agent.agent")

DB_PATH = "/data/gateway.db"

# Map command type -> handler coroutine
_HANDLERS: Dict[str, Callable[..., Coroutine]] = {
    "install_skill": handle_install_skill,
    "config_reload": handle_config_reload,
    "reload_runtime": handle_reload_runtime,
}


async def _init_idempotency_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS executed_commands (
                idempotency_key TEXT PRIMARY KEY,
                command_id TEXT NOT NULL,
                executed_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def _is_duplicate(idempotency_key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM executed_commands WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return await cursor.fetchone() is not None


async def _record_execution(idempotency_key: str, command_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO executed_commands (idempotency_key, command_id, executed_at) VALUES (?, ?, ?)",
            (idempotency_key, command_id, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


def _make_ack(command_id: str, idempotency_key: str, status: str, error: Optional[str] = None) -> str:
    return json.dumps({
        "type": "command_ack",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "command_id": command_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "error_code": "execution_error" if error else None,
            "error_message": error,
        },
    })


async def handle_frame(ws: websockets.WebSocketClientProtocol, frame: Dict[str, Any]) -> None:
    """Dispatch a single inbound server frame."""
    frame_type = frame.get("type")

    if frame_type != "command":
        logger.debug("Ignoring server frame type=%s", frame_type)
        return

    payload = frame.get("payload") or {}
    command_id: str = payload.get("command_id", "")
    idempotency_key: str = payload.get("idempotency_key", "")
    command_type: str = payload.get("command_type", "")
    expires_at_str: str = payload.get("expires_at", "")
    body: Dict[str, Any] = payload.get("body") or {}

    if not command_id or not idempotency_key or not command_type:
        logger.warning("Malformed command frame: %s", payload)
        return

    # Check TTL
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("Bad expires_at format in command command_id=%s", command_id)
        await ws.send(_make_ack(command_id, idempotency_key, "failed", "bad expires_at format"))
        return

    if datetime.now(timezone.utc) > expires_at:
        logger.info("Command expired command_id=%s", command_id)
        await ws.send(_make_ack(command_id, idempotency_key, "expired"))
        return

    # Deduplicate
    if await _is_duplicate(idempotency_key):
        logger.info("Duplicate command ignored idempotency_key=%s", idempotency_key)
        await ws.send(_make_ack(command_id, idempotency_key, "succeeded"))
        return

    handler = _HANDLERS.get(command_type)
    if handler is None:
        logger.warning("Unknown command type=%s command_id=%s", command_type, command_id)
        await ws.send(_make_ack(command_id, idempotency_key, "failed", f"unknown command type: {command_type}"))
        return

    # Ack received
    await ws.send(_make_ack(command_id, idempotency_key, "received"))

    # Execute
    try:
        logger.info("Executing command_id=%s type=%s", command_id, command_type)
        await ws.send(_make_ack(command_id, idempotency_key, "running"))
        result = await handler(body)
        await _record_execution(idempotency_key, command_id)
        await ws.send(_make_ack(command_id, idempotency_key, "succeeded"))
        logger.info("Command succeeded command_id=%s result=%s", command_id, result)
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Command failed command_id=%s type=%s error=%s", command_id, command_type, error_msg)
        await ws.send(_make_ack(command_id, idempotency_key, "failed", error_msg))


async def run_agent(
    device_id: str,
    device_token: str,
    cloud_ws_url: str,
    agent_version: str,
    heartbeat_interval: int = 30,
) -> None:
    """Main agent loop: connect, hello, heartbeat, handle commands, reconnect."""
    import asyncio

    await _init_idempotency_db()

    ws_url = f"{cloud_ws_url.rstrip('/')}/devices/connect"
    auth_header = {"Authorization": f"Bearer {device_id}:{device_token}"}

    while True:
        try:
            async with websockets.connect(ws_url, extra_headers=auth_header, ping_interval=None) as ws:
                logger.info("Connected to cloud device_id=%s url=%s", device_id, ws_url)

                # Send hello
                await ws.send(json.dumps({
                    "type": "hello",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "device_id": device_id,
                        "agent_version": agent_version,
                        "capabilities": ["install_skill", "config_reload", "reload_runtime"],
                    },
                }))

                async def _heartbeat_loop() -> None:
                    while True:
                        await asyncio.sleep(heartbeat_interval)
                        await ws.send(json.dumps({
                            "type": "heartbeat",
                            "sent_at": datetime.now(timezone.utc).isoformat(),
                            "payload": {
                                "device_id": device_id,
                                "runtime_health": "ok",
                                "queue_depth": 0,
                            },
                        }))

                heartbeat_task = asyncio.create_task(_heartbeat_loop())
                try:
                    async for raw_message in ws:
                        try:
                            frame = json.loads(raw_message)
                        except json.JSONDecodeError:
                            logger.warning("Received non-JSON message from cloud")
                            continue
                        await handle_frame(ws, frame)
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

        except Exception as exc:
            logger.warning("Cloud connection lost: %s — will reconnect", exc)
