"""Budget Assistant skill — cloud-hosted PostgreSQL version.

Categorization + math: fully deterministic (no LLM).
LLM: agentic loop with tool calling for flexible query handling.
All transactions are stored in the PostgreSQL `transactions` table.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from sqlalchemy import select, func, extract, text
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.models import NotificationLog, Transaction, SkillMemory, User
from cloud_service.app.skills.agent_loop import run as agent_run

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


def _check_budget_alerts(totals: Dict[str, float], limits: Dict[str, float]) -> List[str]:
    alerts = []
    for category, budget in limits.items():
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


async def _get_user_budget_limits(user_id: str, db: AsyncSession) -> Dict[str, float]:
    """Merge env defaults with DB overrides stored in skill_memories."""
    limits = dict(BUDGETS)
    result = await db.execute(
        select(SkillMemory.key, SkillMemory.value_json)
        .where(SkillMemory.skill_id == "budget_assistant", SkillMemory.user_id == user_id)
    )
    for row in result.all():
        if row.key.startswith("budget_limit_"):
            category = row.key[len("budget_limit_"):]
            try:
                limits[category] = float(json.loads(row.value_json))
            except (ValueError, json.JSONDecodeError):
                pass
    return limits


async def _set_user_budget_limit(user_id: str, category: str, amount: float, db: AsyncSession) -> None:
    key = f"budget_limit_{category}"
    existing = await db.execute(
        select(SkillMemory).where(
            SkillMemory.skill_id == "budget_assistant",
            SkillMemory.user_id == user_id,
            SkillMemory.key == key,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.value_json = json.dumps(amount)
    else:
        db.add(SkillMemory(skill_id="budget_assistant", user_id=user_id, key=key, value_json=json.dumps(amount)))
    await db.commit()


# ─── Tool definitions ──────────────────────────────────────────────────────────

BUDGET_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "log_transaction",
            "description": "Log a new spending transaction for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Transaction amount in USD"},
                    "category": {"type": "string", "description": "Spending category (food/transport/utilities/entertainment/health/shopping/other)"},
                    "merchant": {"type": "string", "description": "Merchant or store name"},
                    "note": {"type": "string", "description": "Original user message or note"},
                },
                "required": ["amount", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_summary",
            "description": "Get total spending by category for a given month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Month as YYYY-MM, or 'current' for current month"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget_limits",
            "description": "Get the user's budget limits per category.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_budget_limit",
            "description": "Set a budget limit for a spending category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Spending category"},
                    "amount": {"type": "number", "description": "Monthly budget limit in USD"},
                },
                "required": ["category", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions",
            "description": "Get recent transactions, optionally filtered by category or merchant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by category (optional)"},
                    "merchant": {"type": "string", "description": "Filter by merchant name (optional, partial match)"},
                    "limit": {"type": "integer", "description": "Max transactions to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spending_trends",
            "description": "Compare spending this month vs last month by category. Use when user asks about trends, changes, or 'am I spending more'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_transaction",
            "description": "Delete a transaction by ID (use get_transactions to find the ID first).",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer", "description": "Transaction ID to delete"},
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms_to_user",
            "description": "Send an SMS message to the user's phone number. Use for reminders, alerts, or any message the user wants sent to their phone. Only works if the user has a phone number on file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The message to send via SMS"},
                },
                "required": ["message"],
            },
        },
    },
]


# ─── Tool executor ─────────────────────────────────────────────────────────────

async def _execute_tool(name: str, args: Dict, db: AsyncSession, user_id: str) -> str:
    now = datetime.now(timezone.utc)

    if name == "log_transaction":
        amount = float(args["amount"])
        category = args.get("category") or _categorize(args.get("note", ""))
        merchant = args.get("merchant", "")
        note = args.get("note", "")
        await _insert_transaction(user_id, amount, category, merchant, note, db)
        limits = await _get_user_budget_limits(user_id, db)
        totals = await _monthly_totals(user_id, now.year, now.month, db)
        alerts = _check_budget_alerts(totals, limits)
        result = f"Logged ${amount:.2f} in {category}"
        if merchant:
            result += f" at {merchant}"
        if alerts:
            result += ". Alerts: " + "; ".join(alerts)

        # Fire SMS/email budget alert if this category is now over its limit
        if alerts and category in limits and totals.get(category, 0.0) > limits[category]:
            try:
                user_result = await db.execute(select(User).where(User.user_id == user_id))
                user_obj = user_result.scalar_one_or_none()
                if user_obj:
                    alert_msg = (
                        f"Nestor budget alert: {category.title()} is ${totals[category]:.2f} "
                        f"of ${limits[category]:.2f} limit."
                    )
                    if user_obj.phone_number:
                        from cloud_service.app.integrations.twilio_client import send_sms
                        await send_sms(user_obj.phone_number, alert_msg)
                        db.add(NotificationLog(
                            user_id=user_id, channel="sms", type="budget_alert",
                            to_address=user_obj.phone_number, body=alert_msg, status="sent",
                        ))
                    if user_obj.notification_email:
                        from cloud_service.app.integrations.resend_client import send_email
                        await send_email(
                            user_obj.notification_email,
                            f"Nestor Budget Alert: {category.title()}",
                            f"<p>{alert_msg}</p>",
                        )
                        db.add(NotificationLog(
                            user_id=user_id, channel="email", type="budget_alert",
                            to_address=user_obj.notification_email, body=alert_msg, status="sent",
                        ))
                    await db.commit()
            except Exception:
                logger.warning("Budget alert send failed for user_id=%s", user_id, exc_info=True)

        return result

    if name == "get_monthly_summary":
        month_str = args.get("month", "current")
        if month_str == "current" or not month_str:
            year, month = now.year, now.month
        else:
            try:
                dt = datetime.strptime(month_str, "%Y-%m")
                year, month = dt.year, dt.month
            except ValueError:
                year, month = now.year, now.month
        totals = await _monthly_totals(user_id, year, month, db)
        if not totals:
            return f"No transactions found for {year}-{month:02d}."
        limits = await _get_user_budget_limits(user_id, db)
        alerts = _check_budget_alerts(totals, limits)
        lines = [f"{cat.title()}: ${amt:.2f}" for cat, amt in totals.items()]
        total = sum(totals.values())
        summary = f"Spending for {year}-{month:02d}:\n" + "\n".join(lines) + f"\nTotal: ${total:.2f}"
        if alerts:
            summary += "\nAlerts: " + "; ".join(alerts)
        return summary

    if name == "get_budget_limits":
        limits = await _get_user_budget_limits(user_id, db)
        lines = [f"{cat.title()}: ${amt:.2f}/month" for cat, amt in limits.items()]
        return "Budget limits:\n" + "\n".join(lines)

    if name == "set_budget_limit":
        category = args["category"].lower()
        amount = float(args["amount"])
        await _set_user_budget_limit(user_id, category, amount, db)
        return f"Budget limit for {category} set to ${amount:.2f}/month."

    if name == "get_transactions":
        category_filter = args.get("category")
        merchant_filter = args.get("merchant")
        limit = int(args.get("limit", 10))
        query = select(Transaction).where(Transaction.user_id == user_id)
        if category_filter:
            query = query.where(Transaction.category == category_filter.lower())
        if merchant_filter:
            query = query.where(Transaction.merchant.ilike(f"%{merchant_filter}%"))
        query = query.order_by(Transaction.timestamp.desc()).limit(limit)
        result = await db.execute(query)
        rows = result.scalars().all()
        if not rows:
            return "No transactions found."
        lines = [
            f"[{t.id}] ${float(t.amount):.2f} {t.category}"
            + (f" at {t.merchant}" if t.merchant else "")
            + f" — {t.timestamp.strftime('%b %d')}"
            for t in rows
        ]
        return "\n".join(lines)

    if name == "get_spending_trends":
        # Current month vs previous month
        if now.month == 1:
            prev_year, prev_month = now.year - 1, 12
        else:
            prev_year, prev_month = now.year, now.month - 1

        curr_totals = await _monthly_totals(user_id, now.year, now.month, db)
        prev_totals = await _monthly_totals(user_id, prev_year, prev_month, db)

        if not curr_totals and not prev_totals:
            return "No transaction data yet to compare trends."

        all_cats = sorted(set(curr_totals) | set(prev_totals))
        curr_total = sum(curr_totals.values())
        prev_total = sum(prev_totals.values())

        lines = [
            f"Spending trends: {now.strftime('%b')} vs {datetime(prev_year, prev_month, 1).strftime('%b')}:\n"
        ]
        for cat in all_cats:
            curr = curr_totals.get(cat, 0.0)
            prev = prev_totals.get(cat, 0.0)
            if prev > 0:
                pct = int((curr - prev) / prev * 100)
                arrow = "↑" if pct > 0 else "↓" if pct < 0 else "→"
                change = f"{arrow} {abs(pct)}%"
            elif curr > 0:
                change = "↑ new"
            else:
                change = "→"
            lines.append(f"  {cat.title():<14} ${curr:>7.2f}  (was ${prev:.2f})  {change}")

        overall_change = ""
        if prev_total > 0:
            pct = int((curr_total - prev_total) / prev_total * 100)
            overall_change = f"  {'↑' if pct > 0 else '↓'} {abs(pct)}% overall"
        lines.append(f"\nTotal: ${curr_total:.2f} (was ${prev_total:.2f}){overall_change}")

        # Days elapsed this month for projection
        days_in_month = 31  # conservative
        days_elapsed = now.day
        if days_elapsed < days_in_month and curr_total > 0:
            projected = curr_total / days_elapsed * days_in_month
            lines.append(f"Projected month-end: ~${projected:.0f} (based on {days_elapsed} days)")

        return "\n".join(lines)

    if name == "delete_transaction":
        txn_id = int(args["transaction_id"])
        result = await db.execute(
            select(Transaction).where(
                Transaction.id == txn_id, Transaction.user_id == user_id
            )
        )
        txn = result.scalar_one_or_none()
        if not txn:
            return f"Transaction {txn_id} not found."
        desc = f"${float(txn.amount):.2f} {txn.category}" + (f" at {txn.merchant}" if txn.merchant else "")
        await db.delete(txn)
        await db.commit()
        return f"Deleted transaction {txn_id}: {desc}."

    if name == "send_sms_to_user":
        message = args.get("message", "").strip()
        if not message:
            return "No message provided."
        user_result = await db.execute(select(User).where(User.user_id == user_id))
        user_obj = user_result.scalar_one_or_none()
        if not user_obj or not user_obj.phone_number:
            return "No phone number on file. The user needs to add one in Account settings."
        try:
            from cloud_service.app.integrations.twilio_client import send_sms
            await send_sms(user_obj.phone_number, message)
            db.add(NotificationLog(
                user_id=user_id, channel="sms", type="agent_send",
                to_address=user_obj.phone_number, body=message, status="sent",
            ))
            await db.commit()
            return f"SMS sent to {user_obj.phone_number}."
        except Exception as exc:
            logger.warning("send_sms_to_user failed user_id=%s: %s", user_id, exc)
            return f"Failed to send SMS: {exc}"

    return f"Unknown tool: {name}"


# ─── Main dispatch ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a sharp, friendly budget assistant. Today: {today}.

Your tools:
- log_transaction: Use whenever the user mentions spending money. Extract amount, merchant, and infer category.
- get_monthly_summary: Use for "how much did I spend", "what's my budget", monthly overview questions.
- get_spending_trends: Use for "am I spending more", "how does this month compare", trend questions.
- get_transactions: Use to list recent transactions, optionally by category or merchant.
- get_budget_limits: Use when asked about budget limits or remaining budget.
- set_budget_limit: Use when user wants to change a budget limit.
- delete_transaction: Use when user says a transaction was wrong or wants to remove it.
- send_sms_to_user: Use when the user asks you to send them a reminder, alert, or any message via SMS/text/phone. Sends immediately.

Guidelines:
- When the user mentions ANY purchase, spending, or payment — immediately call log_transaction. Don't ask for confirmation.
- Infer category from context: coffee/restaurant = food, Uber/gas = transport, Netflix/Spotify = entertainment.
- After logging, briefly confirm and mention if they're near/over budget for that category.
- Be concise. One or two sentences is usually enough after a transaction log.
- If showing a summary, include totals and any budget alerts prominently.
- When asked to send a reminder or text, call send_sms_to_user immediately. Note: messages send right away, not on a delay."""


