# ADR 0006: Rebuild each dirty correlation from immutable history

- Status: Accepted
- Date: 2026-08-24

## Context

Provider webhooks may be duplicated, delayed, or delivered out of order. Updating a mutable payment
row as each webhook arrives would make arrival timing part of financial truth. Transition precedence
would also risk hiding a real regression that the later invariant engine must be able to observe.

## Decision

PostgreSQL owns one generation-counted work row per merchant and correlation. Inserting a normalized
event increments that generation in the same database transaction through a trigger. A worker locks
the correlation, reads its complete normalized history, removes identical event retries, orders the
set by `(occurred_at, observed_at, event_type, source_event_id, event_id)`, and runs a pure versioned
reducer.

The transaction replaces one current state, appends one immutable state revision and attempt, and
advances the applied generation together. A concurrent event insert waits on the same work-row lock,
then increments the generation after the reduction commits, ensuring it cannot be silently missed.

Provider statuses are retained rather than forced through a guessed transition graph. The reducer
derives only bounded facts supported by explicit fields, including payment-to-order and
refund-to-payment edges. Phase 6 will evaluate contradictions as invariants instead of the reducer
discarding them.

## Consequences

- The same event set always produces the same state hash regardless of delivery order.
- Late events cause a complete, reviewable revision instead of an in-place guess.
- PostgreSQL remains authoritative; Phase 5 can rebuild Neo4j from current state and immutable events.
- Reduction cost grows with events per correlation. A configurable hard limit prevents unbounded
  memory use; an oversized journey dead-letters with a stable code and requires audited replay after
  a reviewed limit or implementation change.
- Replaying a completed journey creates a new generation and revision without mutating prior evidence.
