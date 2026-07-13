"""Database engine and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from pilgrimage_agent.config import get_settings


class Base(DeclarativeBase):
    """Base for all persisted application records."""


def create_engine() -> AsyncEngine:
    url = get_settings().database_url.get_secret_value()
    return create_async_engine(url, pool_pre_ping=True)


async def session_scope() -> AsyncIterator[AsyncSession]:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()

