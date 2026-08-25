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

- [x] Public HTTPS staging webhook is created and registered in Razorpay Test Mode.
- [x] One real ₹10 Test Checkout payment is authorized and remains uncaptured.
- [x] Signature verification and authoritative payment proof are recorded in PostgreSQL.
- [x] Signed provider webhook produces the canonical journey and invariant incident.
- [x] Grounded diagnosis cites the real provider-backed evidence mesh.
- [x] Distinct maker, checker, and executor principals execute exactly one bounded Test Mode capture.
- [x] Provider and local state prove capture idempotency and incident resolution.

## Review outcome

Phase 11 is approved for the isolated Razorpay Test Mode scope. The full redacted provider-backed
record is in [Phase 11B external evidence](phase-11b-external-evidence.md). Live credentials and
real-money mutation remain unsupported by design.

The post-proof OpenRouter resilience extension and its synthetic live verification are recorded in
[Phase 11C provider failover evidence](phase-11c-provider-failover-evidence.md).
