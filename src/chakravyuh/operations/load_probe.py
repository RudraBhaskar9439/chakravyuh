"""Bounded signed-webhook load and idempotency probe for local or staging gates."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from pydantic import BaseModel, ConfigDict, Field, model_validator

LOAD_PROBE_REPORT_VERSION = "signed-ingress-load-report-v2"


class LoadProbeReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = LOAD_PROBE_REPORT_VERSION
    run_id: str
    target_origin: str
    merchant_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unique_events: int = Field(ge=1)
    journey_count: int = Field(ge=1)
    duplicate_deliveries: int = Field(ge=0)
    concurrency: int = Field(ge=1, le=500)
    total_requests: int = Field(ge=1)
    total_attempts: int = Field(ge=1)
    transport_failures: int = Field(ge=0)
    recovered_after_retry: int = Field(ge=0)
    unrecovered_requests: int = Field(ge=0)
    accepted_unique: int = Field(ge=0)
    confirmed_duplicates: int = Field(ge=0)
    status_counts: dict[str, int]
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    requests_per_second: float = Field(ge=0)
    passed: bool
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> LoadProbeReport:
        if self.journey_count > self.unique_events:
            msg = "load-probe journey count cannot exceed unique events"
            raise ValueError(msg)
        if self.total_requests != self.unique_events + self.duplicate_deliveries:
            msg = "load-probe logical request count does not match its workload"
            raise ValueError(msg)
        if self.total_attempts != self.total_requests + self.transport_failures:
            msg = "load-probe physical attempt count does not match transport failures"
            raise ValueError(msg)
        if self.total_attempts > self.total_requests * 6:
            msg = "load-probe physical attempts exceed the global retry bound"
            raise ValueError(msg)
        if sum(self.status_counts.values()) != self.total_requests:
            msg = "load-probe status counts do not match logical requests"
            raise ValueError(msg)
        if any(count < 0 for count in self.status_counts.values()):
            msg = "load-probe status counts cannot be negative"
            raise ValueError(msg)
        if self.unrecovered_requests != self.status_counts.get("0", 0):
            msg = "load-probe unrecovered request count does not match transport outcomes"
            raise ValueError(msg)
        if self.accepted_unique > self.unique_events:
            msg = "load-probe accepted unique count exceeds the configured workload"
            raise ValueError(msg)
        if self.confirmed_duplicates > self.duplicate_deliveries:
            msg = "load-probe confirmed duplicate count exceeds deliberate redeliveries"
            raise ValueError(msg)
        if (
            self.recovered_after_retry > self.transport_failures
            or self.recovered_after_retry > self.total_requests
        ):
            msg = "load-probe recovered retry count exceeds transport failures"
            raise ValueError(msg)
        if self.passed != _load_probe_passed(self):
            msg = "load-probe pass flag does not match its exact ingress gates"
            raise ValueError(msg)
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            msg = "load-probe report hash does not match its canonical content"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class LoadProbeConfig:
    base_url: str
    merchant_id: str
    account_id: str
    run_id: str
    unique_events: int = 100
    journey_count: int | None = None
    duplicate_deliveries: int = 20
    concurrency: int = 10
    timeout_seconds: float = 10
    max_transport_retries: int = 2
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
        if self.journey_count is not None and not 1 <= self.journey_count <= self.unique_events:
            msg = "journey count must be between one and unique event count"
            raise ValueError(msg)
        if not 0 <= self.duplicate_deliveries <= self.unique_events:
            msg = "duplicate deliveries must be between zero and unique event count"
            raise ValueError(msg)
        if not 1 <= self.concurrency <= 500 or not 0 < self.timeout_seconds <= 60:
            msg = "concurrency must be 1..500 and timeout must be greater than 0 and at most 60"
            raise ValueError(msg)
        if not 0 <= self.max_transport_retries <= 5:
            msg = "maximum transport retries must be between zero and five"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _DeliveryResult:
    status_code: int
    accepted: bool | None
    latency_ms: float
    transport_failures: int


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
    accepted_unique = sum(_durably_accepted_unique(result) for result in unique_results)
    confirmed_duplicates = sum(
        result.status_code == 200 and result.accepted is False for result in duplicate_results
    )
    statuses = Counter(str(result.status_code) for result in all_results)
    transport_failures = sum(result.transport_failures for result in all_results)
    recovered_after_retry = sum(
        result.transport_failures > 0 and result.status_code in {200, 202} for result in all_results
    )
    unrecovered_requests = sum(result.status_code == 0 for result in all_results)
    parsed = urlsplit(config.base_url)
    journey_count = config.journey_count or config.unique_events
    draft = LoadProbeReport.model_construct(
        report_version=LOAD_PROBE_REPORT_VERSION,
        run_id=config.run_id,
        target_origin=f"{parsed.scheme}://{parsed.netloc}",
        merchant_id_sha256=hashlib.sha256(config.merchant_id.encode()).hexdigest(),
        account_id_sha256=hashlib.sha256(config.account_id.encode()).hexdigest(),
        unique_events=config.unique_events,
        journey_count=journey_count,
        duplicate_deliveries=config.duplicate_deliveries,
        concurrency=config.concurrency,
        total_requests=len(all_results),
        total_attempts=len(all_results) + transport_failures,
        transport_failures=transport_failures,
        recovered_after_retry=recovered_after_retry,
        unrecovered_requests=unrecovered_requests,
        accepted_unique=accepted_unique,
        confirmed_duplicates=confirmed_duplicates,
        status_counts=dict(sorted(statuses.items())),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        requests_per_second=len(all_results) / elapsed,
        passed=False,
        report_sha256="0" * 64,
    )
    with_pass = draft.model_copy(update={"passed": _load_probe_passed(draft)})
    return LoadProbeReport.model_validate(
        {
            **with_pass.model_dump(mode="json"),
            "report_sha256": _model_hash(with_pass, exclude={"report_sha256"}),
        }
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
        transport_failures = 0
        for attempt in range(config.max_transport_retries + 1):
            try:
                response = await client.post(
                    f"/v1/webhooks/razorpay/{config.merchant_id}",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Razorpay-Event-Id": event_id,
                        "X-Razorpay-Signature": hmac.new(
                            secret.encode(), body, "sha256"
                        ).hexdigest(),
                    },
                )
                data = response.json() if response.status_code in {200, 202} else {}
                accepted = data.get("accepted") if isinstance(data, dict) else None
                return _DeliveryResult(
                    status_code=response.status_code,
                    accepted=accepted if isinstance(accepted, bool) else None,
                    latency_ms=(perf_counter() - started) * 1_000,
                    transport_failures=transport_failures,
                )
            except (httpx.HTTPError, ValueError):
                transport_failures += 1
                if attempt < config.max_transport_retries:
                    await asyncio.sleep(min(0.05 * (2**attempt), 0.2))
        return _DeliveryResult(
            status_code=0,
            accepted=None,
            latency_ms=(perf_counter() - started) * 1_000,
            transport_failures=transport_failures,
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


def _durably_accepted_unique(result: _DeliveryResult) -> bool:
    if result.status_code == 202 and result.accepted is True:
        return True
    return bool(
        result.transport_failures > 0 and result.status_code == 200 and result.accepted is False
    )


def _load_probe_passed(report: LoadProbeReport) -> bool:
    return bool(
        report.accepted_unique == report.unique_events
        and report.confirmed_duplicates == report.duplicate_deliveries
        and report.unrecovered_requests == 0
        and set(report.status_counts).issubset({"200", "202"})
    )


def _payload(config: LoadProbeConfig, index: int) -> tuple[str, bytes]:
    payment_id = f"pay_load{config.run_id}{index:06d}"
    event_id = f"load-{config.run_id}-{index:06d}"
    journey_count = config.journey_count or config.unique_events
    invoice_id = f"inv_load{config.run_id}{index % journey_count:06d}"
    document = {
        "account_id": config.account_id,
        "contains": ["payment"],
        "created_at": 1_787_485_600 + (index % 86_400),
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "amount": 10_000,
                    "currency": "INR",
                    "entity": "payment",
                    "id": payment_id,
                    "invoice_id": invoice_id,
                    "status": "captured",
                }
            }
        },
    }
    return event_id, json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


def _percentile(values: list[float], percentile: float) -> float:
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile)))
    return values[index]


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    canonical = json.dumps(
        model.model_dump(mode="json", exclude=exclude),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send bounded signed webhook load and verify duplicate acknowledgements.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--unique-events", type=int, default=100)
    parser.add_argument(
        "--journey-count",
        type=int,
        default=None,
        help="group events into this many invoice-correlated evidence journeys",
    )
    parser.add_argument("--duplicate-deliveries", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--max-transport-retries", type=int, default=2)
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
                journey_count=args.journey_count,
                duplicate_deliveries=args.duplicate_deliveries,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
                max_transport_retries=args.max_transport_retries,
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
