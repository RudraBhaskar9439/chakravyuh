# Phase 4 review checklist

## Temporal correctness

- [x] Caller delivery order cannot change the reduced state or its canonical hash.
- [x] Identical duplicate event identities are idempotent; conflicting identity reuse is rejected.
- [x] Late events rebuild the full immutable history rather than applying last-arrival-wins.
- [x] Unknown provider statuses are retained without guessed transitions.
- [x] Amounts remain integer currency subunits and explicit relationship IDs become graph-ready edges.

## Durability and concurrency

- [x] Normalized inserts transactionally dirty their merchant correlation.
- [x] Multiple workers claim non-overlapping correlations with `SKIP LOCKED`.
- [x] Current state, immutable revision, attempt, and queue generation commit atomically.
- [x] Concurrent inserts cannot be lost behind a completed generation.
- [x] Unexpected failures leave pending work with no partial state or attempt.

## Failure and replay

- [x] Oversized correlations dead-letter with a stable payload-free error code.
- [x] Completed and dead-lettered correlations can be rebuilt only with bounded operator audit context.
- [x] Revisions, attempts, and replay requests reject update, delete, and truncate.
- [x] Current derived state remains explicitly rebuildable.

## Synthetic generator

- [x] Seeds reproduce stable identities and complete outputs.
- [x] Success, incomplete, recovered, refund, out-of-order, and duplicate scenarios are covered.
- [x] The simulator is offline and has no persistence, provider, or money-action capability.

## Review outcome

Covered by the owner's standing authorization of 2026-08-24. Final verification evidence and the
private CI run are recorded in `phase-4-evidence.md` before Phase 5 begins.
