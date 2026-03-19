"""Add user_skill_channels table for per-skill delivery channel preferences.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_skill_channels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False, server_default="web"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "skill_id", name="uq_user_skill_channel"),
    )
    op.create_index("ix_user_skill_channels_user_id", "user_skill_channels", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_skill_channels_user_id", "user_skill_channels")
    op.drop_table("user_skill_channels")
