# Phase 1 review checklist

## Architecture

- [x] Domain code has no infrastructure imports.
- [x] PostgreSQL is explicitly the source of financial truth.
- [x] Neo4j is explicitly rebuildable.
- [x] AI cannot execute actions or approve itself.
- [x] API and worker share versioned domain contracts.

## Security

- [x] Repository visibility is private and public Pages are disabled.
- [x] No real secrets are present.
- [x] Wildcard CORS is rejected.
- [x] Production API documentation is disabled.
- [x] Security headers are set.
- [x] Containers use non-root users.

## Correctness

- [x] Money uses integer subunits and explicit currency.
- [x] Events require timezone-aware timestamps.
- [x] Impossible observation ordering is rejected.
- [x] Incident, proposal, and decision IDs form an audit chain.
- [x] Contracts reject unknown fields and are immutable.

## Operations

- [x] API exposes liveness and readiness separately.
- [x] Logs are structured in non-local environments.
- [x] Local infrastructure has health checks and persistent volumes.
- [x] CI runs lint, formatting, strict typing, tests, builds, and container builds.

## Review outcome

Approved by the owner on 2026-08-24 through the instruction to continue to forward phases.
