"""Cloud skill router — replaces OpenClaw dispatch.

Resolves the correct skill handler, calls the user's LLM, and returns a reply.
The LLM layer is abstracted through an async `llm_complete(messages) -> str` callable
built from the user's stored API key and provider preference.
"""
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.auth import get_user_llm_key
from cloud_service.app.skills import budget_assistant, general

logger = logging.getLogger("cloud.skills.router")

LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))

# Fallback API key (used if user hasn't stored their own key — e.g. for demos)
SYSTEM_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SYSTEM_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
SYSTEM_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")


# ─── Error types ──────────────────────────────────────────────────────────────

class LLMError(ValueError):
    """Raised for classifiable LLM API errors (auth, rate-limit, server errors)."""
    pass


# ─── LLM callable factory ─────────────────────────────────────────────────────

def _make_llm_complete(api_key: str, model: str, base_url: str):
    """Return an async `llm_complete(messages) -> str` bound to the given config."""

    async def llm_complete(messages: List[Dict[str, str]]) -> str:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": LLM_MAX_TOKENS,
                        "stream": False,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status == 401:
                    raise LLMError("Invalid API key. Please update your key in Settings.")
                if status == 429:
                    raise LLMError("LLM rate limit reached. Please try again in a moment.")
                if status >= 500:
                    raise LLMError("LLM service is temporarily unavailable.")
                raise LLMError(f"LLM request failed ({status}).")
            data = response.json()
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content", "").strip()
                if content:
                    return content
        return "I couldn't generate a response right now."

    return llm_complete


def _make_llm_stream(api_key: str, model: str, base_url: str):
    """Return an async generator function that yields tokens from a streaming LLM response."""

    async def llm_stream(messages: List[Dict[str, str]]):
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": LLM_MAX_TOKENS, "stream": True},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status == 401:
                        raise LLMError("Invalid API key. Please update your key in Settings.")
                    if status == 429:
                        raise LLMError("LLM rate limit reached. Please try again.")
                    if status >= 500:
                        raise LLMError("LLM service is temporarily unavailable.")
                    raise LLMError(f"LLM request failed ({status}).")
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        token = (data.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                        if token:
                            yield token
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

    return llm_stream


async def _resolve_llm_complete(user_id: str, db: AsyncSession):
    """Build the llm_complete callable for a user.

    Preference order:
    1. User's own stored API key + SYSTEM_LLM_MODEL
    2. System-level OPENAI_API_KEY (demo / admin fallback)
    3. Raises if neither is available
    """
    user_key = await get_user_llm_key(user_id, db)
    if user_key:
        logger.debug("Using user API key for user_id=%s", user_id)
        return _make_llm_complete(user_key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)

    if SYSTEM_OPENAI_API_KEY:
        logger.debug("Using system API key fallback for user_id=%s", user_id)
        return _make_llm_complete(SYSTEM_OPENAI_API_KEY, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)

    raise ValueError(
        "No LLM API key configured. "
        "Set your API key at /api/auth/apikey or configure OPENAI_API_KEY in the environment."
    )


async def _resolve_llm_stream(user_id: str, db: AsyncSession):
    """Build the llm_stream callable for a user."""
    user_key = await get_user_llm_key(user_id, db)
    key = user_key or SYSTEM_OPENAI_API_KEY
    if not key:
        raise ValueError("No LLM API key configured. Set your key at Settings \u2192 LLM API Key.")
    return _make_llm_stream(key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)


# ─── Skill dispatch ───────────────────────────────────────────────────────────

SUPPORTED_SKILLS = {"general", "budget_assistant"}


async def dispatch(
    user_id: str,
    text: str,
    skill_id: str,
    context_messages: List[Dict[str, str]],
    db: AsyncSession,
) -> str:
    """Route a user message to the appropriate skill handler.

    Args:
        user_id: Clerk user ID (used for LLM key lookup + data isolation).
        text: Raw user message text.
        skill_id: Which skill to invoke ("general" | "budget_assistant").
        context_messages: Pre-assembled context (from context.build_context_messages).
        db: Async DB session (used by budget_assistant for transaction storage).

    Returns:
        Reply string from the skill.
    """
    if skill_id not in SUPPORTED_SKILLS:
        logger.warning("Unknown skill_id=%s — falling back to general", skill_id)
        skill_id = "general"

    try:
        llm_complete = await _resolve_llm_complete(user_id, db)
    except ValueError as exc:
        return str(exc)

    if skill_id == "budget_assistant":
        return await budget_assistant.handle(
            user_id=user_id,
            text=text,
            context_messages=context_messages,
            llm_complete=llm_complete,
            db=db,
        )

    # default: general
    return await general.handle(
        user_id=user_id,
        text=text,
        context_messages=context_messages,
        llm_complete=llm_complete,
    )


async def dispatch_stream(
    user_id: str,
    text: str,
    skill_id: str,
    context_messages: List[Dict[str, str]],
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Route a user message to the appropriate skill handler (streaming).

    Yields tokens as they arrive from the LLM. Falls back to a single-token
    error message if the key is missing or the LLM is unavailable.
    """
    if skill_id not in SUPPORTED_SKILLS:
        skill_id = "general"

    try:
        llm_stream = await _resolve_llm_stream(user_id, db)
    except ValueError as exc:
        yield str(exc)
        return

    if skill_id == "budget_assistant":
        async for token in budget_assistant.handle_stream(user_id, text, context_messages, llm_stream, db):
            yield token
    else:
        async for token in general.handle_stream(user_id, text, context_messages, llm_stream):
            yield token
