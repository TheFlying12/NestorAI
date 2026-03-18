"""Proactive notification scheduler — habit reminders and job follow-up nudges.

Wired into main.py lifespan via scheduler.start() / scheduler.shutdown().
Jobs silently skip users without phone numbers or when Twilio is unconfigured.
"""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from cloud_service.app.db import AsyncSessionLocal
from cloud_service.app.models import Habit, HabitLog, JobApplication, NotificationLog, User

logger = logging.getLogger("cloud.notifications")

scheduler = AsyncIOScheduler(timezone="UTC")


@scheduler.scheduled_job("cron", hour=20, minute=0)
async def daily_habit_reminder() -> None:
    """8 PM UTC daily: SMS users who have incomplete daily habits."""
    from cloud_service.app.integrations.twilio_client import send_sms  # lazy — avoids module-load warning

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.phone_number.is_not(None)))
        users = result.scalars().all()

        for user in users:
            try:
                habits_result = await db.execute(
                    select(Habit).where(
                        Habit.user_id == user.user_id,
                        Habit.is_active.is_(True),
                        Habit.frequency == "daily",
                    )
                )
                habits = habits_result.scalars().all()
                if not habits:
                    continue

                habit_ids = [h.id for h in habits]
                logged_result = await db.execute(
                    select(HabitLog.habit_id).where(
                        HabitLog.user_id == user.user_id,
                        HabitLog.habit_id.in_(habit_ids),
                        HabitLog.logged_at >= today_start,
                    )
                )
                logged_ids = {row[0] for row in logged_result.all()}

                incomplete = [h for h in habits if h.id not in logged_ids]
                if not incomplete:
                    continue

                names = ", ".join(h.name for h in incomplete)
                body = f"Nestor reminder: Don't forget your habits today — {names}!"

                await send_sms(user.phone_number, body)
                db.add(
                    NotificationLog(
                        user_id=user.user_id,
                        channel="sms",
                        type="habit_reminder",
                        to_address=user.phone_number,
                        body=body,
                        status="sent",
                    )
                )
                await db.commit()
                logger.info("Habit reminder sent user_id=%s habits=%d", user.user_id, len(incomplete))
            except Exception:
                logger.exception("Habit reminder failed for user_id=%s", user.user_id)


@scheduler.scheduled_job("cron", day_of_week="mon", hour=9, minute=0)
async def weekly_job_followup() -> None:
    """Monday 9 AM UTC: SMS users who have stale 'applied' job applications (>7 days)."""
    from cloud_service.app.integrations.twilio_client import send_sms  # lazy

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.phone_number.is_not(None)))
        users = result.scalars().all()

        for user in users:
            try:
                stale_result = await db.execute(
                    select(JobApplication).where(
                        JobApplication.user_id == user.user_id,
                        JobApplication.status == "applied",
                        JobApplication.applied_at <= stale_cutoff,
                    )
                )
                apps = stale_result.scalars().all()
                if not apps:
                    continue

                companies = ", ".join(a.company for a in apps[:5])
                suffix = f" and {len(apps) - 5} more" if len(apps) > 5 else ""
                body = (
                    f"Nestor follow-up: {len(apps)} application(s) with no update in 7+ days — "
                    f"{companies}{suffix}. Consider reaching out this week!"
                )

                await send_sms(user.phone_number, body)
                db.add(
                    NotificationLog(
                        user_id=user.user_id,
                        channel="sms",
                        type="job_followup",
                        to_address=user.phone_number,
                        body=body,
                        status="sent",
                    )
                )
                await db.commit()
                logger.info(
                    "Job follow-up sent user_id=%s apps=%d", user.user_id, len(apps)
                )
            except Exception:
                logger.exception("Job follow-up failed for user_id=%s", user.user_id)
