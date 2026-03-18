"""Cloud skill router — replaces OpenClaw dispatch.

Resolves the correct skill handler, calls the user's LLM, and returns a reply.
The LLM layer is abstracted through async callables built from the user's stored API key.
"""
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.auth import get_user_llm_key
from cloud_service.app.models import NotificationLog
from cloud_service.app.skills import budget_assistant, general
from cloud_service.app.skills import job_tracker, habit_tracker

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


# ─── LLM callable factories ───────────────────────────────────────────────────

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
                logger.debug("LLM stream response status=%s model=%s", response.status_code, model)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    body = await e.response.aread()
                    logger.warning(
                        "LLM stream HTTP %s model=%s body=%.300s", status, model, body.decode(errors="replace")
                    )
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


def _make_llm_complete_with_tools(api_key: str, model: str, base_url: str):
    """Return an async `llm_complete_with_tools(messages, tools) -> choice dict`.

    Returns choices[0] dict with keys: finish_reason, message (with optional tool_calls).
    """

    async def llm_complete_with_tools(messages: List[Dict], tools: List[Dict]) -> Dict:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": "auto",
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
                return choices[0]
        return {"finish_reason": "stop", "message": {"content": "I couldn't generate a response right now.", "tool_calls": []}}

    return llm_complete_with_tools


async def _resolve_llm_complete(user_id: str, db: AsyncSession):
    """Build the llm_complete callable for a user."""
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


async def _resolve_llm_complete_with_tools(user_id: str, db: AsyncSession):
    """Build the llm_complete_with_tools callable for a user."""
    user_key = await get_user_llm_key(user_id, db)
    key = user_key or SYSTEM_OPENAI_API_KEY
    if not key:
        raise ValueError("No LLM API key configured. Set your key at Settings \u2192 LLM API Key.")
    return _make_llm_complete_with_tools(key, SYSTEM_LLM_MODEL, SYSTEM_LLM_BASE_URL)


# ─── Shared tools (send_sms / send_email) ─────────────────────────────────────

SEND_SMS_TOOL = {
    "type": "function",
    "function": {
        "name": "send_sms",
        "description": (
            "Send an SMS to a phone number on behalf of the user. "
            "Use ONLY when the user explicitly asks to send a text message to someone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Destination phone number in E.164 format, e.g. +14155552671",
                },
                "body": {
                    "type": "string",
                    "description": "Message text (max 1600 characters)",
                },
            },
            "required": ["to", "body"],
        },
    },
}

SEND_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": (
            "Send an email on behalf of the user. "
            "Use ONLY when the user explicitly asks to send an email to someone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Plain-text email body (will be wrapped in simple HTML)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
}


def _get_shared_tools() -> List[Dict]:
    """Return shared tool list; empty if neither Twilio nor Resend credentials are set."""
    from cloud_service.app.integrations.twilio_client import TWILIO_ACCOUNT_SID
    from cloud_service.app.integrations.resend_client import RESEND_API_KEY
    tools = []
    if TWILIO_ACCOUNT_SID:
        tools.append(SEND_SMS_TOOL)
    if RESEND_API_KEY:
        tools.append(SEND_EMAIL_TOOL)
    return tools


async def _shared_tool_executor(name: str, args: Dict, db: Any, user_id: str) -> str:
    """Execute shared tools (send_sms / send_email) called by the general skill agentic loop."""
    if name == "send_sms":
        from cloud_service.app.integrations.twilio_client import send_sms
        to = args.get("to", "")
        body = args.get("body", "")
        if not to or not body:
            return "Error: 'to' and 'body' are required."
        await send_sms(to, body)
        db.add(
            NotificationLog(
                user_id=user_id,
                channel="sms",
                type="agent_send",
                to_address=to,
                body=body,
                status="sent",
            )
        )
        await db.commit()
        logger.info("Agent send_sms user_id=%s to=%s", user_id, to)
        return f"SMS sent to {to}."

    if name == "send_email":
        from cloud_service.app.integrations.resend_client import send_email
        to = args.get("to", "")
        subject = args.get("subject", "Message from Nestor")
        body = args.get("body", "")
        if not to or not body:
            return "Error: 'to' and 'body' are required."
        html_body = f"<p>{body.replace(chr(10), '<br>')}</p>"
        await send_email(to, subject, html_body)
        db.add(
            NotificationLog(
                user_id=user_id,
                channel="email",
                type="agent_send",
                to_address=to,
                body=body,
                status="sent",
            )
        )
        await db.commit()
        logger.info("Agent send_email user_id=%s to=%s", user_id, to)
        return f"Email sent to {to}."

    return f"Unknown shared tool: {name}"


# ─── Skill dispatch ───────────────────────────────────────────────────────────

SUPPORTED_SKILLS = {"general", "budget_assistant", "job_tracker", "habit_tracker"}


async def dispatch(
    user_id: str,
    text: str,
    skill_id: str,
    context_messages: List[Dict[str, str]],
    db: AsyncSession,
) -> str:
    """Route a user message to the appropriate skill handler."""
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
    """Route a user message to the appropriate skill handler (streaming)."""
    if skill_id not in SUPPORTED_SKILLS:
        skill_id = "general"

    try:
        llm_stream = await _resolve_llm_stream(user_id, db)
    except ValueError as exc:
        yield str(exc)
        return

    if skill_id in ("budget_assistant", "job_tracker", "habit_tracker"):
        try:
            llm_complete_with_tools = await _resolve_llm_complete_with_tools(user_id, db)
        except ValueError as exc:
            yield str(exc)
            return

        if skill_id == "budget_assistant":
            async for token in budget_assistant.handle_stream(
                user_id, text, context_messages, llm_stream, llm_complete_with_tools, db
            ):
                yield token
        elif skill_id == "job_tracker":
            async for token in job_tracker.handle_stream(
                user_id, text, context_messages, llm_stream, llm_complete_with_tools, db
            ):
                yield token
        elif skill_id == "habit_tracker":
            async for token in habit_tracker.handle_stream(
                user_id, text, context_messages, llm_stream, llm_complete_with_tools, db
            ):
                yield token
    else:
        # Use agentic path if send_sms / send_email tools are configured
        shared_tools = _get_shared_tools()
        if shared_tools:
            try:
                llm_complete_with_tools = await _resolve_llm_complete_with_tools(user_id, db)
            except ValueError as exc:
                yield str(exc)
                return
            async for token in general.handle_stream_with_tools(
                user_id, text, context_messages, llm_stream, llm_complete_with_tools,
                db, shared_tools, _shared_tool_executor,
            ):
                yield token
        else:
            async for token in general.handle_stream(user_id, text, context_messages, llm_stream):
                yield token
