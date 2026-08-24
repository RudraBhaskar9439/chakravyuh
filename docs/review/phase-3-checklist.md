# Phase 3 review checklist

## Durable discovery

- [x] Raw intake and pending normalization work commit in one transaction.
- [x] Migration backfills raw events recorded before Phase 3.
- [x] PostgreSQL, not Redis, owns pending, completed, and dead-letter status.
- [x] Multiple workers claim bounded, non-overlapping batches with `SKIP LOCKED`.

## Normalization correctness

- [x] Payment, order, refund, and payment-link subjects follow the documented envelope shape.
- [x] Output identity and correlation are deterministic.
- [x] Unknown additive entity fields are retained.
- [x] Unsupported or malformed events abstain with stable, payload-free error codes.
- [x] One raw event can commit at most one normalized output.

## Failure and replay

- [x] Unexpected exceptions roll the batch back to pending with no partial output or attempt.
- [x] Permanent failures create a dead letter and immutable attempt in the same transaction.
- [x] Only dead letters can be manually re-queued.
- [x] Replays require bounded operator identity and reason and retain an immutable audit row.
- [x] Worker handles SIGINT/SIGTERM, idle polling, safe failure logging, and bounded backoff.

## Persistence and quality

- [x] Empty upgrade, downgrade, re-upgrade, and metadata-drift checks pass.
- [x] PostgreSQL rejects UPDATE, DELETE, and TRUNCATE against Phase 3 audit ledgers.
- [x] Strict lint, formatting, typing, backend, web, build, and container checks pass.
- [ ] Private-repository CI passes for the final Phase 3 commit.

## Review outcome

Awaiting owner review. Record Approved, Approved with follow-up, or Changes requested.

Phase 4 must not begin until this review is complete.
