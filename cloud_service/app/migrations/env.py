import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from cloud_service.app.db import Base
import cloud_service.app.models  # noqa: F401 — register ORM models

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = os.environ["DATABASE_URL"]
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    connectable = create_async_engine(url)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
