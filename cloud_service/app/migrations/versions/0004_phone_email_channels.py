"""Add phone_number, notification_email to users; create notification_logs.

Revision ID: 0004
Revises: 0002, 0003  (merge point)
Create Date: 2026-03-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = ("0002", "0003")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users — new contact fields ──────────────────────────────────────────────
    op.add_column("users", sa.Column("phone_number", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("notification_email", sa.String(255), nullable=True))

    # ── notification_logs — audit trail for all sent notifications ──────────────
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(16), nullable=False),   # 'sms' | 'email'
        sa.Column("type", sa.String(32), nullable=False),      # 'budget_alert' | 'habit_reminder' | 'job_followup' | 'agent_send' | 'inbound_reply'
        sa.Column("to_address", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_notification_logs_user_id", "notification_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_logs_user_id", "notification_logs")
    op.drop_table("notification_logs")
    op.drop_column("users", "notification_email")
    op.drop_column("users", "phone_number")
