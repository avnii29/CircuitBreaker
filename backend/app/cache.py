from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import settings

_redis = None
_memory_hits: dict[str, deque[float]] = defaultdict(deque)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _reset_redis() -> None:
    global _redis
    _redis = None


async def _redis_client():
    global _redis
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return None
    if _redis is None:
        from redis.asyncio import Redis

        try:
            _redis = Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception:
            _reset_redis()
            return None
    return _redis


async def incr_window(key: str, window_seconds: int = 60) -> int:
    client = await _redis_client()
    now = time.time()
    if client is not None:
        try:
            pipe = client.pipeline()
            member = f"{now}:{id(key)}:{now}"
            await pipe.zadd(key, {member: now})
            await pipe.zremrangebyscore(key, 0, now - window_seconds)
            await pipe.zcard(key)
            await pipe.expire(key, window_seconds + 5)
            results = await pipe.execute()
            return int(results[2] or 0)
        except Exception:
            _reset_redis()

    from app.db.session import session_scope
    from app.db.tables import RateHitRow

    cutoff = _utcnow() - timedelta(seconds=window_seconds)
    async with session_scope() as session:
        session.add(RateHitRow(bucket=key, created_at=_utcnow()))
        await session.flush()
        await session.execute(delete(RateHitRow).where(RateHitRow.created_at < cutoff, RateHitRow.bucket == key))
        count = (
            await session.execute(
                select(func.count(RateHitRow.id)).where(RateHitRow.bucket == key, RateHitRow.created_at >= cutoff)
            )
        ).scalar() or 0
        return int(count)


async def ping_cache() -> bool:
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return True
    client = await _redis_client()
    if client is None:
        return False
    try:
        await client.ping()
        return True
    except Exception:
        _reset_redis()
        return False
