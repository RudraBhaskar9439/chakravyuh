# ADR 0013: Isolate Test Checkout from recovery authority

- Status: accepted
- Date: 2026-08-25

## Context

The recovery engine needs one real Razorpay Test Mode payment in the `authorized` and uncaptured
state. Asking a judge to manufacture that state manually in the Dashboard is fragile, while giving
the browser a key secret or general order-creation API would violate the project's authority model.

## Decision

Add a separately disabled Test Checkout capability that creates only a server-fixed INR order with
per-order manual capture. It has an independent `test-checkout:operate` scope and cannot be enabled
when the application environment is production.

The browser receives only the public Test key and bounded order fields. A Checkout result becomes
proof only after the server verifies its HMAC signature and fetches Razorpay's authoritative payment
state. Order and verification facts are append-only and content-hashed. Checkout signatures, key
secrets, and raw provider responses are not persisted.

This capability creates an authorization; it never captures, refunds, or changes a payment. The
existing maker-checker recovery control plane remains the only capture path.

## Consequences

- A realistic incident can be created repeatably without widening recovery authority.
- The Test key secret remains server-side and the public key remains intentionally browser-visible.
- A provider order may exist without a local ledger record if the process fails after provider
  creation but before the database commit. Such an expired Test Mode order is harmless and is never
  reused; reconciliation is intentionally limited to the isolated demonstration capability.
- Webhook delivery still requires a separately configured public HTTPS endpoint. Checkout success
  alone is not claimed as an end-to-end incident and recovery proof.
