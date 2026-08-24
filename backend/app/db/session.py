from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.tables import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_ready = False


def _build_engine() -> AsyncEngine:
    url = settings.DATABASE_URL
    kwargs: dict = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.rstrip("/") == "sqlite+aiosqlite://" or ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    return create_async_engine(url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


async def init_db() -> None:
    global _ready
    if settings.AUTO_CREATE_SCHEMA:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    _ready = True


async def ensure_db() -> None:
    if not _ready:
        await init_db()


async def ping_db() -> bool:
    from sqlalchemy import text

    try:
        await ensure_db()
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    global _engine, _session_factory, _ready
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _ready = False


async def dispose_and_reload() -> None:
    await dispose_engine()
    await ensure_db()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    await ensure_db()
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
