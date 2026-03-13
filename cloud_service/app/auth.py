"""Authentication — Clerk JWT verification via JWKS.

HTTP endpoints  : Bearer token in Authorization header (HTTPBearer).
WebSocket endpoint: ?token=<jwt> query param, verified before accept().
BYOK keys       : Fernet-encrypted, stored in users.api_key_encrypted.
"""
import logging
import os
import time
from typing import Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.db import get_db
from cloud_service.app.models import User

logger = logging.getLogger("cloud.auth")

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
FERNET_KEY = os.getenv("FERNET_KEY", "")
JWKS_CACHE_TTL = 6 * 3600  # seconds

_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}
_http_bearer = HTTPBearer()


# ─── JWKS ─────────────────────────────────────────────────────────────────────

async def _get_jwks() -> list:
    now = time.monotonic()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < JWKS_CACHE_TTL:
        return _jwks_cache["keys"]
    if not CLERK_JWKS_URL:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "CLERK_JWKS_URL not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CLERK_JWKS_URL)
        resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    logger.info("JWKS refreshed key_count=%d", len(keys))
    return keys


async def _verify_token(token: str) -> str:
    """Verify a Clerk RS256 JWT. Returns user_id (sub claim)."""
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keys = await _get_jwks()
        matched = next((k for k in keys if k.get("kid") == kid), None)
        if matched is None:
            # kid not in cache — force refresh once and retry
            _jwks_cache["fetched_at"] = 0.0
            keys = await _get_jwks()
            matched = next((k for k in keys if k.get("kid") == kid), None)
        if matched is None:
            raise JWTError(f"No matching JWKS key for kid={kid}")
        public_key = jwk.construct(matched)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise JWTError("Missing sub claim")
        return user_id
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


# ─── User helpers ──────────────────────────────────────────────────────────────

async def _ensure_user(user_id: str, db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    if result.scalar_one_or_none() is None:
        db.add(User(user_id=user_id, auth_provider="clerk"))
        await db.commit()
        logger.info("New Clerk user created user_id=%s", user_id)


# ─── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
    db: AsyncSession = Depends(get_db),
) -> str:
    """HTTP dependency: verifies Bearer JWT, auto-creates user row, returns user_id."""
    user_id = await _verify_token(credentials.credentials)
    await _ensure_user(user_id, db)
    return user_id


async def verify_ws_token(token: Optional[str], db: AsyncSession) -> str:
    """WebSocket auth — call before websocket.accept().

    Raises HTTPException on failure so the caller can close with code 1008.
    """
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    user_id = await _verify_token(token)
    await _ensure_user(user_id, db)
    return user_id


# ─── LLM key management ────────────────────────────────────────────────────────

async def get_user_llm_key(user_id: str, db: AsyncSession) -> Optional[str]:
    """Decrypt and return the user's stored LLM API key, or None."""
    if not FERNET_KEY:
        return None
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.api_key_encrypted:
        return None
    try:
        f = Fernet(FERNET_KEY.encode())
        return f.decrypt(user.api_key_encrypted.encode()).decode()
    except InvalidToken:
        logger.warning("Failed to decrypt API key for user_id=%s", user_id)
        return None


async def store_user_llm_key(user_id: str, api_key: str, db: AsyncSession) -> None:
    """Encrypt and persist the user's LLM API key."""
    if not FERNET_KEY:
        raise ValueError("FERNET_KEY not configured on the server")
    f = Fernet(FERNET_KEY.encode())
    encrypted = f.encrypt(api_key.encode()).decode()
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.api_key_encrypted = encrypted
    await db.commit()
    logger.info("LLM API key stored for user_id=%s", user_id)
