# Production deployment runbook

The checked-in manifests are a secure release template, not a one-command claim of a live service.
Complete every environment-specific gate before applying them.

## 1. Build immutable images

Build the API image from the repository root. Build the web image with the public TLS API origin:

    docker build -t REGISTRY/chakravyuh-api:0.10.0 .
    docker build -f apps/web/Dockerfile \
      --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com \
      -t REGISTRY/chakravyuh-web:0.10.0 .

Scan both images, push them to a private registry, and replace the Kustomize image values with the
registry-provided immutable digests. Do not deploy a mutable tag.

## 2. Configure the environment

Replace the placeholder CORS origin, trusted API host, and Neo4j address in the ConfigMap. Confirm
that the ingress namespace carries the label expected by the NetworkPolicy. Provide TLS termination,
an exact host, request-size limits, connection limits, and no public route to internal metrics unless
the bearer boundary is intentionally retained.

Create the referenced Secret objects through the platform's external-secret integration:

- `chakravyuh-postgres-secrets`: `CHAKRAVYUH_POSTGRES_DSN`;
- `chakravyuh-graph-secrets`: `CHAKRAVYUH_NEO4J_PASSWORD`;
- `chakravyuh-rate-limit-secrets`: `CHAKRAVYUH_REDIS_DSN`;
- `chakravyuh-operator-secrets`: explicit operator token hashes and principal scopes;
- `chakravyuh-provider-secrets`: Razorpay webhook and dormant Test Mode action credentials; and
- `chakravyuh-model-secrets`: the Gemini API key.

This separation ensures each process receives only its required secret classes. Never put raw
tokens or Secret YAML in Git, shell history, screenshots, tickets, or logs.

Keep `CHAKRAVYUH_RAZORPAY_ACTIONS_ENABLED=false`. This repository rejects live Razorpay keys for
actions; enabling Test Mode actions is a separately reviewed demonstration change.

## 3. Preflight and migrate

Run the full quality gate and deterministic proof against the exact release commit:

    make check
    uv run chakravyuh-judge-demo --seed-start 50000 --seed-count 100

Render and review Kustomize output, create the namespace/configuration, then run the versioned
migration Job exactly once. Require successful completion before any new API or processor pod is
rolled out. `alembic check` must report no pending model drift.

## 4. Roll out and observe

Roll out the API, processors, and web deployments. Require all API readiness probes, graph health,
worker queues, and diagnosis queues to stabilize. Scrape `/internal/metrics` with a principal holding
only `metrics:read`. Watch error rate, p95 latency, dead letters, oldest queue age, graph lag, policy
denials, uncertain executions, and Redis availability.

Start with actions disabled. If a reviewed Test Mode demonstration enables them, use separate maker,
checker, and executor principals; set a small amount cap; execute one known authorization; and verify
the append-only proposal, approval, mutation checkpoint, and receipt before proceeding.

## 5. Roll back safely

Disable actions first. Application rollback is allowed only when the previous version understands
the current schema; never downgrade a database during incident response without a reviewed migration
plan. Scale consumers down if a bad reducer or projector release is producing derived drift. Retain
the raw ledger, then replay or rebuild through the audited commands after the corrected release.

For ambiguous capture results, fetch authoritative provider state and follow the Phase 9 reconciliation
path. Never manually re-POST capture because a client timed out.

## 6. External gates before real production

- Razorpay review and a design that accepts live credentials only after independent security review.
- Workforce OIDC, token expiry/revocation, device policy, and break-glass ownership.
- External Secrets/KMS rotation, encrypted backups, tested point-in-time restore, and retention policy.
- Managed PostgreSQL/Redis/Neo4j capacity, multi-zone failure tests, dashboards, paging, and SLO owner.
- Privacy, legal, merchant consent, incident response, penetration test, and cost controls.
