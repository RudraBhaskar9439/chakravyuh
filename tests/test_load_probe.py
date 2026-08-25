"""Bounded webhook load-probe tests."""

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
from pydantic import ValidationError

from chakravyuh.operations.load_probe import (
    LoadProbeConfig,
    LoadProbeReport,
    _model_hash,
    _payload,
    main,
    run_load_probe,
)

SECRET = "load-probe-test-secret"


async def test_load_probe_verifies_unique_and_duplicate_acknowledgements() -> None:
    seen: set[str] = set()
    active = 0
    maximum_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        body = await request.aread()
        signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert request.headers["X-Razorpay-Signature"] == signature
        event_id = request.headers["X-Razorpay-Event-Id"]
        duplicate = event_id in seen
        seen.add(event_id)
        active -= 1
        return httpx.Response(
            200 if duplicate else 202,
            json={"accepted": not duplicate},
        )

    config = LoadProbeConfig(
        base_url="http://127.0.0.1:8000",
        merchant_id="merchant_test",
        account_id="acc_test",
        run_id="run123",
        unique_events=5,
        journey_count=2,
        duplicate_deliveries=2,
        concurrency=3,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    ) as client:
        report = await run_load_probe(config, webhook_secret=SECRET, client=client)

    assert report.passed
    assert report.accepted_unique == 5
    assert report.confirmed_duplicates == 2
    assert report.journey_count == 2
    assert report.concurrency == 3
    assert report.total_attempts == 7
    assert report.transport_failures == 0
    assert report.recovered_after_retry == 0
    assert report.unrecovered_requests == 0

    tampered = report.model_dump(mode="json")
    tampered["total_attempts"] = 8
    draft = LoadProbeReport.model_construct(**tampered)
    tampered["report_sha256"] = _model_hash(draft, exclude={"report_sha256"})
    with pytest.raises(ValidationError, match="physical attempt count"):
        LoadProbeReport.model_validate(tampered)
    assert report.report_sha256
    assert report.status_counts == {"200": 2, "202": 5}
    assert maximum_active <= config.concurrency
    assert report.target_origin == "http://127.0.0.1:8000"
    assert SECRET not in json.dumps(report.model_dump(mode="json"))


@pytest.mark.parametrize(
    "replacement",
    [
        {"base_url": "https://staging.example"},
        {"base_url": "http://staging.example", "allow_remote": True},
        {"base_url": "http://user:password@localhost:8000"},
        {"base_url": "http://localhost:8000/path"},
        {"merchant_id": "../../escape"},
        {"account_id": "account/slash"},
        {"run_id": "spaces forbidden"},
        {"unique_events": 0},
        {"journey_count": 0},
        {"journey_count": 2, "unique_events": 1},
        {"duplicate_deliveries": 3, "unique_events": 2},
        {"concurrency": 0},
        {"timeout_seconds": 0},
        {"max_transport_retries": 6},
    ],
)
def test_load_probe_rejects_unsafe_or_unbounded_configuration(
    replacement: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "base_url": "http://localhost:8000",
        "merchant_id": "merchant_test",
        "account_id": "acc_test",
        "run_id": "run123",
    }
    values.update(replacement)
    with pytest.raises(ValueError):
        LoadProbeConfig(**values).validate()  # type: ignore[arg-type]


async def test_load_probe_rejects_short_secret() -> None:
    config = LoadProbeConfig(
        base_url="http://localhost:8000",
        merchant_id="merchant_test",
        account_id="acc_test",
        run_id="run123",
    )
    with pytest.raises(ValueError, match="at least 16"):
        await run_load_probe(config, webhook_secret="short")


async def test_load_probe_recovers_ambiguous_transport_failure_idempotently() -> None:
    seen: set[str] = set()
    failed_once = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal failed_once
        event_id = request.headers["X-Razorpay-Event-Id"]
        duplicate = event_id in seen
        seen.add(event_id)
        if not failed_once:
            failed_once = True
            raise httpx.ReadTimeout("response lost after durable insert", request=request)
        return httpx.Response(200 if duplicate else 202, json={"accepted": not duplicate})

    config = LoadProbeConfig(
        base_url="http://127.0.0.1:8000",
        merchant_id="merchant_test",
        account_id="acc_test",
        run_id="retry123",
        unique_events=2,
        duplicate_deliveries=1,
        concurrency=1,
        max_transport_retries=2,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    ) as client:
        report = await run_load_probe(config, webhook_secret=SECRET, client=client)

    assert report.passed
    assert report.accepted_unique == 2
    assert report.confirmed_duplicates == 1
    assert report.total_requests == 3
    assert report.total_attempts == 4
    assert report.transport_failures == 1
    assert report.recovered_after_retry == 1
    assert report.unrecovered_requests == 0


def test_load_probe_groups_events_without_creating_order_incidents() -> None:
    config = LoadProbeConfig(
        base_url="http://localhost:8000",
        merchant_id="merchant_test",
        account_id="acc_test",
        run_id="grouped",
        unique_events=4,
        journey_count=2,
    )

    payloads = [json.loads(_payload(config, index)[1]) for index in range(4)]
    invoice_ids = [item["payload"]["payment"]["entity"]["invoice_id"] for item in payloads]

    assert invoice_ids == [
        "inv_loadgrouped000000",
        "inv_loadgrouped000001",
        "inv_loadgrouped000000",
        "inv_loadgrouped000001",
    ]
    assert all("order_id" not in item["payload"]["payment"]["entity"] for item in payloads)


def test_load_probe_cli_requires_secret_environment(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CHAKRAVYUH_LOAD_WEBHOOK_SECRET", raising=False)

    status = main(["--merchant-id", "merchant", "--account-id", "account"])

    assert status == 2
    assert "CHAKRAVYUH_LOAD_WEBHOOK_SECRET is required" in capsys.readouterr().err
