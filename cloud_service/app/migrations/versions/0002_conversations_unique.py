"""Add unique constraint on conversations(user_id, channel, channel_id, skill_id).

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-13
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_conversation",
        "conversations",
        ["user_id", "channel", "channel_id", "skill_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_conversation", "conversations", type_="unique")
