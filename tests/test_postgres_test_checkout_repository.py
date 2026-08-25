"""Real PostgreSQL proof for Test Checkout idempotency and append-only records."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from chakravyuh.config import Settings
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import TestCheckoutError as CheckoutError
from chakravyuh.domain.errors import TestCheckoutErrorCode as CheckoutErrorCode
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    ProviderManualCaptureOrder,
    create_test_checkout_order,
    create_test_checkout_verification,
)
from chakravyuh.domain.test_checkout import (
    TestCheckoutOrder as CheckoutOrder,
)
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.test_checkout_repository import (
    PostgresTestCheckoutRepository,
)

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None,
    reason="CHAKRAVYUH_TEST_POSTGRES_DSN is required for PostgreSQL integration proofs",
)


def _database() -> Database:
    assert TEST_POSTGRES_DSN is not None
    return Database(Settings(environment="test", postgres_dsn=TEST_POSTGRES_DSN))


def _order() -> CheckoutOrder:
    now = datetime.now(UTC)
    identity = uuid4().hex
    return create_test_checkout_order(
        merchant_id=f"merchant-{identity}",
        provider_order=ProviderManualCaptureOrder(
            order_id=f"order_{identity}",
            amount=Money(amount_subunits=1_000, currency="INR"),
            receipt=f"chkr-{identity[:32]}",
            provider_created_at=now,
        ),
        created_by="integration-maker",
        request_id=f"request-{identity}",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )


async def test_postgres_checkout_records_order_and_verification_idempotently() -> None:
    database = _database()
    repository = PostgresTestCheckoutRepository(database)
    order = _order()
    payment = ProviderPaymentState(
        payment_id=f"pay_{uuid4().hex}",
        status=PaymentStatus.AUTHORIZED,
        amount=order.provider_order.amount,
        captured=False,
        order_id=order.provider_order.order_id,
    )
    first_verification = create_test_checkout_verification(
        checkout_id=order.checkout_id,
        payment=payment,
        verified_by="integration-maker",
        request_id="verify-first",
        verified_at=datetime.now(UTC),
    )
    retry_verification = create_test_checkout_verification(
        checkout_id=order.checkout_id,
        payment=payment,
        verified_by="integration-maker",
        request_id="verify-retry",
        verified_at=datetime.now(UTC),
    )
    try:
        assert await repository.record_order(order) == order
        assert await repository.record_order(order) == order
        assert await repository.get_order(order.provider_order.order_id) == order
        assert await repository.get_order(f"order_{uuid4().hex}") is None
        first = await repository.record_verification(first_verification)
        retry = await repository.record_verification(retry_verification)
        assert retry == first
    finally:
        await database.close()


async def test_postgres_checkout_detects_identity_conflict_and_rejects_mutation() -> None:
    database = _database()
    repository = PostgresTestCheckoutRepository(database)
    order = _order()
    payment = ProviderPaymentState(
        payment_id=f"pay_{uuid4().hex}",
        status=PaymentStatus.AUTHORIZED,
        amount=order.provider_order.amount,
        captured=False,
        order_id=order.provider_order.order_id,
    )
    verification = create_test_checkout_verification(
        checkout_id=order.checkout_id,
        payment=payment,
        verified_by="integration-maker",
        request_id="verify-first",
        verified_at=datetime.now(UTC),
    )
    conflict = create_test_checkout_verification(
        checkout_id=order.checkout_id,
        payment=payment.model_copy(update={"payment_id": f"pay_{uuid4().hex}"}),
        verified_by="integration-maker",
        request_id="verify-conflict",
        verified_at=datetime.now(UTC),
    )
    try:
        await repository.record_order(order)
        await repository.record_verification(verification)
        with pytest.raises(CheckoutError) as captured:
            await repository.record_verification(conflict)
        assert captured.value.code is CheckoutErrorCode.IDENTITY_CONFLICT
        with pytest.raises(DBAPIError, match="append-only"):
            async with database.transaction() as session:
                await session.execute(
                    text(
                        "UPDATE ledger.test_checkout_orders "
                        "SET amount_subunits = 999 WHERE checkout_id = :checkout_id"
                    ),
                    {"checkout_id": order.checkout_id},
                )
    finally:
        await database.close()
