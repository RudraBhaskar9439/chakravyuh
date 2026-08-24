# ADR 0004: Acknowledge webhooks only after durable immutable intake

- Status: accepted
- Date: 2026-08-24

## Context

Razorpay documents at-least-once webhook delivery, duplicate event IDs, retries after non-2xx or
timeout, and possible out-of-order arrival. Parsing before signature verification changes the trust
boundary, while acknowledging before persistence can permanently lose an event.

Primary references:

- [Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/)
- [Webhook Best Practices](https://razorpay.com/docs/webhooks/best-practices/)
- [Payments Webhook Events](https://razorpay.com/docs/webhooks/payments/)

## Decision

Verify HMAC-SHA256 over the exact bounded raw body, validate the configured merchant and account,
and commit an immutable inbox row before returning 2xx. Use merchant, provider, and
`X-Razorpay-Event-Id` as the unique identity. An identical retry returns the original internal event
ID. Reuse of the identity with different bytes is a conflict rather than a duplicate.

The request path performs no graph write, model call, state reduction, or recovery action. Those
operations consume the durable inbox asynchronously in later phases.

## Consequences

- Provider retries are safe and concurrent duplicates collapse atomically.
- A database outage produces non-2xx so Razorpay remains responsible for retrying.
- Out-of-order events are preserved rather than reordered during intake.
- Exact bodies can contain sensitive data and require encrypted storage, restricted access, backup
  controls, and an explicit retention policy before a production launch.
- Secret rotation supports a bounded previous-secret window.