async def handle(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_complete,
    db: AsyncSession,
) -> str:
    # Legacy non-streaming path — deterministic fallback
    parsed = _parse_transaction(text)
    if parsed:
        await _insert_transaction(user_id, parsed["amount"], parsed["category"], parsed["merchant"], text, db)
        return f"Logged ${parsed['amount']:.2f} for {parsed['category']}."
    return "I couldn't understand that budget request. Try: 'I spent $20 at Starbucks'."


async def handle_stream(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_stream,
    llm_complete_with_tools,
    db: AsyncSession,
):
    """Stream LLM tokens using agentic tool-calling loop."""
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=today)}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": text})

    try:
        async for token in agent_run(
            messages=messages,
            tools=BUDGET_TOOLS,
            tool_executor=_execute_tool,
            llm_complete_with_tools=llm_complete_with_tools,
            llm_stream=llm_stream,
            db=db,
            user_id=user_id,
        ):
            yield token
    except Exception:
        logger.warning("Agentic budget loop failed, using deterministic fallback", exc_info=True)
        # Deterministic fallback
        parsed = _parse_transaction(text)
        if parsed:
            try:
                await _insert_transaction(user_id, parsed["amount"], parsed["category"], parsed["merchant"], text, db)
            except Exception:
                pass
            yield f"Logged ${parsed['amount']:.2f} for {parsed['category']}."
        else:
            yield "I couldn't process that budget request. Try: 'I spent $20 at Starbucks'."
