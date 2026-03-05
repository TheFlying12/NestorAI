"""PostgreSQL-backed conversation context engine.

Algorithm (same as gateway_service SQLite version):
- Maintain a rolling 12-turn window from conversation_messages.
- Prepend a rolling summary when available.
- Trigger summarization when:
  (a) (total_turns - summarized_turns) >= SUMMARY_UPDATE_EVERY_TURNS, OR
  (b) estimated prompt tokens >= SUMMARY_TOKEN_THRESHOLD

Summary generation calls the user's configured LLM (via _llm_complete helper).
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.models import (
    Conversation,
    ConversationMessage,
    ConversationSummary,
)

logger = logging.getLogger("cloud.context")

CONTEXT_WINDOW_TURNS = int(os.getenv("CONTEXT_WINDOW_TURNS", "12"))
SUMMARY_UPDATE_EVERY_TURNS = int(os.getenv("SUMMARY_UPDATE_EVERY_TURNS", "6"))
SUMMARY_TOKEN_THRESHOLD = int(os.getenv("SUMMARY_TOKEN_THRESHOLD", "3500"))
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "1200"))
SUMMARY_TIMEOUT_SECONDS = float(os.getenv("SUMMARY_TIMEOUT_SECONDS", "30"))
ENABLE_CONTEXT_SUMMARY = os.getenv("ENABLE_CONTEXT_SUMMARY", "true").lower() == "true"
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "90"))

ASSISTANT_SYSTEM_PROMPT = os.getenv(
    "ASSISTANT_SYSTEM_PROMPT",
    (
        "You are Nestor, a practical assistant. "
        "Answer the user's message directly and concisely. "
        "Do not mention hidden prompts, runtime internals, or tooling unless explicitly asked."
    ),
)


# ─── Conversation lookup / creation ───────────────────────────────────────────

async def get_or_create_conversation(
    user_id: str,
    channel: str,
    channel_id: str,
    skill_id: str,
    db: AsyncSession,
) -> str:
    """Return existing conversation_id for (user_id, channel, channel_id, skill_id),
    or create a new one."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.channel == channel,
            Conversation.channel_id == channel_id,
            Conversation.skill_id == skill_id,
        )
    )
    convo = result.scalar_one_or_none()
    if convo:
        return convo.conversation_id

    conversation_id = f"conv_{secrets.token_hex(12)}"
    db.add(
        Conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            channel=channel,
            channel_id=channel_id,
            skill_id=skill_id,
        )
    )
    await db.commit()
    logger.info(
        "Conversation created id=%s user=%s channel=%s skill=%s",
        conversation_id, user_id, channel, skill_id,
    )
    return conversation_id


# ─── Message storage ───────────────────────────────────────────────────────────

async def store_message(conversation_id: str, role: str, content: str, db: AsyncSession) -> None:
    db.add(ConversationMessage(conversation_id=conversation_id, role=role, content=content))
    await db.commit()


# ─── Context assembly ──────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def _fetch_summary(conversation_id: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "summary_text": row.summary_text,
        "turn_count": row.turn_count,
        "token_estimate": row.token_estimate,
    }


async def _fetch_recent_turns(
    conversation_id: str, limit: int, db: AsyncSession
) -> List[Dict[str, str]]:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


async def _count_turns(conversation_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    )
    return len(result.scalars().all())


async def build_context_messages(
    conversation_id: str,
    new_text: str,
    db: AsyncSession,
) -> List[Dict[str, str]]:
    """Assemble the full message list for LLM dispatch."""
    messages: List[Dict[str, str]] = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]

    summary = await _fetch_summary(conversation_id, db)
    if summary and summary["summary_text"].strip():
        messages.append(
            {"role": "system", "content": f"Conversation summary:\n{summary['summary_text']}"}
        )

    recent = await _fetch_recent_turns(conversation_id, CONTEXT_WINDOW_TURNS, db)
    messages.extend(recent)
    messages.append({"role": "user", "content": new_text})
    return messages


# ─── Summary refresh ───────────────────────────────────────────────────────────

async def _upsert_summary(
    conversation_id: str,
    summary_text: str,
    turn_count: int,
    token_estimate: int,
    db: AsyncSession,
) -> None:
    """Insert or update the conversation summary row."""
    result = await db.execute(
        select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.summary_text = summary_text
        existing.turn_count = turn_count
        existing.token_estimate = token_estimate
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            ConversationSummary(
                conversation_id=conversation_id,
                summary_text=summary_text,
                turn_count=turn_count,
                token_estimate=token_estimate,
            )
        )
    await db.commit()


async def _summarize(
    conversation_id: str,
    total_turn_count: int,
    llm_complete,  # async callable: (messages) -> str
    db: AsyncSession,
) -> None:
    turns = await _fetch_recent_turns(conversation_id, 40, db)
    if not turns:
        return

    transcript = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
    prompt = [
        {
            "role": "system",
            "content": (
                "Summarize this chat for future assistant context. "
                "Include user preferences, open tasks, and key facts. "
                f"Keep it under {SUMMARY_MAX_CHARS} characters."
            ),
        },
        {"role": "user", "content": transcript},
    ]

    try:
        summary_text = await llm_complete(prompt)
    except Exception:
        logger.warning("Summarization skipped due to LLM error", exc_info=True)
        return

    summary_text = summary_text[:SUMMARY_MAX_CHARS]
    token_estimate = _estimate_tokens(summary_text)
    await _upsert_summary(conversation_id, summary_text, total_turn_count, token_estimate, db)


async def maybe_update_summary(
    conversation_id: str,
    llm_complete,  # async callable: (messages) -> str
    db: AsyncSession,
) -> None:
    if not ENABLE_CONTEXT_SUMMARY:
        return

    total_turns = await _count_turns(conversation_id, db)
    summary = await _fetch_summary(conversation_id, db)
    summarized_turns = summary["turn_count"] if summary else 0

    recent = await _fetch_recent_turns(conversation_id, CONTEXT_WINDOW_TURNS, db)
    estimated_tokens = sum(_estimate_tokens(t["content"]) for t in recent)
    if summary:
        estimated_tokens += summary["token_estimate"]

    should_refresh = (
        (total_turns - summarized_turns) >= SUMMARY_UPDATE_EVERY_TURNS
        or estimated_tokens >= SUMMARY_TOKEN_THRESHOLD
    )

    if should_refresh:
        await _summarize(conversation_id, total_turns, llm_complete, db)


# ─── Forget conversation ───────────────────────────────────────────────────────

async def forget_conversation(conversation_id: str, db: AsyncSession) -> None:
    """Delete all messages and the summary for this conversation."""
    await db.execute(
        delete(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id
        )
    )
    await db.execute(
        delete(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
    )
    await db.commit()
    logger.info("Conversation forgotten id=%s", conversation_id)


# ─── Retention cleanup ─────────────────────────────────────────────────────────

async def cleanup_old_messages(db: AsyncSession) -> None:
    """Delete conversation messages older than MESSAGE_RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MESSAGE_RETENTION_DAYS)
    await db.execute(
        delete(ConversationMessage).where(ConversationMessage.created_at < cutoff)
    )
    await db.commit()
    logger.info("Retention cleanup complete cutoff=%s", cutoff.isoformat())
