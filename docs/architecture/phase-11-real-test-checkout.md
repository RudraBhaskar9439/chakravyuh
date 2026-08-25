# Phase 11: real Razorpay Test Checkout proof

## Objective

Create the real provider-backed `authorized` and uncaptured Test Mode payment needed by the
Chakravyuh demo without placing a secret or general money-operation primitive in the browser.

## Flow

    scoped operator
      -> POST /v1/demo/checkout/orders
      -> server generates UUID and receipt
      -> fixed ₹10 INR Razorpay order with capture=manual
      -> immutable local order hash
      -> official Razorpay Checkout with public Test key
      -> signed Checkout success tuple
      -> POST /v1/demo/checkout/verifications
      -> constant-time HMAC verification
      -> authoritative Razorpay payment fetch
      -> exact order + amount + authorized + uncaptured checks
      -> immutable verification hash

Order creation and verification both require `test-checkout:operate`, the operator rate limit, and
the normal no-store response boundary. The raw operator token stays in browser memory. The provider
key secret stays inside the backend adapter.

## Bounded provider contract

The order amount and INR currency are configuration-owned; callers submit no order body. The default
is ₹10, the allowed configuration range is ₹1 through ₹1,000, and the order expires locally after 30
minutes. A random receipt is generated server-side. The provider response must identify a newly
created order and agree exactly on amount, currency, and receipt.

Checkout verification uses `HMAC-SHA256(key_secret, order_id + "|" + payment_id)` and constant-time
comparison. It then fetches the payment and rejects unknown or expired orders, amount or order
mismatches, captured payments, and any state other than `authorized`.

## Immutable evidence

`ledger.test_checkout_orders` stores the allowlisted provider order, principal, request, expiry, and
canonical SHA-256. `ledger.test_checkout_verifications` stores only the allowlisted authoritative
payment fields, principal, request, and canonical SHA-256. Update, delete, and truncate are rejected
by database triggers. The Checkout signature and raw provider response are never stored.

## Fail-closed boundary

- Disabled by default and rejected in production even if configured true.
- Requires a key whose identifier begins `rzp_test_`, its secret, a merchant identity, and a scoped
  operator token.
- Creates Test Mode orders only; it does not capture, refund, or invoke the recovery engine.
- Does not treat the browser callback as authoritative without the HMAC and payment fetch.
- Does not claim webhook delivery, incident detection, diagnosis, or recovery until the external
  end-to-end proof is run.

## External proof sequence

1. Expose the existing signed webhook endpoint through a reviewed public HTTPS staging route.
2. Register that exact endpoint and a fresh secret in the Razorpay Test Mode Dashboard.
3. Enable Test Checkout in the isolated environment and authorize one ₹10 test payment.
4. Confirm the immutable Checkout verification and signed webhook intake.
5. Wait through the invariant grace period, then show the incident and grounded diagnosis.
6. Use distinct maker and checker identities for the exact capture proposal and execution.
7. Confirm the provider payment is captured once and the webhook-driven journey resolves.

The checklist keeps steps 1–7 open until their artifacts exist; mocked provider tests are not
substituted for this external evidence.
