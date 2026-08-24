"""Stable domain vocabularies shared across adapters."""

from enum import StrEnum


class EntityType(StrEnum):
    MERCHANT = "merchant"
    CUSTOMER = "customer"
    MERCHANT_ORDER = "merchant_order"
    RAZORPAY_ORDER = "razorpay_order"
    PAYMENT = "payment"
    PAYMENT_LINK = "payment_link"
    REFUND = "refund"
    WEBHOOK_EVENT = "webhook_event"
    RECOVERY_CASE = "recovery_case"
    RECOVERY_ACTION = "recovery_action"


class EventSource(StrEnum):
    MERCHANT = "merchant"
    RAZORPAY_API = "razorpay_api"
    RAZORPAY_WEBHOOK = "razorpay_webhook"
    CHAKRAVYUH = "chakravyuh"
    SIMULATOR = "simulator"


class NormalizationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class NormalizationOutcome(StrEnum):
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"


class MerchantOrderStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class IncidentType(StrEnum):
    CAPTURED_BUT_ORDER_UNPAID = "captured_but_order_unpaid"
    AUTHORIZED_NOT_CAPTURED = "authorized_not_captured"
    FAILED_WITHOUT_RECOVERY = "failed_without_recovery"
    STALE_RECOVERY_AFTER_SUCCESS = "stale_recovery_after_success"
    DUPLICATE_ACTIVE_RECOVERY_LINKS = "duplicate_active_recovery_links"
    EVENT_ORDER_CORRUPTION = "event_order_corruption"


class IncidentStatus(StrEnum):
    DETECTED = "detected"
    INVESTIGATING = "investigating"
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


class ActionType(StrEnum):
    FETCH_AUTHORITATIVE_STATE = "fetch_authoritative_state"
    REPLAY_MERCHANT_EVENT = "replay_merchant_event"
    CAPTURE_PAYMENT = "capture_payment"
    CREATE_PAYMENT_LINK = "create_payment_link"
    CANCEL_PAYMENT_LINK = "cancel_payment_link"
    ABSTAIN = "abstain"


class ActionRisk(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    MONEY_MOVEMENT = "money_movement"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
