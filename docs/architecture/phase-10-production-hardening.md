# Phase 10: production hardening and judge proof

## Objective

Turn the complete recovery loop into an inspectable release candidate: least-privilege operator
authority, bounded abuse controls, low-cardinality service metrics, reproducible correctness and
chaos evidence, a real signed-ingress load probe, and production-shaped deployment manifests.

## Operator authority

The bearer token remains a high-entropy secret represented in configuration only by a SHA-256 hash.
Authentication returns a principal plus a frozen scope set. Routes enforce the narrow scope before
calling the application port:

| Scope | Authority |
| --- | --- |
| `incident:read` | Overview, incident detail, diagnosis evidence, action history |
| `action:propose` | Create a server-derived proposal |
| `action:approve` | Append a checker decision |
| `action:execute` | Request policy-eligible execution |
| `metrics:read` | Scrape process metrics |

Production validation requires every configured principal to have an explicit, non-empty set. The
permission check complements, but does not replace, Phase 9 maker-checker enforcement: proposal and
approval identities must still differ in the authoritative database.

## Authentication abuse boundary

Every configured-token request first consumes a client-attempt allowance. A valid credential then
consumes the principal allowance. Local and test processes use a bounded in-memory fixed window.
Production with operator tokens requires the atomic Redis implementation. It hashes limiter keys,
sets expiry in the same server-side script as increment, does not trust `X-Forwarded-For`, returns
`429` with retry metadata at the boundary, and returns `503` if Redis cannot decide.

This is a bounded buildathon control, not a replacement for ingress-level connection limits or a
workforce identity provider.

## Observability contract

`GET /internal/metrics` emits Prometheus text after `metrics:read` authentication. Counters and
latency histograms use only method, registered FastAPI route template, and status. Dynamic URL
values and financial identifiers never become labels. API responses carry request IDs, clickjacking,
MIME-sniffing, referrer, permissions, and—under production configuration—HSTS and deny-all CSP
headers. Exact trusted hosts and CORS origins are configuration gates.

## Deterministic proof pack

`chakravyuh-judge-demo` performs four independent checks in one machine-readable report:

1. It regenerates a held-out labelled fault set from an explicit seed range and reports exact
   precision, recall, F1, false-positive count, false-negative count, and review cost.
2. It verifies duplicate delivery idempotency and out-of-order determinism by state hash.
3. It checks recovery policy against checker-required exact capture and three denial boundaries.
4. It reports p50, p95, maximum latency, and throughput against explicit local SLO inputs.

The SHA-256 proof binds correctness inputs and results, not variable timestamps or performance. The
performance values remain in the signed-shaped report but are not misrepresented as deterministic.

`chakravyuh-load-probe` is a separate, bounded ingress proof. Its secret is accepted only through an
environment variable; the CLI never accepts or prints it. Remote targets require an explicit flag,
identifiers are path-safe, concurrency and counts are capped, redirects and ambient proxy settings
are disabled, and the report succeeds only if every unique delivery returns accepted and every
selected retry returns duplicate.

## Deployment topology

`deploy/kubernetes` defines:

- a predeployment Alembic migration Job;
- three API replicas with live, startup, and PostgreSQL readiness probes;
- two normalization/reduction workers, two Neo4j projectors, and two diagnosis workers;
- two web replicas;
- non-root UID/GID 10001, read-only root filesystems, dropped capabilities, runtime seccomp,
  resource requests/limits, temporary-volume caps, disruption budgets, and default-deny networking.

No Secret is committed. Workloads reference separate PostgreSQL, graph, rate-limit, operator,
provider, and model Secret objects so a database migration never receives a Razorpay, Gemini, or
OpenRouter key.
The placeholder origins make a copied manifest fail closed until an operator supplies
environment-specific secrets, hosts, ingress, TLS, managed databases, Redis, Neo4j, and immutable
image digests.

## Deliberate boundaries

- Razorpay mutations remain Test Mode only and off by default.
- The reliability data is labelled synthetic held-out data, not a claim about unknown live traffic.
- Process metrics are per replica; production scraping and long-term aggregation belong to the
  platform.
- Redis fixed-window limiting is intentionally simple and conservative; edge/WAF controls remain
  defense in depth.
- Static tokens demonstrate scopes but are not workforce SSO, automatic expiry, or revocation.
