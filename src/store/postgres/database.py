"""PostgreSQL async database engine and session factory.

See docs/architecture/02-foundation.md Section 5.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import DatabaseSettings


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Create async SQLAlchemy engine."""
    return create_async_engine(
        settings.dsn,
        pool_size=settings.pool_max_size,
        pool_pre_ping=True,
        echo=settings.echo,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set PostgreSQL session variable for Row-Level Security."""
    await session.execute(
        __import__("sqlalchemy").text(f"SET app.current_tenant = '{tenant_id}'")
    )
