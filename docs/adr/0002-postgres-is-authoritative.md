# ADR 0002: PostgreSQL is authoritative; Neo4j is a projection

- Status: accepted
- Date: 2026-08-23

## Context

The graph is central to diagnosis and explanation, but graph projections can be delayed, duplicated, or temporarily unavailable. Financial actions require transactional state, durable idempotency, and a complete audit chain.

## Decision

Store raw events, canonical entity state, incidents, proposals, policy decisions, approvals, action attempts, and outcomes in PostgreSQL. Project relationships into Neo4j asynchronously. Never authorize an external action using graph state alone; re-read canonical and provider state first.

## Consequences

- Neo4j can be rebuilt without changing payment truth.
- Graph lag affects diagnosis freshness, not correctness.
- Projection code must be idempotent.
- Some data is intentionally duplicated between stores.

