"""Budget Assistant skill handler.

Categorization and math are fully deterministic (local).
The LLM is used ONLY to generate a friendly natural-language explanation of the result.

Input contract (from OpenClaw skill dispatch):
  {
    "user_id": str,
    "text": str,
    "intent": str   # "add_transaction" | "monthly_summary"
  }

Output contract:
  {
    "reply": str
  }
"""
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("budget_assistant")

DB_PATH = os.getenv("BUDGET_DB_PATH", "/data/budget_assistant.db")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
LLM_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

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
    """Extract amount, merchant, and category from natural language text.

    Returns None if no amount found.
    """
    amount_match = _AMOUNT_RE.search(text)
    if not amount_match:
        return None

    amount = float(amount_match.group(1))
    merchant_match = _MERCHANT_RE.search(text)
    merchant = merchant_match.group(1).strip() if merchant_match else ""
    category = _categorize(f"{text} {merchant}")

    return {
        "amount": round(amount, 2),
        "merchant": merchant,
        "category": category,
    }


# ─── SQLite persistence ────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            merchant TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'USD',
            timestamp TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_user_ts ON transactions (user_id, timestamp)")
    conn.commit()
    return conn


def _insert_transaction(user_id: str, amount: float, category: str, merchant: str, note: str) -> int:
    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO transactions (user_id, amount, category, merchant, note, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, category, merchant, note, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def _monthly_totals(user_id: str, year: int, month: int) -> Dict[str, float]:
    conn = _get_db()
    cursor = conn.execute(
        """
        SELECT category, ROUND(SUM(amount), 2) AS total
        FROM transactions
        WHERE user_id = ?
          AND strftime('%Y', timestamp) = ?
          AND strftime('%m', timestamp) = ?
        GROUP BY category
        ORDER BY total DESC
        """,
        (user_id, str(year), f"{month:02d}"),
    )
    rows = cursor.fetchall()
    conn.close()
    return {row["category"]: row["total"] for row in rows}


def _check_budget_alerts(totals: Dict[str, float]) -> List[str]:
    alerts = []
    for category, budget in BUDGETS.items():
        spent = totals.get(category, 0.0)
        if spent > budget:
            pct = int((spent / budget - 1) * 100)
            alerts.append(f"{category.title()}: ${spent:.2f} spent vs ${budget:.2f} budget ({pct}% over)")
        elif spent > budget * 0.8:
            remaining = budget - spent
            alerts.append(f"{category.title()}: ${spent:.2f} spent, ${remaining:.2f} remaining (80%+ used)")
    return alerts


# ─── LLM explanation (cloud LLM via OpenClaw) ─────────────────────────────────

def _llm_explain(prompt: str) -> str:
    """Synchronous call to OpenClaw chat completions for explanation only."""
    import httpx

    headers = {}
    if OPENCLAW_GATEWAY_TOKEN:
        headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

    try:
        response = httpx.post(
            f"{OPENCLAW_URL.rstrip('/')}/v1/chat/completions",
            json={
                "model": LLM_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "You are a friendly budget assistant. Be concise (2-3 sentences max)."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 120,
            },
            headers=headers,
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if choices:
            return (choices[0].get("message") or {}).get("content", "").strip()
    except Exception as exc:
        logger.warning("LLM explanation failed: %s", exc)

    return ""


# ─── Main dispatch ─────────────────────────────────────────────────────────────

def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous skill entry point called by OpenClaw runtime."""
    user_id: str = request.get("user_id", "")
    text: str = request.get("text", "")
    intent: str = request.get("intent", "add_transaction")

    if intent == "monthly_summary":
        return _handle_summary(user_id, text)

    return _handle_add_transaction(user_id, text)


def _handle_add_transaction(user_id: str, text: str) -> Dict[str, Any]:
    parsed = _parse_transaction(text)
    if not parsed:
        return {"reply": "I couldn't find an amount in your message. Try: 'I spent $15 at Starbucks'."}

    amount = parsed["amount"]
    category = parsed["category"]
    merchant = parsed["merchant"]

    _insert_transaction(user_id=user_id, amount=amount, category=category, merchant=merchant, note=text)

    # Check if this pushes the category over budget
    now = datetime.now(timezone.utc)
    totals = _monthly_totals(user_id, now.year, now.month)
    alerts = _check_budget_alerts(totals)

    # Build a structured summary for the LLM explanation
    summary_lines = [f"Transaction logged: ${amount:.2f} in {category}"]
    if merchant:
        summary_lines[0] += f" at {merchant}"
    if alerts:
        summary_lines.append("Budget alerts: " + "; ".join(alerts))

    explain_prompt = ". ".join(summary_lines) + ". Give a brief friendly confirmation."
    explanation = _llm_explain(explain_prompt)

    if explanation:
        reply = explanation
    else:
        reply = f"Logged ${amount:.2f} for {category}"
        if merchant:
            reply += f" at {merchant}"
        reply += "."
        if alerts:
            reply += "\n⚠️ " + "\n⚠️ ".join(alerts)

    return {"reply": reply}


def _handle_summary(user_id: str, text: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    totals = _monthly_totals(user_id, now.year, now.month)

    if not totals:
        return {"reply": "No transactions recorded for this month yet."}

    total_spent = sum(totals.values())
    lines = [f"{cat.title()}: ${amt:.2f}" for cat, amt in totals.items()]
    breakdown = "\n".join(lines)
    alerts = _check_budget_alerts(totals)

    explain_prompt = (
        f"Monthly spending summary for {now.strftime('%B %Y')}:\n{breakdown}\n"
        f"Total: ${total_spent:.2f}"
    )
    if alerts:
        explain_prompt += "\nAlerts: " + "; ".join(alerts)
    explain_prompt += "\nWrite a brief friendly 2-3 sentence summary."

    explanation = _llm_explain(explain_prompt)

    if explanation:
        reply = explanation
    else:
        reply = f"Your spending for {now.strftime('%B %Y')}:\n{breakdown}\nTotal: ${total_spent:.2f}"
        if alerts:
            reply += "\n\n⚠️ " + "\n⚠️ ".join(alerts)

    return {"reply": reply}
