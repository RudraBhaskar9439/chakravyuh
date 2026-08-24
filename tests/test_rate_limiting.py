"""Rate-limiter correctness and fail-closed behavior."""

from typing import Any

import pytest
from redis.exceptions import RedisError

from chakravyuh.config import Settings
from chakravyuh.infrastructure.rate_limiting import (
    MemoryFixedWindowRateLimiter,
    RateLimiterUnavailableError,
    RedisFixedWindowRateLimiter,
    build_rate_limiter,
)


async def test_memory_limiter_enforces_limit_and_resets_window() -> None:
    now = 15.0
    limiter = MemoryFixedWindowRateLimiter(clock=lambda: now)

    first = await limiter.consume("principal:maker", limit=2, window_seconds=10)
    second = await limiter.consume("principal:maker", limit=2, window_seconds=10)
    denied = await limiter.consume("principal:maker", limit=2, window_seconds=10)
    now = 21.0
    reset = await limiter.consume("principal:maker", limit=2, window_seconds=10)

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert (denied.allowed, denied.remaining, denied.retry_after_seconds) == (False, 0, 5)
    assert (reset.allowed, reset.remaining) == (True, 1)
    await limiter.close()


async def test_memory_limiter_is_bounded_and_purges_expired_keys() -> None:
    now = 1.0
    limiter = MemoryFixedWindowRateLimiter(clock=lambda: now, maximum_keys=1)
    await limiter.consume("first", limit=1, window_seconds=10)

    with pytest.raises(RateLimiterUnavailableError):
        await limiter.consume("second", limit=1, window_seconds=10)

    now = 11.0
    assert (await limiter.consume("second", limit=1, window_seconds=10)).allowed


class _RedisClient:
    def __init__(self, *, count: object = "2", ttl: int = 8, failure: bool = False) -> None:
        self.count = count
        self.ttl_value = ttl
        self.failure = failure
        self.closed = False
        self.arguments: tuple[object, ...] | None = None

    async def eval(self, *arguments: object) -> object:
        self.arguments = arguments
        if self.failure:
            raise RedisError
        return self.count

    async def ttl(self, _: str) -> int:
        return self.ttl_value

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_limiter_hashes_keys_and_returns_atomic_count() -> None:
    client = _RedisClient()
    limiter = RedisFixedWindowRateLimiter(
        "redis://unused",
        prefix="test-rate",
        client=client,  # type: ignore[arg-type]
    )

    decision = await limiter.consume("sensitive-client-identity", limit=3)

    assert (decision.allowed, decision.remaining, decision.retry_after_seconds) == (True, 1, 8)
    assert client.arguments is not None
    redis_key = str(client.arguments[2])
    assert redis_key.startswith("test-rate:")
    assert "sensitive-client-identity" not in redis_key
    await limiter.close()
    assert client.closed


async def test_redis_limiter_fails_closed_on_backend_or_type_errors() -> None:
    for client in (_RedisClient(failure=True), _RedisClient(count=object())):
        limiter = RedisFixedWindowRateLimiter(
            "redis://unused",
            prefix="test-rate",
            client=client,  # type: ignore[arg-type]
        )
        with pytest.raises(RateLimiterUnavailableError):
            await limiter.consume("principal", limit=1)


async def test_rate_limiter_rejects_invalid_bounds() -> None:
    limiter = MemoryFixedWindowRateLimiter()
    for key, limit, window in (("", 1, 60), ("x" * 513, 1, 60), ("x", 0, 60), ("x", 1, 0)):
        with pytest.raises(ValueError, match="rate-limit"):
            await limiter.consume(key, limit=limit, window_seconds=window)
    with pytest.raises(ValueError, match="positive"):
        MemoryFixedWindowRateLimiter(maximum_keys=0)


def test_rate_limiter_factory_selects_configured_backend(monkeypatch: Any) -> None:
    assert isinstance(build_rate_limiter(Settings()), MemoryFixedWindowRateLimiter)
    monkeypatch.setattr(
        "chakravyuh.infrastructure.rate_limiting.Redis.from_url",
        lambda *_args, **_kwargs: _RedisClient(),
    )
    assert isinstance(
        build_rate_limiter(Settings(rate_limit_backend="redis")),
        RedisFixedWindowRateLimiter,
    )
