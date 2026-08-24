# Phase 10 verification evidence

- Status: approved
- Date: 2026-08-24

## Implemented control plane

Phase 10 adds explicit operator scopes, bounded per-client and per-principal authentication limits,
a required Redis production limiter, exact trusted-host enforcement, hardened response headers, and
an authenticated Prometheus endpoint with bounded route-template labels. It also adds a deterministic
judge proof, a guarded signed-ingress load probe, deployment policy tests, and a Kubernetes release
template with no committed Secret.

## Local quality and service gates

- Ruff lint and formatting passed across 138 Python source, test, and migration files.
- Mypy strict mode passed across 137 configured source, test, and migration files.
- Backend tests: 318 passed, including real PostgreSQL and Neo4j integration proofs.
- Backend branch coverage: 94.67 percent.
- Biome and TypeScript strict checks passed; 4 web tests and the Next.js production build passed.
- `kubectl kustomize deploy/kubernetes` rendered the complete manifest set successfully.
- npm production and Python dependency audits reported no known vulnerabilities.
- Exact-value scanning confirmed configured Razorpay and Gemini secrets absent from tracked content;
  `.env` remains untracked.

## Deterministic correctness and chaos proof

The offline gate evaluated 1,500 labelled held-out synthetic cases from seeds 50,000 through 50,099.
It reported precision 1.0, recall 1.0, zero false positives, and zero false negatives on that dataset.
Duplicate delivery and out-of-order delivery produced their expected identical state hashes. Exact
Test Mode capture required checker approval; oversize capture, low confidence, and the kill switch
all produced deterministic denials.

The gate passed its 50 ms p95 and 100 cases/second local thresholds. On this machine it measured
0.024125 ms p50, 0.038875 ms p95, 0.293916 ms maximum case latency, and 39,362.37 cases/second. The
stable correctness proof SHA-256 was
`aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.

These figures describe generated, labelled, held-out synthetic cases on one local machine. They do
not claim zero false negatives, the same latency, or the same throughput on unknown merchant traffic.

## Isolated signed-ingress proof

A fresh isolated PostgreSQL database upgraded through migration head `20260824_0009`. Against the
real local API, the probe sent 500 unique HMAC-authenticated webhook events and 100 selected retries
at concurrency 25. All 500 unique requests returned durable `202 accepted`; all 100 retries returned
`200 duplicate`. PostgreSQL contained exactly 500 raw-ledger rows and 500 normalization work rows.

The run passed at 355.77 requests/second with 47.61 ms p50 and 228.32 ms p95. Its run ID was
`phase10proof2308`. The API was stopped and the isolated database was removed after verification.
A separate real Redis proof allowed two requests and denied the third, then removed its exact proof
key.

## Migration, container, and browser gates

- Another empty database upgraded to head and `alembic check` reported no model drift; the temporary
  database was removed.
- Backend and web production images built and ran as UID/GID 10001.
- The backend image reports version 0.10.0, migration head `20260824_0009`, contains both Phase 10
  commands, and passes the judge proof inside the image.
- The web image compiled the configured API origin, passed its live health endpoint, and rendered
  the Phase 10 console.
- Real browser QA passed at 1440-by-1000 and 390-by-844: no horizontal overflow, 48/49-pixel mobile
  controls, password input with autocomplete off, empty token value, and no console warnings/errors.

## Private CI and approval

- Implementation commit: `a9928ac1d7cc211cc72ed334bee3ea3853129c0a`.
- Private CI run: <https://github.com/RudraBhaskar9439/chakravyuh/actions/runs/32758443348>.
- Repository policy, backend, web, and production-container jobs all passed.
- The CI backend independently ran the migration, metadata-drift check, strict lint/type gates,
  PostgreSQL/Neo4j tests, branch coverage, and a 25-seed judge proof.
- GitHub reported zero open Dependabot alerts at approval time; local npm production and Python
  audits also reported no known vulnerabilities.

Phase 10 and the ten-phase buildathon implementation are approved under the owner's standing
authorization of 2026-08-24. Real production activation remains subject to every external gate in
the production runbook; Razorpay action execution remains Test Mode only and disabled by default.
