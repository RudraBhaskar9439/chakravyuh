# Phase 3: durable normalization

## Objective

Turn each immutable, signature-verified Razorpay webhook into a deterministic domain event or a
visible dead letter, with safe concurrency, crash recovery, and audited manual replay.

## Commit path

    verified webhook transaction
      ├── ledger.webhook_events (immutable exact input)
      └── operations.webhook_normalization_work (pending)

    worker transaction
      ├── SELECT pending ... FOR UPDATE SKIP LOCKED
      ├── pure Razorpay normalizer
      ├── ledger.normalized_events OR stable error code
      ├── ledger.normalization_attempts (immutable)
      └── work status = completed OR dead_letter

There is no acknowledgement message to lose. A transaction either commits every effect or rolls
all of them back. A crash releases its row locks and leaves the work pending.

## Deterministic provider contract

The event type prefix selects the primary subject:

| Razorpay event family | Domain subject |
| --- | --- |
| `payment.*` | `payment` |
| `order.*` | `razorpay_order` |
| `refund.*` | `refund` |
| `payment_link.*` | `payment_link` |

The normalizer reads `payload.<family>.entity`, requires a bounded non-empty provider ID, and stores
that point-in-time entity snapshot. It prefers explicit order, payment, invoice, and reference IDs
for correlation, then a related order snapshot, then the subject ID. Its output UUID is derived from
the immutable raw event UUID, so the same input and normalizer always produce the same identity.

Razorpay documents webhook payloads as snapshots and documents multi-entity shapes for the four
families above:

- [Payment webhooks](https://razorpay.com/docs/webhooks/payments/)
- [Order webhooks](https://razorpay.com/docs/webhooks/orders/)
- [Refund webhooks](https://razorpay.com/docs/webhooks/refunds/)
- [Payment Link webhooks](https://razorpay.com/docs/webhooks/payment-links/)

Unknown additive entity fields are preserved. The original multi-entity envelope and exact signed
bytes remain in the raw ledger, so a later normalizer can replay from evidence rather than from a
lossy projection.

## Dead-letter policy

Only expected permanent contract failures become dead letters:

- unsupported source or event family;
- missing primary entity or provider entity ID;
- provider event time later than local observation time.

The database stores a stable error code, not the payload or an exception string. Unexpected code or
database failures roll back to pending and receive bounded worker backoff. Batch logs contain counts,
normalizer version, worker version, and exception class only; they do not contain webhook data.

## Replay boundary

Replay is deliberately not exposed as an unauthenticated HTTP endpoint. An operator with database
and host authorization runs:

    chakravyuh-replay RAW_EVENT_UUID \
      --requested-by operator@example.com \
      --reason "Normalizer support deployed and change reviewed"

Only a dead-lettered item can be re-queued. The operator identity, reason, raw event identity, replay
identity, and database timestamp are append-only. Prior failed attempts remain unchanged and the
next attempt number increases.

## Operational boundaries

- Run any number of worker replicas; `SKIP LOCKED` partitions available work.
- Apply migrations before starting API or workers.
- Alert on `dead_lettered > 0`, repeated `normalization_batch_failed`, growing pending age, and worker
  absence.
- Encrypt raw and normalized payload storage and backups, restrict database roles, and set a reviewed
  retention policy before using live data.
- This phase creates no Neo4j write, model call, outbound Razorpay call, or financial action.
