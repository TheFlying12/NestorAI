"""Authentication — MVP no-auth mode.

All requests run as a single local user defined by MVP_USER_ID (default "local").
No JWT verification. Swap this module for a real auth provider (Clerk, Auth0, etc.)
when moving to multi-user production.
"""
import logging
import os
from typing import Optional

from fastapi import Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.db import get_db
from cloud_service.app.models import User

logger = logging.getLogger("cloud.auth")

MVP_USER_ID = os.getenv("MVP_USER_ID", "local")


async def _ensure_user(user_id: str, db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    if result.scalar_one_or_none() is None:
        db.add(User(user_id=user_id, auth_provider="local"))
        await db.commit()
        logger.info("MVP user created user_id=%s", user_id)


async def get_current_user(db: AsyncSession = Depends(get_db)) -> str:
    """FastAPI dependency: returns MVP_USER_ID. No auth check."""
    await _ensure_user(MVP_USER_ID, db)
    return MVP_USER_ID


async def get_current_user_ws(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> str:
    """WebSocket variant: returns MVP_USER_ID. No token required."""
    await _ensure_user(MVP_USER_ID, db)
    return MVP_USER_ID


async def get_user_llm_key(user_id: str, db: AsyncSession) -> Optional[str]:
    """MVP: no per-user key storage. Returns None — system OPENAI_API_KEY is used."""
    return None
