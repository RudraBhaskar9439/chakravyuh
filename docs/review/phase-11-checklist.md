# Phase 11 review checklist

## Test Checkout implementation

- [x] Order amount, currency, receipt, and manual-capture mode are server-controlled.
- [x] The browser receives the public Test key but never the key secret.
- [x] Checkout result HMAC is verified with constant-time comparison.
- [x] Razorpay payment state is fetched and checked for exact order, amount, status, and capture flag.
- [x] Order and verification evidence is content-hashed and append-only.
- [x] Dedicated operator scope, rate limiting, no-store responses, TTL, and kill switch are enforced.
- [x] Production configuration rejects the Test Checkout capability.
- [x] Unit, API, adapter, configuration, web, migration, and PostgreSQL integration tests pass.

## External Razorpay evidence

- [ ] Public HTTPS staging webhook is created and registered in Razorpay Test Mode.
- [ ] One real ₹10 Test Checkout payment is authorized and remains uncaptured.
- [ ] Signature verification and authoritative payment proof are recorded in PostgreSQL.
- [ ] Signed provider webhook produces the canonical journey and invariant incident.
- [ ] Grounded diagnosis cites the real provider-backed evidence mesh.
- [ ] Distinct maker and checker execute exactly one bounded Test Mode capture.
- [ ] Provider and local state prove capture idempotency and incident resolution.

## Review outcome

Implementation is in review. Phase 11 is not approved until the unchecked external gates have real,
redacted evidence. This distinction prevents mocked contracts from being presented as a live
provider proof.
