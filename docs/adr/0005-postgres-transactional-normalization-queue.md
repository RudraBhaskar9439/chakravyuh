# ADR 0005: use PostgreSQL as the transactional normalization queue

- Status: accepted
- Date: 2026-08-24

## Context

Phase 3 must turn every verified webhook into either one canonical domain event or one visible dead
letter. A process may stop at any instruction, several worker replicas may compete, and provider
deliveries may be duplicated or out of order. The raw webhook ledger is already authoritative in
PostgreSQL.

Publishing a second message to Redis after committing the raw row would create a dual-write gap.
Publishing first would let a worker observe data that PostgreSQL had not committed. Adding an
outbox relay would solve that gap but add another moving part before normalization needs any
external I/O.

## Decision

Insert `operations.webhook_normalization_work` in the same transaction as the immutable raw event.
Workers claim bounded batches with `FOR UPDATE SKIP LOCKED`. Normalization is pure and local; the
claim lock is held only while database writes and deterministic transformation run.

Each batch commits these effects atomically:

1. one immutable normalized event or a stable dead-letter error code;
2. one immutable attempt record;
3. the mutable work row's terminal status.

Unexpected exceptions roll back all three. PostgreSQL uniqueness constraints guarantee at most one
committed normalized output for a raw event and provider identity. This is exactly-once committed
effect, not a claim that distributed execution itself occurs only once.

Redis is not part of this correctness path. It may later carry expendable notifications, but the
worker must be able to recover solely from PostgreSQL.

## Consequences

- Intake cannot commit a raw event without also making it discoverable by a worker.
- Multiple replicas can work without duplicate committed outputs or a lease reaper.
- A stopped worker releases uncommitted row locks when its connection closes.
- Batch size and database statement timeout bound lock duration.
- Permanent contract failures do not hot-loop. They become dead letters with payload-free codes.
- Replay is an explicit operator action and creates an append-only audit record before re-queuing.
- A future normalizer that performs network I/O must split claim and execution with a lease or
  transactional outbox; external calls must never occur while these row locks are held.
