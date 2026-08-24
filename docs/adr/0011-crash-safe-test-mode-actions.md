# ADR 0011: checkpoint before mutation and reconcile ambiguity without retry

- Status: accepted
- Date: 2026-08-24

## Context

Razorpay exposes `GET /v1/payments/:id` and `POST /v1/payments/:id/capture`. Capture is valid only
for an authorized payment and requires the exact order amount in currency subunits. Razorpay's
documented idempotency header applies to payout and composite APIs, not the Payments capture API.
A timeout after a capture POST can therefore leave the caller unable to distinguish a committed
capture from an uncommitted request.

## Decision

Phase 9 supports only authoritative payment fetch and payment capture, only with an explicitly
enabled `rzp_test_` credential. Capture requires deterministic policy plus an immutable approval
from a principal distinct from the maker.

The executor performs an authoritative GET before any mutation. It verifies the exact payment ID,
amount, currency, and authorized state, then durably appends a mutation authorization and sets
`mutation_attempted=true` before sending capture. Any expired lease, process crash, network error,
or timeout after that checkpoint can only issue another GET. It may record success when exact
captured state is observed; it must otherwise record an uncertain terminal outcome. It never sends
a second capture POST for that proposal.

## Consequences

- Crash ambiguity cannot become a duplicate capture attempt.
- A transient preflight failure remains retryable because no mutation checkpoint exists.
- An uncertain result requires human/provider investigation rather than optimistic automation.
- Live credentials, unsupported actions, stale diagnoses, changed state, amounts above the cap,
  non-INR capture, and low-confidence diagnoses fail closed.
- The narrow adapter trades breadth for an evidence-backed safety case judges can inspect.
