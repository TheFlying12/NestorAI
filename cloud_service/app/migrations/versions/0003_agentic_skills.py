"""Agentic skills — job_applications, habits, habit_logs.

Revision ID: 0003
Revises: 0001
Create Date: 2026-03-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── job_applications ───────────────────────────────────────────────────────
    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company", sa.String(128), nullable=False),
        sa.Column("role", sa.String(128), nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("salary_range", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="applied"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_applications_user_id", "job_applications", ["user_id"])
    op.create_index("ix_job_applications_status", "job_applications", ["status"])

    # ── habits ─────────────────────────────────────────────────────────────────
    op.create_table(
        "habits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False, server_default="daily"),
        sa.Column("target_per_week", sa.Integer, nullable=False, server_default="7"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_habits_user_id", "habits", ["user_id"])

    # ── habit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "habit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "habit_id",
            sa.Integer,
            sa.ForeignKey("habits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("note", sa.Text, nullable=True),
    )
    op.create_index("ix_habit_logs_habit_id", "habit_logs", ["habit_id"])
    op.create_index("ix_habit_logs_user_id", "habit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_habit_logs_user_id", "habit_logs")
    op.drop_index("ix_habit_logs_habit_id", "habit_logs")
    op.drop_table("habit_logs")
    op.drop_index("ix_habits_user_id", "habits")
    op.drop_table("habits")
    op.drop_index("ix_job_applications_status", "job_applications")
    op.drop_index("ix_job_applications_user_id", "job_applications")
    op.drop_table("job_applications")
