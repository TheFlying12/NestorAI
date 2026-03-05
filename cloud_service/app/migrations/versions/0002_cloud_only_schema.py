"""Cloud-only schema: users, conversations, messages, summaries, transactions, skill_memories.
Also adds user_id FK to devices (nullable, backward-compat).

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-05

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(128), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("auth_provider", sa.String(32), nullable=False, server_default="clerk"),
        sa.Column("api_key_encrypted", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── devices: add nullable user_id FK ─────────────────────────────────────
    op.add_column("devices", sa.Column("user_id", sa.String(128), nullable=True))
    op.create_foreign_key(
        "fk_devices_user_id", "devices", "users", ["user_id"], ["user_id"], ondelete="SET NULL"
    )

    # ── conversations ─────────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False, server_default="web"),
        sa.Column("channel_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("skill_id", sa.String(64), nullable=False, server_default="general"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # ── conversation_messages ─────────────────────────────────────────────────
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conv_messages_conversation_id", "conversation_messages", ["conversation_id"])

    # ── conversation_summaries ────────────────────────────────────────────────
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("summary_text", sa.Text, nullable=False),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("token_estimate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("merchant", sa.String(128), nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])

    # ── skill_memories ────────────────────────────────────────────────────────
    op.create_table(
        "skill_memories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("skill_id", "user_id", "key", name="uq_skill_memory"),
    )


def downgrade() -> None:
    op.drop_table("skill_memories")
    op.drop_index("ix_transactions_user_id", "transactions")
    op.drop_table("transactions")
    op.drop_table("conversation_summaries")
    op.drop_index("ix_conv_messages_conversation_id", "conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_id", "conversations")
    op.drop_table("conversations")
    op.drop_constraint("fk_devices_user_id", "devices", type_="foreignkey")
    op.drop_column("devices", "user_id")
    op.drop_table("users")
