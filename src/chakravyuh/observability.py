"""Low-cardinality in-process Prometheus metrics without merchant identifiers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass

_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_HTTP_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})


@dataclass(frozen=True, slots=True)
class RequestMetricKey:
    method: str
    route: str
    status: int


class ProcessMetrics:
    """Concurrency-safe bounded metrics keyed only by registered route templates."""

    def __init__(self, *, version: str, environment: str, actions_enabled: bool) -> None:
        self._version = version
        self._environment = environment
        self._actions_enabled = actions_enabled
        self._requests: dict[RequestMetricKey, int] = defaultdict(int)
        self._duration_sum: dict[RequestMetricKey, float] = defaultdict(float)
        self._duration_buckets: dict[tuple[RequestMetricKey, float], int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def observe(
        self,
        *,
        method: str,
        route: str,
        status: int,
        duration_seconds: float,
    ) -> None:
        safe_route = route if route.startswith("/") and len(route) <= 255 else "unmatched"
        normalized_method = method.upper()
        key = RequestMetricKey(
            method=normalized_method if normalized_method in _HTTP_METHODS else "OTHER",
            route=safe_route,
            status=status if 100 <= status <= 599 else 0,
        )
        duration = max(0.0, duration_seconds)
        async with self._lock:
            self._requests[key] += 1
            self._duration_sum[key] += duration
            for bucket in _DURATION_BUCKETS:
                if duration <= bucket:
                    self._duration_buckets[(key, bucket)] += 1

    async def render_prometheus(self) -> str:
        async with self._lock:
            requests = dict(self._requests)
            duration_sums = dict(self._duration_sum)
            buckets = dict(self._duration_buckets)

        lines = [
            "# HELP chakravyuh_build_info Build and runtime environment information.",
            "# TYPE chakravyuh_build_info gauge",
            (
                'chakravyuh_build_info{environment="'
                f'{_escape(self._environment)}",version="{_escape(self._version)}"}} 1'
            ),
            "# HELP chakravyuh_actions_enabled Whether guarded provider actions are enabled.",
            "# TYPE chakravyuh_actions_enabled gauge",
            f"chakravyuh_actions_enabled {int(self._actions_enabled)}",
            "# HELP chakravyuh_http_requests_total Completed HTTP requests.",
            "# TYPE chakravyuh_http_requests_total counter",
        ]
        for key in sorted(requests, key=_sort_key):
            labels = _labels(key)
            lines.append(f"chakravyuh_http_requests_total{{{labels}}} {requests[key]}")
        lines.extend(
            (
                "# HELP chakravyuh_http_request_duration_seconds Request latency by route.",
                "# TYPE chakravyuh_http_request_duration_seconds histogram",
            )
        )
        for key in sorted(requests, key=_sort_key):
            labels = _labels(key)
            for bucket in _DURATION_BUCKETS:
                count = buckets.get((key, bucket), 0)
                lines.append(
                    "chakravyuh_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{bucket:g}"}} {count}'
                )
            lines.append(
                "chakravyuh_http_request_duration_seconds_bucket"
                f'{{{labels},le="+Inf"}} {requests[key]}'
            )
            lines.append(
                f"chakravyuh_http_request_duration_seconds_sum{{{labels}}} {duration_sums[key]:.9f}"
            )
            lines.append(
                f"chakravyuh_http_request_duration_seconds_count{{{labels}}} {requests[key]}"
            )
        return "\n".join(lines) + "\n"


def _labels(key: RequestMetricKey) -> str:
    return f'method="{_escape(key.method)}",route="{_escape(key.route)}",status="{key.status}"'


def _sort_key(key: RequestMetricKey) -> tuple[str, str, int]:
    return (key.route, key.method, key.status)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
