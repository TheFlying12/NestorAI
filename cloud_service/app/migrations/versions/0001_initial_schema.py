"""Initial schema: devices, pairing_codes, commands, transfer_nonces

Revision ID: 0001
Revises:
Create Date: 2026-03-04

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(64), primary_key=True),
        sa.Column("device_token_hash", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("factory_secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installed_skills", sa.Text, nullable=False, server_default=""),
    )

    op.create_table(
        "pairing_codes",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "commands",
        sa.Column("command_id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_commands_device_id", "commands", ["device_id"])
    op.create_index("ix_commands_idempotency_key", "commands", ["idempotency_key"])

    op.create_table(
        "transfer_nonces",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("new_owner_id", sa.String(64), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("transfer_nonces")
    op.drop_index("ix_commands_idempotency_key", "commands")
    op.drop_index("ix_commands_device_id", "commands")
    op.drop_table("commands")
    op.drop_table("pairing_codes")
    op.drop_table("devices")
