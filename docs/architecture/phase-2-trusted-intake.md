# Phase 2: trusted webhook intake

## Objective

Convert an unauthenticated public HTTP request into a durable, signature-verified fact without
performing any financial or AI action.

## Request path

    bounded ASGI byte stream
              ↓
    merchant configuration gate
              ↓
    HMAC-SHA256 over exact bytes
              ↓
    tolerant provider-envelope validation
              ↓
    PostgreSQL INSERT ... ON CONFLICT
              ↓
    202 new / 200 identical retry

The endpoint does not return success until the transaction commits. It never logs the payload or
signature.

## Identity and conflict semantics

The database uniqueness key is `(merchant_id, source, source_event_id)`. This keeps tenants
isolated and uses Razorpay's documented event ID for provider idempotency.

- No existing identity: insert the event and return accepted.
- Existing identity with the same SHA-256 body digest: return the original event ID.
- Existing identity with a different digest: raise an identity conflict and return 409.

The insert and conflict inspection run in one PostgreSQL transaction. Concurrent requests race on
the unique index, so exactly one can insert.

## Immutability

The `ledger.webhook_events` table stores the exact body, parsed JSON, integrity digest, merchant and
account scope, provider identity, event type, provider time, and observation time. PostgreSQL
also records its own insertion timestamp. Triggers reject UPDATE, DELETE, and TRUNCATE even if
application code attempts them.

Schema creation is never performed by API startup. Alembic owns schema changes, and CI checks the
reviewed migration against SQLAlchemy metadata for drift.

## Availability behavior

Liveness proves only that HTTP can execute. Readiness performs a bounded PostgreSQL round trip and
returns 503 when the authoritative ledger is unavailable. Redis and Neo4j are intentionally absent
from readiness because intake correctness does not depend on them.

## Security boundaries

- The request body is streamed with both declared and observed size limits.
- HMAC comparison is constant-time and supports current plus previous rotation secrets.
- Additive provider JSON fields are tolerated and retained.
- Merchant path identity and optional Razorpay account identity must match configuration.
- Missing configuration fails closed.
- Only Test Mode events are permitted during the buildathon.

Before a real production launch, deployment infrastructure must add TLS termination, provider IP
allowlisting as defence in depth, encrypted database volumes and backups, database role separation,
alerting, and an approved payload-retention schedule.
