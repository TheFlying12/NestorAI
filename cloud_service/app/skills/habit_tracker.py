"""Habit Tracker skill — create and log daily/weekly habits with streaks and stats."""
import difflib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.models import Habit, HabitLog
from cloud_service.app.skills.agent_loop import run as agent_run

logger = logging.getLogger("cloud.skills.habit_tracker")

HABIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_habit",
            "description": "Create a new habit to track. Use this when the user wants to start tracking something new.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Habit name, e.g. 'Morning meditation', 'Run 3km', 'Read 20 pages'"},
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly"],
                        "description": "daily = track every day, weekly = track a few times per week",
                    },
                    "target_per_week": {
                        "type": "integer",
                        "description": "How many times per week. Daily habits default to 7, weekly to 3.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_habit",
            "description": (
                "Log that the user completed a habit today. Fuzzy-matches the habit name. "
                "Use this when the user says they did something (e.g. 'I meditated', 'went for a run', 'done with reading')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "habit_name": {"type": "string", "description": "Name or partial name of the habit"},
                    "note": {"type": "string", "description": "Optional detail, e.g. '5km', '30 minutes', 'felt great'"},
                },
                "required": ["habit_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_habits",
            "description": "List all active habits with current streak and today's completion status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekly_review",
            "description": "Show a day-by-day breakdown of habit completions for the current week.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_habit_stats",
            "description": "Show completion rate and streak history for a specific habit over the last 30 days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "habit_name": {"type": "string", "description": "Name or partial name of the habit"},
                },
                "required": ["habit_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_habit",
            "description": "Deactivate a habit (soft delete — history is preserved). Use when the user wants to stop tracking something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "habit_id": {"type": "integer", "description": "ID from get_habits output"},
                },
                "required": ["habit_id"],
            },
        },
    },
]


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _get_active_habits(user_id: str, db: AsyncSession) -> List[Habit]:
    result = await db.execute(
        select(Habit).where(Habit.user_id == user_id, Habit.is_active == True)
        .order_by(Habit.created_at)
    )
    return list(result.scalars().all())


def _fuzzy_find_habit(name: str, habits: List[Habit]) -> Optional[Habit]:
    """Find a habit by fuzzy name match. Returns the best match or None."""
    if not habits:
        return None
    habit_names = [h.name for h in habits]
    lower = name.lower()

    # 1. Exact match
    exact = next((h for h in habits if h.name.lower() == lower), None)
    if exact:
        return exact

    # 2. Substring match
    substr = next((h for h in habits if lower in h.name.lower() or h.name.lower() in lower), None)
    if substr:
        return substr

    # 3. Word overlap (any word from input matches a word in habit name)
    input_words = set(lower.split())
    for h in habits:
        habit_words = set(h.name.lower().split())
        if input_words & habit_words:
            return h

    # 4. Difflib fuzzy match
    matches = difflib.get_close_matches(name, habit_names, n=1, cutoff=0.4)
    if matches:
        return next(h for h in habits if h.name == matches[0])

    return None


async def _compute_streak(habit_id: int, db: AsyncSession) -> int:
    """Count consecutive calendar days (UTC) with at least one log, ending today or yesterday."""
    result = await db.execute(
        select(func.date(HabitLog.logged_at).label("day"))
        .where(HabitLog.habit_id == habit_id)
        .group_by(func.date(HabitLog.logged_at))
        .order_by(func.date(HabitLog.logged_at).desc())
    )
    raw_days = [row.day for row in result.all()]
    if not raw_days:
        return 0

    # Normalise to date objects
    days = []
    for d in raw_days:
        if isinstance(d, str):
            days.append(datetime.strptime(d, "%Y-%m-%d").date())
        else:
            days.append(d)

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    # Streak only valid if most recent log is today or yesterday
    if days[0] < yesterday:
        return 0

    streak = 0
    expected = days[0]
    for day in days:
        if day == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


