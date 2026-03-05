"""Cloud skill router — replaces OpenClaw dispatch.

Resolves the correct skill handler, calls the user's LLM, and returns a reply.
The LLM layer is abstracted through an async `llm_complete(messages) -> str` callable
built from the user's stored API key and provider preference.
"""
import logging
import os
from typing import Any, Dict, List, Optional

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


# ─── LLM callable factory ─────────────────────────────────────────────────────

def _make_llm_complete(api_key: str, model: str, base_url: str):
    """Return an async `llm_complete(messages) -> str` bound to the given config."""

    async def llm_complete(messages: List[Dict[str, str]]) -> str:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
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
            data = response.json()
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content", "").strip()
                if content:
                    return content
        return "I couldn't generate a response right now."

    return llm_complete


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
