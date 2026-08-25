"""Append-only PostgreSQL ledger for bounded Test Checkout proof."""

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping

from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import TestCheckoutError, TestCheckoutErrorCode
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    ProviderManualCaptureOrder,
    TestCheckoutOrder,
    TestCheckoutVerification,
)
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    test_checkout_orders,
    test_checkout_verifications,
)


class PostgresTestCheckoutRepository:
    """Persist order and verification records once without retaining Checkout signatures."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def record_order(self, order: TestCheckoutOrder) -> TestCheckoutOrder:
        statement = (
            insert(test_checkout_orders)
            .values(
                checkout_id=order.checkout_id,
                merchant_id=order.merchant_id,
                order_id=order.provider_order.order_id,
                amount_subunits=order.provider_order.amount.amount_subunits,
                currency=order.provider_order.amount.currency,
                receipt=order.provider_order.receipt,
                provider_created_at=order.provider_order.provider_created_at,
                created_by=order.created_by,
                request_id=order.request_id,
                created_at=order.created_at,
                expires_at=order.expires_at,
                order_hash=order.order_hash,
            )
            .on_conflict_do_nothing()
            .returning(test_checkout_orders)
        )
        async with self._database.transaction() as session:
            row = (await session.execute(statement)).mappings().one_or_none()
            if row is None:
                row = (
                    (
                        await session.execute(
                            select(test_checkout_orders).where(
                                or_(
                                    test_checkout_orders.c.order_id
                                    == order.provider_order.order_id,
                                    test_checkout_orders.c.receipt == order.provider_order.receipt,
                                )
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if row is None:
            raise TestCheckoutError(TestCheckoutErrorCode.IDENTITY_CONFLICT)
        existing = _order(row)
        if existing.order_hash != order.order_hash:
            raise TestCheckoutError(TestCheckoutErrorCode.IDENTITY_CONFLICT)
        return existing

    async def get_order(self, order_id: str) -> TestCheckoutOrder | None:
        async with self._database.session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(test_checkout_orders).where(
                            test_checkout_orders.c.order_id == order_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _order(row)

    async def record_verification(
        self,
        verification: TestCheckoutVerification,
    ) -> TestCheckoutVerification:
        payment = verification.payment
        statement = (
            insert(test_checkout_verifications)
            .values(
                verification_id=verification.verification_id,
                checkout_id=verification.checkout_id,
                payment_id=payment.payment_id,
                order_id=payment.order_id,
                status=payment.status.value,
                amount_subunits=payment.amount.amount_subunits,
                currency=payment.amount.currency,
                captured=payment.captured,
                verified_by=verification.verified_by,
                request_id=verification.request_id,
                verified_at=verification.verified_at,
                verification_hash=verification.verification_hash,
            )
            .on_conflict_do_nothing()
            .returning(test_checkout_verifications)
        )
        async with self._database.transaction() as session:
            row = (await session.execute(statement)).mappings().one_or_none()
            if row is None:
                row = (
                    (
                        await session.execute(
                            select(test_checkout_verifications).where(
                                or_(
                                    test_checkout_verifications.c.checkout_id
                                    == verification.checkout_id,
                                    test_checkout_verifications.c.payment_id == payment.payment_id,
                                )
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if row is None:
            raise TestCheckoutError(TestCheckoutErrorCode.IDENTITY_CONFLICT)
        existing = _verification(row)
        if (
            existing.checkout_id != verification.checkout_id
            or existing.payment != verification.payment
        ):
            raise TestCheckoutError(TestCheckoutErrorCode.IDENTITY_CONFLICT)
        return existing


def _order(row: RowMapping) -> TestCheckoutOrder:
    return TestCheckoutOrder(
        checkout_id=row["checkout_id"],
        merchant_id=row["merchant_id"],
        provider_order=ProviderManualCaptureOrder(
            order_id=row["order_id"],
            amount=Money(
                amount_subunits=row["amount_subunits"],
                currency=row["currency"],
            ),
            receipt=row["receipt"],
            provider_created_at=row["provider_created_at"],
        ),
        created_by=row["created_by"],
        request_id=row["request_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        order_hash=row["order_hash"],
    )


def _verification(row: RowMapping) -> TestCheckoutVerification:
    return TestCheckoutVerification(
        verification_id=row["verification_id"],
        checkout_id=row["checkout_id"],
        payment=ProviderPaymentState(
            payment_id=row["payment_id"],
            status=PaymentStatus(row["status"]),
            amount=Money(
                amount_subunits=row["amount_subunits"],
                currency=row["currency"],
            ),
            captured=row["captured"],
            order_id=row["order_id"],
        ),
        verified_by=row["verified_by"],
        request_id=row["request_id"],
        verified_at=row["verified_at"],
        verification_hash=row["verification_hash"],
    )
