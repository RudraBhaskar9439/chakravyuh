# Phase 7 review checklist

## Evidence scope and grounding

- [x] PostgreSQL incident and journey revisions select the authoritative diagnosis checkpoint.
- [x] Neo4j traversal is read-only, single-journey, fact-bounded, and relationship-bounded.
- [x] Merchant, correlation, state generation, and state hash must all match.
- [x] Duplicate facts, open edges, silent truncation, and missing invariant events fail closed.
- [x] Only allowlisted fields reach the subgraph; raw payloads and credentials are absent.
- [x] Canonical prompt and subgraph SHA-256 hashes are recorded.

## Model safety

- [x] Gemini uses the stable v1 Interactions API and strict JSON Schema output.
- [x] Provider storage and streaming are disabled and no tools are declared.
- [x] Identifiers and statuses are explicitly treated as untrusted data.
- [x] Every diagnosis cites existing evidence and at least one invariant fact.
- [x] Root causes and actions are independently allowlisted by incident type.
- [x] Low-confidence, invalid-citation, unsupported-cause, and unsupported-action proposals abstain.
- [x] Model output remains non-executable and cannot modify incident truth.

## Durability and isolation

- [x] Incident revisions transactionally advance a versioned diagnosis work row.
- [x] Claims use database-time leases, skip-locked row claiming, and expired-lease recovery.
- [x] New targets survive an older in-flight model call.
- [x] Resolution revokes in-flight work; reopening creates a new pending target.
- [x] Completion validates incident and source revision against the receipt.
- [x] Transient failures retry; permanent or exhausted failures dead-letter with stable codes.
- [x] Receipts and attempts are append-only and commit atomically with the queue checkpoint.
- [x] Diagnosis runs in a separate process from intake, reduction, projection, and detection.

## Operational proof

- [x] Real PostgreSQL and Neo4j test covers incident-to-receipt processing.
- [x] Real service test proves append-only guards, immediate permanent dead letter, and lease fencing.
- [x] Fake-provider tests cover complete, incomplete, malformed, unavailable, and timed-out responses.
- [x] A live configured Gemini call completed with grounded citations and a guard-approved result.
- [x] Migration upgrades to head and matches SQLAlchemy metadata.
- [x] Full local quality gate and production-container checks are recorded in Phase 7 evidence.
- [ ] Private CI is recorded in Phase 7 evidence.

## Review outcome

Covered by the owner's standing authorization of 2026-08-24. Phase 7 is approved only after the
remaining release gate is checked and recorded in `phase-7-evidence.md`.