async def _get_logged_today(habit_id: int, user_id: str, db: AsyncSession) -> bool:
    today = datetime.now(timezone.utc).date()
    result = await db.execute(
        select(HabitLog.id).where(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            func.date(HabitLog.logged_at) == today,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _get_week_logs(habit_id: int, user_id: str, week_start, week_end, db: AsyncSession) -> List:
    """Return list of date objects when this habit was logged in the given week."""
    result = await db.execute(
        select(func.date(HabitLog.logged_at).label("day"))
        .where(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            func.date(HabitLog.logged_at) >= week_start,
            func.date(HabitLog.logged_at) <= week_end,
        )
        .group_by(func.date(HabitLog.logged_at))
    )
    days = []
    for row in result.all():
        d = row.day
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        days.append(d)
    return days


# ─── Tool executor ─────────────────────────────────────────────────────────────

async def _execute_tool(name: str, args: Dict, db: AsyncSession, user_id: str) -> str:
    now = datetime.now(timezone.utc)

    if name == "create_habit":
        habit_name = args["name"].strip()
        frequency = args.get("frequency", "daily")
        default_target = 7 if frequency == "daily" else 3
        target_per_week = int(args.get("target_per_week", default_target))

        # Prevent duplicates
        existing = await _get_active_habits(user_id, db)
        dup = _fuzzy_find_habit(habit_name, existing)
        if dup and dup.name.lower() == habit_name.lower():
            return f"You already have a habit called '{dup.name}' (ID: {dup.id}). Log it with log_habit."

        habit = Habit(
            user_id=user_id,
            name=habit_name,
            frequency=frequency,
            target_per_week=target_per_week,
            is_active=True,
        )
        db.add(habit)
        await db.commit()
        await db.refresh(habit)
        target_desc = f"{target_per_week}x/week" if frequency == "weekly" else "daily"
        return f"✅ Created habit [{habit.id}]: **{habit_name}** ({target_desc}). Start logging it with 'I did {habit_name.lower()}' anytime."

    if name == "log_habit":
        habit_name = args["habit_name"].strip()
        note = args.get("note")
        habits = await _get_active_habits(user_id, db)
        if not habits:
            return "You have no active habits yet. Create one first."

        habit = _fuzzy_find_habit(habit_name, habits)
        if not habit:
            names_list = ", ".join(f"'{h.name}'" for h in habits)
            return f"Couldn't match '{habit_name}' to any habit. Your habits: {names_list}"

        # Deduplication: one log per habit per UTC day
        today_date = now.date()
        if await _get_logged_today(habit.id, user_id, db):
            streak = await _compute_streak(habit.id, db)
            return f"'{habit.name}' already logged for today 👍 (streak: {streak} days). Come back tomorrow!"

        log = HabitLog(habit_id=habit.id, user_id=user_id, logged_at=now, note=note)
        db.add(log)
        await db.commit()

        streak = await _compute_streak(habit.id, db)
        if streak >= 30:
            streak_msg = f" 🔥🔥🔥 {streak}-day streak — incredible!"
        elif streak >= 7:
            streak_msg = f" 🔥 {streak}-day streak!"
        elif streak >= 2:
            streak_msg = f" {streak}-day streak going!"
        else:
            streak_msg = " Day 1 — great start!"
        note_part = f" ({note})" if note else ""
        return f"✅ Logged **{habit.name}**{note_part} for today.{streak_msg}"

    if name == "get_habits":
        habits = await _get_active_habits(user_id, db)
        if not habits:
            return "No habits yet. Tell me what you want to build — e.g. 'Create a daily meditation habit'."
        today = now.date()
        lines = []
        for h in habits:
            streak = await _compute_streak(h.id, db)
            done_today = await _get_logged_today(h.id, user_id, db)
            check = "✅" if done_today else "⬜"
            fire = " 🔥" if streak >= 7 else ""
            streak_str = f"{streak}d streak{fire}" if streak > 0 else "no streak yet"
            target_str = f"{h.target_per_week}x/week" if h.frequency == "weekly" else "daily"
            lines.append(f"{check} [{h.id}] **{h.name}** ({target_str}) — {streak_str}")
        done_count = sum(1 for line in lines if line.startswith("✅"))
        total = len(habits)
        header = f"Today: {done_count}/{total} habits done\n"
        return header + "\n".join(lines)

    if name == "get_weekly_review":
        habits = await _get_active_habits(user_id, db)
        if not habits:
            return "No active habits yet."

        today = now.date()
        # Week starts Monday
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        lines = [f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d')}:\n"]
        for h in habits:
            logged_days = await _get_week_logs(h.id, user_id, week_start, week_end, db)
            logged_set = set(logged_days)
            cells = []
            for i in range(7):
                day = week_start + timedelta(days=i)
                if day > today:
                    cells.append("·")  # future
                elif day in logged_set:
                    cells.append("✓")
                else:
                    cells.append("✗")
            count = len(logged_days)
            pct = min(100, int(count / h.target_per_week * 100)) if h.target_per_week else 0
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            day_row = " ".join(f"{day_labels[i]}:{cells[i]}" for i in range(7))
            lines.append(f"**{h.name}**")
            lines.append(f"  {day_row}")
            lines.append(f"  [{bar}] {count}/{h.target_per_week} ({pct}%)\n")
        return "\n".join(lines)

    if name == "get_habit_stats":
        habit_name = args["habit_name"].strip()
        habits = await _get_active_habits(user_id, db)
        # Also include inactive ones for stats
        if not habits:
            all_result = await db.execute(select(Habit).where(Habit.user_id == user_id))
            habits = list(all_result.scalars().all())
        habit = _fuzzy_find_habit(habit_name, habits)
        if not habit:
            return f"Habit '{habit_name}' not found."

        today = now.date()
        start_30 = today - timedelta(days=29)

        # Get all logs in last 30 days
        result = await db.execute(
            select(func.date(HabitLog.logged_at).label("day"))
            .where(
                HabitLog.habit_id == habit.id,
                HabitLog.user_id == user_id,
                func.date(HabitLog.logged_at) >= start_30,
            )
            .group_by(func.date(HabitLog.logged_at))
            .order_by(func.date(HabitLog.logged_at).desc())
        )
        raw = [row.day for row in result.all()]
        logged_days = set()
        for d in raw:
            if isinstance(d, str):
                logged_days.add(datetime.strptime(d, "%Y-%m-%d").date())
            else:
                logged_days.add(d)

        days_elapsed = (today - max(habit.created_at.date(), start_30)).days + 1
        completion_rate = int(len(logged_days) / days_elapsed * 100) if days_elapsed else 0
        streak = await _compute_streak(habit.id, db)

        # Build mini calendar (last 4 weeks, 7 cols)
        calendar_lines = []
        for week_offset in range(3, -1, -1):
            week_days = []
            for dow in range(7):
                d = today - timedelta(weeks=week_offset, days=today.weekday() - dow)
                if d < habit.created_at.date() or d > today:
                    week_days.append("·")
                elif d in logged_days:
                    week_days.append("█")
                else:
                    week_days.append("░")
            calendar_lines.append(" ".join(week_days))

        total_logs_result = await db.execute(
            select(func.count(HabitLog.id)).where(
                HabitLog.habit_id == habit.id, HabitLog.user_id == user_id
            )
        )
        total_logs = total_logs_result.scalar() or 0

        return (
            f"**{habit.name}** — 30-day stats\n\n"
            f"Completion rate: {completion_rate}% ({len(logged_days)}/{days_elapsed} days)\n"
            f"Current streak: {streak} days {'🔥' if streak >= 7 else ''}\n"
            f"Total completions: {total_logs}\n\n"
            f"Last 4 weeks (█ = done, ░ = missed):\n"
            f"Mon Tue Wed Thu Fri Sat Sun\n"
            + "\n".join(calendar_lines)
        )

    if name == "delete_habit":
        habit_id = int(args["habit_id"])
        result = await db.execute(
            select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id)
        )
        habit = result.scalar_one_or_none()
        if not habit:
            return f"Habit ID {habit_id} not found."
        habit.is_active = False
        await db.commit()
        return f"'{habit.name}' has been deactivated. Your history is preserved."

    return f"Unknown tool: {name}"


# ─── Skill entry point ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an encouraging habit tracking coach. Today is {today}.

Your tools:
- create_habit: When user wants to start tracking something new.
- log_habit: When user says they did/completed a habit. Use fuzzy matching — "I ran today", "did meditation", "finished reading" all trigger this.
- get_habits: Show all habits with streak and today's status. Use at the start of a session or when asked "how am I doing".
- get_weekly_review: Day-by-day breakdown for the current week.
- get_habit_stats: 30-day completion rate + visual calendar for one habit.
- delete_habit: When user wants to stop tracking a habit.

Guidelines:
- Be warm and encouraging. Celebrate streaks and progress.
- If the user says they did something that sounds like an existing habit, call log_habit immediately.
- After logging, mention the streak if it's 3+ days.
- If they ask how they're doing, call get_habits first, then add your own encouraging commentary.
- Keep responses concise — the data speaks for itself."""


async def handle_stream(
    user_id: str,
    text: str,
    context_messages: List[Dict],
    llm_stream,
    llm_complete_with_tools,
    db: AsyncSession,
):
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=today)}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": text})

    try:
        async for token in agent_run(
            messages=messages,
            tools=HABIT_TOOLS,
            tool_executor=_execute_tool,
            llm_complete_with_tools=llm_complete_with_tools,
            llm_stream=llm_stream,
            db=db,
            user_id=user_id,
        ):
            yield token
    except Exception:
        logger.warning("Habit tracker agent loop failed", exc_info=True)
        yield "I hit an error. Please try again."
