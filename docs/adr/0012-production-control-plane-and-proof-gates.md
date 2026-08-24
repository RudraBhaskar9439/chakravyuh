# ADR 0012: production controls and claims require executable proof

- Status: accepted
- Date: 2026-08-24

## Context

A safe payment action is not sufficient for an operable service. Static bearer identities can be
overprivileged, login attempts can become an abuse path, request telemetry can leak unbounded
merchant identifiers, and deployment templates can silently run as root or skip migrations. A demo
can also hide correctness failures behind one successful journey.

## Decision

Operator principals receive explicit scopes for incident reads, proposals, approvals, execution,
and metric reads. Production refuses an operator token without an explicit non-empty scope set and
requires a Redis-backed fixed-window limiter. Redis failure denies authentication; client identity
comes from the transport peer and never from an untrusted forwarded header.

Process metrics use registered route templates, HTTP methods, and status codes only. Merchant,
incident, payment, event, request, token, and account identifiers are forbidden as metric labels.
The Prometheus endpoint requires its own scope.

Release claims come from executable gates:

- a deterministic held-out fault set reports precision, recall, false positives, and false negatives;
- duplicate and out-of-order deliveries must reduce to identical state hashes;
- recovery policy must require checker approval and deny oversize, weak, or kill-switched captures;
- a bounded signed-webhook probe verifies new-event and duplicate acknowledgements against a named
  target; and
- tests inspect deployment manifests for explicit migration, non-root execution, read-only filesystems,
  probes, resources, disruption budgets, and default-deny networking.

## Consequences

- A stolen read token cannot propose, approve, execute, or scrape metrics unless separately scoped.
- A Redis outage stops operator authentication instead of silently disabling the production limit.
- High-cardinality business identifiers cannot exhaust the process metric label space.
- The proof digest is stable for the same evaluator, cases, and policy assertions, while wall-clock
  performance remains visible and honestly machine-dependent.
- Static tokens remain a buildathon identity mechanism. Workforce OIDC, external secrets, ingress,
  certificate management, managed data services, and pager ownership are deployment integrations,
  not claims made by this repository.
