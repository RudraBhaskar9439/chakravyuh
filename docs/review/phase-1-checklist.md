# Phase 1 review checklist

## Architecture

- [ ] Domain code has no infrastructure imports.
- [ ] PostgreSQL is explicitly the source of financial truth.
- [ ] Neo4j is explicitly rebuildable.
- [ ] AI cannot execute actions or approve itself.
- [ ] API and worker share versioned domain contracts.

## Security

- [ ] Repository visibility is private and public forks/pages are disabled.
- [ ] No real secrets are present.
- [ ] Wildcard CORS is rejected.
- [ ] Production API documentation is disabled.
- [ ] Security headers are set.
- [ ] Containers use non-root users.

## Correctness

- [ ] Money uses integer subunits and explicit currency.
- [ ] Events require timezone-aware timestamps.
- [ ] Impossible observation ordering is rejected.
- [ ] Incident, proposal, and decision IDs form an audit chain.
- [ ] Contracts reject unknown fields and are immutable.

## Operations

- [ ] API exposes liveness and readiness separately.
- [ ] Logs are structured in non-local environments.
- [ ] Local infrastructure has health checks and persistent volumes.
- [ ] CI runs lint, formatting, strict typing, tests, builds, and container builds.

## Review outcome

Record one of:

- Approved
- Approved with follow-up
- Changes requested

Phase 2 must not begin until this review is complete.
