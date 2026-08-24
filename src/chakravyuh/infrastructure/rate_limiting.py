"""Bounded fixed-window rate limiting with a Redis production backend."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from chakravyuh.config import Settings


class RateLimiterUnavailableError(RuntimeError):
    """The configured authoritative limiter could not make a decision."""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision: ...

    async def close(self) -> None: ...


class MemoryFixedWindowRateLimiter:
    """Per-process development/test limiter with bounded key retention."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        maximum_keys: int = 10_000,
    ) -> None:
        if maximum_keys < 1:
            msg = "maximum rate-limit keys must be positive"
            raise ValueError(msg)
        self._clock = clock
        self._maximum_keys = maximum_keys
        self._windows: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        _validate_request(key, limit, window_seconds)
        now = self._clock()
        window = int(now // window_seconds)
        async with self._lock:
            if key not in self._windows and len(self._windows) >= self._maximum_keys:
                self._windows = {
                    stored_key: state
                    for stored_key, state in self._windows.items()
                    if state[0] == window
                }
                if len(self._windows) >= self._maximum_keys:
                    raise RateLimiterUnavailableError
            previous_window, previous_count = self._windows.get(key, (-1, 0))
            count = previous_count + 1 if previous_window == window else 1
            self._windows[key] = (window, count)
        retry_after = max(1, math.ceil(((window + 1) * window_seconds) - now))
        return RateLimitDecision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after_seconds=retry_after,
        )

    async def close(self) -> None:
        return None


class RedisFixedWindowRateLimiter:
    """Atomic cluster-wide limiter; failures deny operator authentication."""

    _CONSUME_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

    def __init__(self, dsn: str, *, prefix: str, client: Redis | None = None) -> None:
        self._prefix = prefix
        self._client = client or Redis.from_url(
            dsn,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    async def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        _validate_request(key, limit, window_seconds)
        redis_key = f"{self._prefix}:{hashlib.sha256(key.encode()).hexdigest()}"
        try:
            raw_count = await cast(
                "Awaitable[object]",
                self._client.eval(
                    self._CONSUME_SCRIPT,
                    1,
                    redis_key,
                    window_seconds,
                ),
            )
            ttl = await self._client.ttl(redis_key)
            count = int(cast("int | str", raw_count))
        except (RedisError, TypeError, ValueError) as error:
            raise RateLimiterUnavailableError from error
        return RateLimitDecision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after_seconds=max(1, int(ttl)),
        )

    async def close(self) -> None:
        await cast("Awaitable[object]", self._client.aclose())


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == "redis":
        return RedisFixedWindowRateLimiter(
            settings.redis_dsn,
            prefix=settings.rate_limit_prefix,
        )
    return MemoryFixedWindowRateLimiter()


def _validate_request(key: str, limit: int, window_seconds: int) -> None:
    if not key or len(key) > 512:
        msg = "rate-limit keys must contain between 1 and 512 characters"
        raise ValueError(msg)
    if limit < 1 or window_seconds < 1:
        msg = "rate-limit bounds must be positive"
        raise ValueError(msg)
