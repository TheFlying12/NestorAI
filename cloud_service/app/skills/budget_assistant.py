"""Budget Assistant skill — cloud-hosted PostgreSQL version.

Ported from skills/budget_assistant/main.py.

Categorization + math: fully deterministic (no LLM).
LLM: used ONLY to generate the friendly natural-language reply.

All transactions are stored in the PostgreSQL `transactions` table.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.models import Transaction

logger = logging.getLogger("cloud.skills.budget_assistant")

BUDGETS: Dict[str, float] = json.loads(os.getenv("SKILL_BUDGETS", "{}")) or {
    "food": 400.0,
    "transport": 150.0,
    "entertainment": 100.0,
    "utilities": 200.0,
}

# ─── Deterministic category rules ─────────────────────────────────────────────

_CATEGORY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("food", ["grocery", "groceries", "supermarket", "whole foods", "trader joe", "aldi",
              "kroger", "walmart", "target", "food", "restaurant", "cafe", "coffee",
              "starbucks", "mcdonald", "pizza", "lunch", "dinner", "breakfast", "eat",
              "doordash", "ubereats", "grubhub"]),
    ("transport", ["uber", "lyft", "taxi", "gas", "fuel", "parking", "transit",
                   "metro", "subway", "train", "bus", "flight", "airline", "car"]),
    ("utilities", ["electric", "electricity", "water", "internet", "phone", "bill",
                   "utility", "utilities", "at&t", "verizon", "comcast", "spectrum"]),
    ("entertainment", ["netflix", "spotify", "apple", "amazon prime", "hulu",
                       "movie", "concert", "game", "entertainment", "bar", "club"]),
    ("health", ["pharmacy", "cvs", "walgreens", "doctor", "hospital", "gym",
                "fitness", "medical", "prescription", "dental"]),
    ("shopping", ["amazon", "ebay", "mall", "clothing", "shoes", "clothes",
                  "apparel", "department store"]),
]


def _categorize(text: str) -> str:
    lower = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return category
    return "other"


_AMOUNT_RE = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)")
_MERCHANT_RE = re.compile(r"\bat\s+([A-Za-z][A-Za-z0-9 &']{1,40})", re.IGNORECASE)


def _parse_transaction(text: str) -> Optional[Dict[str, Any]]:
    amount_match = _AMOUNT_RE.search(text)
    if not amount_match:
        return None
    amount = float(amount_match.group(1))
    merchant_match = _MERCHANT_RE.search(text)
    merchant = merchant_match.group(1).strip() if merchant_match else ""
    category = _categorize(f"{text} {merchant}")
    return {"amount": round(amount, 2), "merchant": merchant, "category": category}


def _check_budget_alerts(totals: Dict[str, float]) -> List[str]:
    alerts = []
    for category, budget in BUDGETS.items():
        spent = totals.get(category, 0.0)
        if spent > budget:
            pct = int((spent / budget - 1) * 100)
            alerts.append(f"{category.title()}: ${spent:.2f} vs ${budget:.2f} budget ({pct}% over)")
        elif spent > budget * 0.8:
            remaining = budget - spent
            alerts.append(f"{category.title()}: ${spent:.2f} spent, ${remaining:.2f} remaining")
    return alerts


# ─── PostgreSQL persistence ────────────────────────────────────────────────────

async def _insert_transaction(
    user_id: str, amount: float, category: str, merchant: str, note: str, db: AsyncSession
) -> None:
    db.add(
        Transaction(
            user_id=user_id,
            amount=amount,
            category=category,
            merchant=merchant,
            note=note,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def _monthly_totals(
    user_id: str, year: int, month: int, db: AsyncSession
) -> Dict[str, float]:
    result = await db.execute(
        select(Transaction.category, func.round(func.sum(Transaction.amount), 2).label("total"))
        .where(
            Transaction.user_id == user_id,
            extract("year", Transaction.timestamp) == year,
            extract("month", Transaction.timestamp) == month,
        )
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
    )
    rows = result.all()
    return {row.category: float(row.total) for row in rows}


# ─── Intent detection ──────────────────────────────────────────────────────────

_SUMMARY_KEYWORDS = re.compile(
    r"\b(summary|spending|spent|total|monthly|how much|budget)\b", re.IGNORECASE
)


def _detect_intent(text: str) -> str:
    """Simple keyword-based intent detection (no LLM required)."""
    return "monthly_summary" if _SUMMARY_KEYWORDS.search(text) else "add_transaction"


# ─── Main dispatch ─────────────────────────────────────────────────────────────

async def handle(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_complete,  # async callable: (messages) -> str
    db: AsyncSession,
) -> str:
    intent = _detect_intent(text)
    if intent == "monthly_summary":
        return await _handle_summary(user_id, llm_complete, db)
    return await _handle_add_transaction(user_id, text, llm_complete, db)


async def _handle_add_transaction(
    user_id: str, text: str, llm_complete, db: AsyncSession
) -> str:
    parsed = _parse_transaction(text)
    if not parsed:
        return "I couldn't find an amount in your message. Try: 'I spent $15 at Starbucks'."

    amount = parsed["amount"]
    category = parsed["category"]
    merchant = parsed["merchant"]

    await _insert_transaction(user_id, amount, category, merchant, text, db)

    now = datetime.now(timezone.utc)
    totals = await _monthly_totals(user_id, now.year, now.month, db)
    alerts = _check_budget_alerts(totals)

    summary_line = f"Transaction logged: ${amount:.2f} in {category}"
    if merchant:
        summary_line += f" at {merchant}"

    explain_prompt_parts = [summary_line]
    if alerts:
        explain_prompt_parts.append("Budget alerts: " + "; ".join(alerts))
    explain_prompt_parts.append("Give a brief friendly confirmation (2-3 sentences).")

    llm_messages = [
        {"role": "system", "content": "You are a friendly budget assistant. Be concise."},
        {"role": "user", "content": ". ".join(explain_prompt_parts)},
    ]

    try:
        explanation = await llm_complete(llm_messages)
        if explanation.strip():
            return explanation
    except Exception:
        logger.warning("LLM explanation failed for add_transaction", exc_info=True)

    # Deterministic fallback
    reply = f"Logged ${amount:.2f} for {category}"
    if merchant:
        reply += f" at {merchant}"
    reply += "."
    if alerts:
        reply += "\n\u26a0\ufe0f " + "\n\u26a0\ufe0f ".join(alerts)
    return reply


async def _handle_summary(user_id: str, llm_complete, db: AsyncSession) -> str:
    now = datetime.now(timezone.utc)
    totals = await _monthly_totals(user_id, now.year, now.month, db)

    if not totals:
        return "No transactions recorded for this month yet."

    total_spent = sum(totals.values())
    lines = [f"{cat.title()}: ${amt:.2f}" for cat, amt in totals.items()]
    breakdown = "\n".join(lines)
    alerts = _check_budget_alerts(totals)

    explain_text = (
        f"Monthly spending for {now.strftime('%B %Y')}:\n{breakdown}\n"
        f"Total: ${total_spent:.2f}"
    )
    if alerts:
        explain_text += "\nAlerts: " + "; ".join(alerts)
    explain_text += "\nWrite a brief friendly 2-3 sentence summary."

    llm_messages = [
        {"role": "system", "content": "You are a friendly budget assistant. Be concise."},
        {"role": "user", "content": explain_text},
    ]

    try:
        explanation = await llm_complete(llm_messages)
        if explanation.strip():
            return explanation
    except Exception:
        logger.warning("LLM explanation failed for summary", exc_info=True)

    reply = f"Your spending for {now.strftime('%B %Y')}:\n{breakdown}\nTotal: ${total_spent:.2f}"
    if alerts:
        reply += "\n\n\u26a0\ufe0f " + "\n\u26a0\ufe0f ".join(alerts)
    return reply
