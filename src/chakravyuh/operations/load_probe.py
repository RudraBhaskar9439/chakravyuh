"""Bounded signed-webhook load and idempotency probe for local or staging gates."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field


class LoadProbeReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    target_origin: str
    unique_events: int = Field(ge=1)
    duplicate_deliveries: int = Field(ge=0)
    total_requests: int = Field(ge=1)
    accepted_unique: int = Field(ge=0)
    confirmed_duplicates: int = Field(ge=0)
    status_counts: dict[str, int]
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    requests_per_second: float = Field(ge=0)
    passed: bool


@dataclass(frozen=True, slots=True)
class LoadProbeConfig:
    base_url: str
    merchant_id: str
    account_id: str
    run_id: str
    unique_events: int = 100
    duplicate_deliveries: int = 20
    concurrency: int = 10
    timeout_seconds: float = 10
    allow_remote: bool = False

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            msg = "base URL must be an absolute HTTP(S) origin"
            raise ValueError(msg)
        if (parsed.path not in {"", "/"}) or parsed.query or parsed.fragment:
            msg = "base URL must not contain a path, query, or fragment"
            raise ValueError(msg)
        if not self.allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            msg = "remote load probes require --allow-remote"
            raise ValueError(msg)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and parsed.scheme != "https":
            msg = "remote load probes require HTTPS"
            raise ValueError(msg)
        if parsed.username is not None or parsed.password is not None:
            msg = "base URL must not contain credentials"
            raise ValueError(msg)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,255}", self.merchant_id) is None:
            msg = "merchant ID must contain 1..255 URL-safe identifier characters"
            raise ValueError(msg)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,255}", self.account_id) is None:
            msg = "account ID must contain 1..255 URL-safe identifier characters"
            raise ValueError(msg)
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", self.run_id) is None:
            msg = "run ID must contain 1..64 alphanumeric characters"
            raise ValueError(msg)
        if not 1 <= self.unique_events <= 100_000:
            msg = "unique event count must be 1..100000"
            raise ValueError(msg)
        if not 0 <= self.duplicate_deliveries <= self.unique_events:
            msg = "duplicate deliveries must be between zero and unique event count"
            raise ValueError(msg)
        if not 1 <= self.concurrency <= 500 or not 0 < self.timeout_seconds <= 60:
            msg = "concurrency must be 1..500 and timeout must be greater than 0 and at most 60"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _DeliveryResult:
    status_code: int
    accepted: bool | None
    latency_ms: float


async def run_load_probe(
    config: LoadProbeConfig,
    *,
    webhook_secret: str,
    client: httpx.AsyncClient | None = None,
) -> LoadProbeReport:
    config.validate()
    if len(webhook_secret) < 16:
        msg = "load-probe webhook secret must contain at least 16 characters"
        raise ValueError(msg)
    payloads = [_payload(config, index) for index in range(config.unique_events)]
    started = perf_counter()
    if client is None:
        limits = httpx.Limits(
            max_connections=config.concurrency,
            max_keepalive_connections=config.concurrency,
        )
        async with httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
        ) as owned_client:
            unique_results = await _deliver_batch(owned_client, config, webhook_secret, payloads)
            duplicate_results = await _deliver_batch(
                owned_client,
                config,
                webhook_secret,
                payloads[: config.duplicate_deliveries],
            )
    else:
        unique_results = await _deliver_batch(client, config, webhook_secret, payloads)
        duplicate_results = await _deliver_batch(
            client,
            config,
            webhook_secret,
            payloads[: config.duplicate_deliveries],
        )
    elapsed = max(perf_counter() - started, 1e-9)
    all_results = (*unique_results, *duplicate_results)
    latencies = sorted(result.latency_ms for result in all_results)
    accepted_unique = sum(
        result.status_code == 202 and result.accepted is True for result in unique_results
    )
    confirmed_duplicates = sum(
        result.status_code == 200 and result.accepted is False for result in duplicate_results
    )
    statuses = Counter(str(result.status_code) for result in all_results)
    passed = (
        accepted_unique == config.unique_events
        and confirmed_duplicates == config.duplicate_deliveries
        and len(all_results) == config.unique_events + config.duplicate_deliveries
    )
    parsed = urlsplit(config.base_url)
    return LoadProbeReport(
        run_id=config.run_id,
        target_origin=f"{parsed.scheme}://{parsed.netloc}",
        unique_events=config.unique_events,
        duplicate_deliveries=config.duplicate_deliveries,
        total_requests=len(all_results),
        accepted_unique=accepted_unique,
        confirmed_duplicates=confirmed_duplicates,
        status_counts=dict(sorted(statuses.items())),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        requests_per_second=len(all_results) / elapsed,
        passed=passed,
    )


async def _deliver_batch(
    client: httpx.AsyncClient,
    config: LoadProbeConfig,
    secret: str,
    payloads: list[tuple[str, bytes]],
) -> tuple[_DeliveryResult, ...]:
    async def deliver(item: tuple[str, bytes]) -> _DeliveryResult:
        event_id, body = item
        started = perf_counter()
        try:
            response = await client.post(
                f"/v1/webhooks/razorpay/{config.merchant_id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Event-Id": event_id,
                    "X-Razorpay-Signature": hmac.new(secret.encode(), body, "sha256").hexdigest(),
                },
            )
            data = response.json() if response.status_code in {200, 202} else {}
            accepted = data.get("accepted") if isinstance(data, dict) else None
            return _DeliveryResult(
                status_code=response.status_code,
                accepted=accepted if isinstance(accepted, bool) else None,
                latency_ms=(perf_counter() - started) * 1_000,
            )
        except (httpx.HTTPError, ValueError):
            return _DeliveryResult(
                status_code=0,
                accepted=None,
                latency_ms=(perf_counter() - started) * 1_000,
            )

    next_index = 0
    results: list[_DeliveryResult] = []

    async def worker() -> None:
        nonlocal next_index
        while next_index < len(payloads):
            item = payloads[next_index]
            next_index += 1
            results.append(await deliver(item))

    worker_count = min(config.concurrency, len(payloads))
    await asyncio.gather(*(worker() for _ in range(worker_count)))
    return tuple(results)


def _payload(config: LoadProbeConfig, index: int) -> tuple[str, bytes]:
    payment_id = f"pay_load{config.run_id}{index:06d}"
    event_id = f"load-{config.run_id}-{index:06d}"
    document = {
        "account_id": config.account_id,
        "contains": ["payment"],
        "created_at": 1_787_572_000 + index,
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "amount": 10_000,
                    "currency": "INR",
                    "entity": "payment",
                    "id": payment_id,
                    "status": "captured",
                }
            }
        },
    }
    return event_id, json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


def _percentile(values: list[float], percentile: float) -> float:
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile)))
    return values[index]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send bounded signed webhook load and verify duplicate acknowledgements.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--unique-events", type=int, default=100)
    parser.add_argument("--duplicate-deliveries", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--allow-remote", action="store_true")
    return parser


async def _load_probe_main_async(args: argparse.Namespace) -> int:
    secret = os.environ.get("CHAKRAVYUH_LOAD_WEBHOOK_SECRET", "")
    if not secret:
        sys.stderr.write("load probe rejected: CHAKRAVYUH_LOAD_WEBHOOK_SECRET is required\n")
        return 2
    try:
        report = await run_load_probe(
            LoadProbeConfig(
                base_url=args.base_url,
                merchant_id=args.merchant_id,
                account_id=args.account_id,
                run_id=args.run_id or uuid4().hex[:12],
                unique_events=args.unique_events,
                duplicate_deliveries=args.duplicate_deliveries,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
                allow_remote=args.allow_remote,
            ),
            webhook_secret=secret,
        )
    except ValueError as failure:
        sys.stderr.write(f"load probe rejected: {failure}\n")
        return 2
    sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_load_probe_main_async(_parser().parse_args(argv)))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
