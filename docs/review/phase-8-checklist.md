# Phase 8 review checklist

## Authentication and query safety

- [x] Operator access fails closed when no token hashes are configured.
- [x] Raw operator credentials are never stored in configuration or the database.
- [x] Bearer hashes use constant-time comparison and invalid credentials return a generic response.
- [x] Status filters are enum constrained and pages are limited to 100 rows.
- [x] Opaque cursors validate structure, timestamp timezone, UUID, and total length.
- [x] Every response is marked `Cache-Control: no-store`.

## Truth and audit boundary

- [x] Operator reads use PostgreSQL current state and immutable receipt tables.
- [x] Detail returns the exact evidence subgraph stored at diagnosis time.
- [x] Overview, list, detail, and not-found reads append principal and request audit records.
- [x] Read and audit occur in one transaction.
- [x] The database rejects audit update, delete, and truncate.
- [x] No token, raw webhook body, or diagnosis payload is copied into read-audit details.

## Interface safety

- [x] The credential remains in browser memory and is cleared by end session.
- [x] Requests omit cookies and ambient credentials.
- [x] Incident, diagnosis, exact evidence mesh, hash, and lifecycle are visible together.
- [x] Evidence layout is deterministic and exposes only stored facts and relationships.
- [x] The approval control is disabled and no operator mutation endpoint exists.
- [x] Empty, loading, API-failure, and absent-diagnosis states are handled.
- [x] Responsive styles and semantic labels support desktop and narrow layouts.

## Operational proof

- [x] API tests cover unconfigured, unauthorized, authorized, validation, and not-found paths.
- [x] Real PostgreSQL proof reads an incident receipt and verifies immutable access audits.
- [x] Web test authenticates, loads the evidence mesh, verifies no-cache requests, and ends the session.
- [x] Fresh migration upgrade, downgrade/re-upgrade, metadata drift, and containers are recorded.
- [x] Full local quality gate and private CI are recorded.

## Review outcome

Approved. The implementation commit passed the complete local and private GitHub release gates.
