# Phase 5 review checklist

## Authority and graph shape

- [x] PostgreSQL state and immutable events are the only projection inputs and source of truth.
- [x] Graph inputs reject a mismatched state hash, event count, duplicate identity, or foreign journey.
- [x] Merchant, journey, entity, event, and explicit relationship nodes/edges use deterministic keys.
- [x] Raw webhook bodies, arbitrary payloads, credentials, and secrets are absent from Neo4j writes.
- [x] Unique Neo4j constraints are created idempotently before projection.

## Concurrency and crash safety

- [x] Multiple projectors claim non-overlapping correlations through expiring PostgreSQL leases.
- [x] One complete journey replacement commits in one Neo4j managed transaction.
- [x] PostgreSQL checkpoints only after graph commit and under the exact unexpired lease.
- [x] A crash after graph commit is safe to replay and produces the same projection receipt.
- [x] A state change during projection leaves its newer target pending.
- [x] Epoch-plus-generation ordering rejects an expired stale graph writer.
- [x] Lost leases are isolated per item and cannot abort unrelated batch claims.

## Failure, rebuild, and audit

- [x] Stable payload-free failure codes retry and then dead-letter at a configured bound.
- [x] A rebuild requires bounded operator identity and reason and is not exposed over public HTTP.
- [x] A new audited epoch can supersede a graph ahead of restored PostgreSQL state.
- [x] Rebuild finalization prunes graph-only older-epoch journeys and their orphan nodes.
- [x] Projection attempts, rebuild requests, and completion receipts reject update, delete, and truncate.
- [x] Migration backfills every existing journey and supports downgrade/re-upgrade.

## Observability and process boundary

- [x] A separate process isolates Neo4j degradation from intake and temporal reduction.
- [x] Graph health fails closed for connectivity, lag-query, dead-letter, unfinished-rebuild, and age-threshold failures.
- [x] Health responses expose aggregate lag only and contain no merchant identifiers.
- [x] Worker logs record counts and exception types without exception messages or payloads.
- [x] API, projector, rebuild command, and migration are installed in the non-root backend image.

## Review outcome

Covered by the owner's standing authorization of 2026-08-24. Final local, container, and private CI
evidence is recorded in `phase-5-evidence.md` before Phase 6 begins.
