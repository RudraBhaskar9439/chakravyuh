"""PostgreSQL engine lifecycle and transaction factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chakravyuh.config import Settings


class Database:
    """Own the process-local SQLAlchemy engine and its connection pool."""

    def __init__(self, settings: Settings) -> None:
        self._engine: AsyncEngine = create_async_engine(
            settings.postgres_dsn,
            pool_pre_ping=True,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_timeout=settings.postgres_pool_timeout_seconds,
            connect_args={
                "server_settings": {
                    "application_name": "chakravyuh",
                    "statement_timeout": str(settings.postgres_statement_timeout_ms),
                }
            },
        )
        self.session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield one session enclosed in an atomic database transaction."""
        async with self.session_factory() as session, session.begin():
            yield session

    async def ping(self) -> None:
        """Prove that a connection can execute a round trip."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Release all pooled connections during process shutdown."""
        await self._engine.dispose()
