"""Authentication and API key management for NestorAI cloud service.

- JWT verification via Clerk JWKS endpoint (RS256)
- User record upsert on first login
- Per-user LLM API key storage: encrypted at rest with Fernet symmetric encryption
- FastAPI dependency: get_current_user() → user_id str
"""
import logging
import os
from typing import Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Query, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import RSAKey
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.db import get_db
from cloud_service.app.models import User

logger = logging.getLogger("cloud.auth")

# ─── Config ───────────────────────────────────────────────────────────────────

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
# Clerk JWKS URL — e.g. https://<your-clerk-domain>/.well-known/jwks.json
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
# Fernet key for encrypting user API keys at rest.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY = os.getenv("FERNET_KEY", "")

_fernet: Optional[Fernet] = None
_jwks_cache: Optional[dict] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not FERNET_KEY:
            raise RuntimeError("FERNET_KEY is not configured")
        _fernet = Fernet(FERNET_KEY.encode())
    return _fernet


async def _fetch_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    if not CLERK_JWKS_URL:
        raise RuntimeError("CLERK_JWKS_URL is not configured")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(CLERK_JWKS_URL)
        response.raise_for_status()
        _jwks_cache = response.json()
    return _jwks_cache


def encrypt_api_key(raw_key: str) -> str:
    """Encrypt a plaintext API key using Fernet symmetric encryption."""
    return _get_fernet().encrypt(raw_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted API key. Raises ValueError on bad token."""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt API key") from exc


# ─── JWT verification ──────────────────────────────────────────────────────────

async def _verify_clerk_token(token: str) -> dict:
    """Verify a Clerk-issued JWT against the JWKS endpoint.

    Returns the decoded claims dict on success. Raises HTTPException on failure.
    """
    try:
        jwks = await _fetch_jwks()
        # python-jose can decode using JWKS directly
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},  # Clerk omits aud in some configs
        )
        return claims
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as exc:
        logger.error("JWKS fetch/decode error: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")


async def _upsert_user(user_id: str, email: Optional[str], db: AsyncSession) -> User:
    """Ensure a User row exists for this Clerk user ID."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(user_id=user_id, email=email, auth_provider="clerk")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("New user created user_id=%s", user_id)
    return user


# ─── FastAPI dependencies ──────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency: extract + verify Clerk JWT → returns user_id.

    Raises 401 if token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")

    claims = await _verify_clerk_token(credentials.credentials)
    user_id: str = claims.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    email: Optional[str] = claims.get("email")
    await _upsert_user(user_id, email, db)
    return user_id


async def get_current_user_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """WebSocket variant: reads token from ?token= query param.

    Usage: ws = await websocket.accept() after this dependency resolves.
    Closes with 1008 if auth fails.
    """
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        claims = await _verify_clerk_token(token)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=exc.detail)
        raise

    user_id: str = claims.get("sub", "")
    if not user_id:
        await websocket.close(code=1008, reason="Token missing sub")
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    email: Optional[str] = claims.get("email")
    await _upsert_user(user_id, email, db)
    return user_id


# ─── Pydantic models ───────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    api_key: str
    provider: str = "openai"   # "openai" | "gemini"


class MeResponse(BaseModel):
    user_id: str
    email: Optional[str]
    has_api_key: bool
    auth_provider: str


# ─── Auth endpoints ────────────────────────────────────────────────────────────

async def store_api_key(
    req: ApiKeyRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/auth/apikey — store (or replace) the user's LLM API key."""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key must not be empty")

    encrypted = encrypt_api_key(req.api_key.strip())
    await db.execute(
        update(User).where(User.user_id == user_id).values(api_key_encrypted=encrypted)
    )
    await db.commit()
    logger.info("API key updated user_id=%s provider=%s", user_id, req.provider)
    return {"status": "ok"}


async def get_me(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """GET /api/auth/me — return current user info."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return MeResponse(
        user_id=user.user_id,
        email=user.email,
        has_api_key=bool(user.api_key_encrypted),
        auth_provider=user.auth_provider,
    )


async def get_user_llm_key(user_id: str, db: AsyncSession) -> Optional[str]:
    """Internal helper: returns plaintext LLM API key or None if not set."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.api_key_encrypted:
        return None
    try:
        return decrypt_api_key(user.api_key_encrypted)
    except ValueError:
        logger.error("Failed to decrypt API key for user_id=%s", user_id)
        return None
