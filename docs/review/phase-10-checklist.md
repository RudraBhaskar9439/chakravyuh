# Phase 10 review checklist

## Security and observability

- [x] Every operator route enforces a named least-privilege scope before application work.
- [x] Production rejects implicit scopes and requires a cluster-wide Redis limiter.
- [x] Limiter failures deny authentication; client identity does not trust forwarded headers.
- [x] Trusted hosts, exact CORS, production HSTS/CSP, no-store, and existing response protections are tested.
- [x] Metrics use route templates only and require the independent `metrics:read` scope.
- [x] Threat model documents protected assets, boundaries, controls, and explicit non-claims.

## Reliability and proof

- [x] One command emits held-out correctness, chaos, recovery-policy, latency, and throughput evidence.
- [x] Proof digest is deterministic and excludes wall-clock/timing variability.
- [x] Signed-ingress probe bounds target, identifiers, count, concurrency, timeout, redirect, and secret handling.
- [x] Isolated PostgreSQL ingress load and duplicate proof passes with recorded measurements.
- [x] Full local quality gate and real PostgreSQL/Neo4j integration suite pass.

## Deployment and supply chain

- [x] Versioned migration Job precedes API and processors.
- [x] Workloads are non-root, read-only, capability-dropped, seccomp-confined, and resource-bounded.
- [x] API/web have replicas, zero-unavailable rollout shape, probes, and disruption budgets.
- [x] Network policy defaults deny and allowlists DNS, ingress, and runtime dependency ports.
- [x] No Secret is committed; environment setup and immutable-digest requirements are documented.
- [x] Dependabot covers Python, npm, Actions, and both container build roots.
- [x] Backend/web images build, run non-root, and expose Phase 10 commands.
- [x] Private GitHub CI and dependency audit pass on the exact implementation commit.

## Review outcome

Approved. The local quality, real-service, isolated-load, Redis, migration, container, secret,
responsive-browser, private-CI, and dependency gates passed under the owner's standing authorization
of 2026-08-24.
