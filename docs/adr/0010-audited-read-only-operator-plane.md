# ADR 0010: Keep the first operator control plane authenticated, audited, and read-only

- Status: Accepted
- Date: 2026-08-24

## Context

An operator must be able to inspect the incident, the deterministic rule finding, the exact evidence
shown to the model, the guarded result, and its immutable history in one place. Serving that view
directly from Neo4j would make a rebuildable projection appear authoritative. Adding action buttons
before policy and approval enforcement would also create an unsafe implied capability.

The operator surface contains financial state and provider identifiers. Anonymous access, browser
credential persistence, cacheable responses, unbounded list queries, and unaudited reads are not
acceptable boundaries even in Test Mode.

## Decision

Phase 8 exposes three internal, read-only endpoints backed exclusively by PostgreSQL current state
and immutable receipt tables: overview, cursor-paginated incident list, and incident detail. Detail
returns the exact stored evidence subgraph from the latest immutable diagnosis receipt; it never
performs a fresh Neo4j traversal.

The API authenticates a bearer token by hashing it with SHA-256 and comparing it in constant time
against configured hashes mapped to stable principal IDs. Raw tokens are never configured. An empty
credential map fails closed with `503`; missing or invalid credentials receive one generic `401`.
Every authorized read appends the principal, request ID, bounded action metadata, resource, and
outcome in the same database transaction as the read. PostgreSQL rejects update, delete, and
truncate on that audit table.

Lists use a bounded limit of 100 and an opaque cursor over the stable descending
`(last_detected_at, incident_id)` order. Filters accept only incident-status enum values. Responses
set `Cache-Control: no-store`.

The browser keeps the raw token only in React memory, sends requests without ambient credentials,
and provides an explicit end-session control. It renders a deterministic evidence layout from the
stored receipt. The approval control is visibly disabled and has no backing mutation endpoint.

## Consequences

- PostgreSQL remains the source of operator-visible financial truth.
- Every successful or not-found authorized lookup has an immutable audit record.
- A graph rebuild cannot silently change evidence already used for a diagnosis.
- Token compromise is still bearer-credential compromise, so production transport must use TLS and
  tokens must be issued through a secret manager with rotation and expiry handled operationally.
- Phase 8 can explain an action but cannot request, approve, enqueue, or execute one.
- Role-based scopes, short-lived identity-provider sessions, proposal policy, and dual control remain
  later release requirements.
