# Chakravyuh

Chakravyuh is a self-healing money graph for Razorpay payment journeys. It detects missing or contradictory state transitions, assembles an evidence path, and proposes a bounded recovery action.

The project is implemented in eleven auditable phases. Phase 10 hardens the complete evidence and
action mesh with scoped operator authority, fail-closed throttling, deterministic correctness and
chaos proofs, and production deployment manifests. Phase 11 adds a separately gated Razorpay Test
Checkout that can create the exact authorized-but-uncaptured payment used in the recovery proof. AI
remains non-executable: deterministic policy, immutable maker-checker approval, exact-amount
preflight, and Test-Mode-only Razorpay adapters control every outbound operation.

Repository policy: private access only. The source and generated evaluation artifacts must not be published without the owner's explicit approval.

## Architecture principles

- PostgreSQL is the authoritative event and financial state store.
- Neo4j is a rebuildable graph projection, never the source of truth.
- Every financial action passes through deterministic policy and approval checks.
- AI produces structured diagnoses and proposals; it cannot execute tools directly.
- Raw events are append-only and derived state is replayable.
- External events are assumed to be duplicated, delayed, and out of order.

## Local prerequisites

- Python 3.12
- uv
- Node.js 24+
- pnpm 11+
- Docker with Compose

## Bootstrap

    cp .env.example .env
    make bootstrap
    make infra-up

Run the API and web application in separate terminals:

    make api
    make worker
    make projector
    make diagnosis-worker
    make web

The API liveness endpoint is http://localhost:8000/health/live. The web application is available at http://localhost:3000.

`make infra-up` waits for local dependencies and applies all database migrations. The readiness
endpoint at http://localhost:8000/health/ready returns success only when PostgreSQL answers a real
query.

## Verified webhook intake

Configure a Test Mode merchant identity, account identity, and webhook secret in `.env`, then use:

    POST /v1/webhooks/razorpay/{merchant_id}

The endpoint:

- reads a size-bounded stream rather than an unbounded request body;
- verifies `X-Razorpay-Signature` over the exact raw bytes before parsing JSON;
- requires `X-Razorpay-Event-Id` as the provider idempotency identity;
- supports the current and previous secret during safe secret rotation;
- commits the verified body to PostgreSQL before returning 2xx;
- returns `202` for a new event and `200` for an identical provider retry;
- returns `409` if one provider event ID is reused with different content.

PostgreSQL rejects row updates, deletes, and table truncation on the raw ledger. Provider events
may arrive late or out of order; ordering is not inferred at intake.

## Durable normalization worker

The worker claims pending raw events directly from PostgreSQL and emits one canonical payment,
order, refund, or payment-link event. Multiple worker replicas can run safely. Contract failures
become visible dead letters; unexpected failures roll back to pending without a partial output.

Run it locally after applying migrations:

    make worker

After deploying reviewed normalizer support, an authorized operator can replay one dead letter:

    uv run chakravyuh-replay RAW_EVENT_UUID \
      --requested-by operator@example.com \
      --reason "Reviewed normalizer support deployed"

Replay is intentionally a host/database-authorized operation rather than a public HTTP endpoint.
See [Phase 3 architecture](docs/architecture/phase-3-durable-normalization.md) for the transaction
and failure guarantees.

## Temporal payment journeys

Every committed normalized event marks its merchant correlation dirty in PostgreSQL. The same worker
then rebuilds the correlation from its complete immutable history, using event time plus stable
tie-breakers rather than arrival order. A successful reduction atomically writes:

- one replaceable current state in `state.payment_journey_states`;
- one immutable, content-hashed revision in `ledger.payment_journey_revisions`;
- one immutable attempt record; and
- the completed queue generation.

Generate an offline proof without credentials or network access:

    chakravyuh-simulate --scenario out_of_order_delivery --seed 42

The output includes delivered events, expected payment status, reduced state, and its SHA-256 hash.
Available scenarios cover success, authorization without capture, capture without order payment,
failed-then-recovered payment, partial refund, out-of-order delivery, and duplicate delivery.

After a reviewed reducer release or a corrected safety limit, an authorized operator can request a
rebuild without deleting history:

    chakravyuh-journey-replay merchant-id correlation-id \
      --requested-by operator@example.com \
      --reason "Reviewed temporal reducer release deployed"

See [Phase 4 architecture](docs/architecture/phase-4-temporal-journeys.md) for ordering, transaction,
and replay guarantees.

## Rebuildable money graph

The separate projector process leases dirty journey correlations from PostgreSQL and replaces one
complete Neo4j subgraph per managed transaction. The graph contains merchants, payment journeys,
financial entities, event evidence, and explicit provider-backed relationships. Raw webhook payloads
and secrets are never copied into Neo4j.

Run the projector alongside the main normalization/reduction worker:

    make projector

`GET /health/graph` checks both Neo4j connectivity and PostgreSQL-authoritative queue lag. It fails
closed for an unreachable graph, dead letters, or lag beyond the configured threshold. After an
operator reviews a graph-wide recovery, every journey can be re-enqueued under a new audited epoch:

    uv run chakravyuh-graph-rebuild \
      --requested-by operator@example.com \
      --reason "Reviewed Neo4j recovery and projection rebuild"

Epoch-plus-generation guards prevent an expired worker from overwriting newer graph state while
allowing PostgreSQL to remain authoritative after disaster recovery. See
[Phase 5 architecture](docs/architecture/phase-5-rebuildable-money-graph.md) for the complete
transaction, crash, and observability contract.

## Deterministic incidents

Every journey-state commit now enqueues invariant evaluation in PostgreSQL. The main worker evaluates
six conservative payment contracts at database time. It reschedules incomplete transitions to their
exact grace-window deadline instead of raising a premature incident. A completed evaluation,
current incident changes, immutable lifecycle revisions, and its queue checkpoint commit in one
transaction.

Run the evaluation-only held-out benchmark without credentials, databases, or network access:

    chakravyuh-evaluate-invariants --seed-start 10000 --seed-count 100

Each seed supplies six labelled positive faults and nine adversarial negative journeys. The JSON
result reports exact-label precision, recall, F1, false-positive and false-negative counts, and an
explicit manual-review cost. This is repeatable contract evidence on synthetic cases, not a claim of
zero false negatives on real merchant traffic.

Incident detection never calls Gemini or queries Neo4j. Evaluations and incident revisions are
append-only; stable incident IDs survive evidence changes, resolution, and recurrence. See
[Phase 6 architecture](docs/architecture/phase-6-invariants-and-incidents.md) for the rule, timing,
transaction, and audit contract.

## Grounded AI diagnosis

Every non-resolved incident revision now advances an isolated diagnosis queue. The diagnosis worker
loads the immutable PostgreSQL checkpoint, reads one bounded allowlisted Neo4j subgraph, requires an
exact generation and state-hash match, and calls Gemini with strict JSON Schema output, disabled
provider storage, and no tools.

    make diagnosis-worker

The deterministic post-model guard requires real citations including invariant evidence, an
incident-allowlisted root cause and action, and minimum confidence. Anything unsafe or weak becomes
an explicit abstention. The model cannot create or resolve incidents and its recommendation cannot
execute. Receipts, attempts, prompt hashes, evidence hashes, retries, dead letters, and guard
interventions are immutable audit records. See
[Phase 7 architecture](docs/architecture/phase-7-grounded-ai-diagnosis.md) for the complete boundary.

After the cause of a temporary provider or graph outage is verified as recovered, an operator can
requeue exactly one dead-lettered diagnosis. The command records the operator, reason, prior stable
error, source incident revision, and target version before returning the item to the queue:

    chakravyuh-diagnosis-replay incident-uuid \
      --requested-by operator-id \
      --reason "Verified model capacity and graph health recovered"

## Operator evidence mesh

The internal operator API reads PostgreSQL incident truth and immutable diagnosis receipts through
three authenticated endpoints under `/v1/operator`: overview, bounded cursor-paginated incident
list, and incident detail. Every authorized read appends a principal-attributed access record and
returns `Cache-Control: no-store`.

Issue a high-entropy local credential:

    uv run chakravyuh-operator-token --principal local-reviewer

Store the one-time `operator_token` output in a password manager. Put only the emitted
`environment_value` JSON into `CHAKRAVYUH_OPERATOR_TOKEN_HASHES`, restart the API, open
http://localhost:3000, and paste the raw token for that browser session. The browser never writes it
to local storage, cookies, a URL, or server-rendered output.

The console renders the exact evidence mesh stored with the latest diagnosis, including its
SHA-256 hash and incident revisions. Production transport must use TLS and an exact CORS allowlist. See
[Phase 8 architecture](docs/architecture/phase-8-operator-control-plane.md) for the authentication,
pagination, audit, and interface contract.

## Guarded Test Mode recovery

Phase 9 implements only two provider actions: an authoritative payment fetch and exact-amount
capture of an `authorized` payment. All other model recommendations are recorded as policy denials.
The outbound kill switch defaults off, and application startup rejects enabled actions unless the
configured key begins with `rzp_test_`.

For a local Test Mode proof, configure two different operator principals, retain only their token
hashes in `CHAKRAVYUH_OPERATOR_TOKEN_HASHES`, and then set:

    CHAKRAVYUH_RAZORPAY_ACTIONS_ENABLED=true

A proposal is derived entirely on the server from the latest immutable diagnosis. Read-only fetch
can execute after policy approval. Capture additionally requires a decision from a principal other
than the proposal maker. Before capture, the adapter fetches current Razorpay state and verifies the
payment ID, `authorized` status, exact integer amount, and currency. It persists a mutation-started
checkpoint before the POST.

Razorpay does not provide the general payment-capture idempotency header available on its payout
APIs. Therefore, any crash or timeout after the checkpoint permits fetch-only reconciliation and
never a blind capture retry. Every proposal, policy decision, checker decision, execution claim,
mutation authorization, result, and operator access event is append-only. See
[Phase 9 architecture](docs/architecture/phase-9-guarded-test-mode-actions.md) for the complete
safety and failure contract.

## Real Razorpay Test Checkout proof

Phase 11 can create one fixed ₹10 Razorpay Test Mode order with per-order manual capture, launch the
official hosted Checkout, and verify its signed success response against authoritative provider
state. The capability has its own `test-checkout:operate` scope and kill switch, stores neither the
Checkout signature nor raw provider bodies, and writes immutable order and verification hashes.

After applying migrations and issuing an operator token with the Test Checkout scope, enable the
capability only in an isolated local or staging environment:

    CHAKRAVYUH_TEST_CHECKOUT_ENABLED=true

Open `http://localhost:3000/demo-checkout`, paste the scoped token, and authorize the displayed ₹10
Test Mode order using Razorpay's documented test credentials. Do not manually capture the payment.
The screen proves the exact provider order, authorized payment, amount, uncaptured state, and
verification hash. A public HTTPS webhook and the final provider-backed incident-to-recovery run are
external Phase 11 gates; the repository never claims those proofs before they are performed.

See [Phase 11 architecture](docs/architecture/phase-11-real-test-checkout.md) for the complete
boundary and [Phase 11 checklist](docs/review/phase-11-checklist.md) for the remaining gates.

## Production hardening and proof

Operator identities now receive explicit scopes for incident reads, proposal creation, checker
decisions, execution requests, and metric scrapes. Local/test environments retain a bounded
in-process limiter for development; production refuses configured operator tokens unless every
principal has explicit scopes and the cluster-wide Redis limiter is selected. Limiter failure denies
authentication.

Run the complete offline judge proof without credentials or services:

    uv run chakravyuh-judge-demo --seed-start 50000 --seed-count 100

It reports held-out exact-label precision/recall and false-positive/false-negative counts, duplicate
and out-of-order state-hash checks, recovery-policy safety checks, local latency/throughput, and a
stable proof SHA-256. This is evidence on labelled synthetic cases, not a guarantee about unseen
merchant traffic.

For an authorized isolated environment, `chakravyuh-load-probe` sends bounded signed webhook events
and proves both durable new-event acknowledgements and duplicate retries. The secret is accepted only
through `CHAKRAVYUH_LOAD_WEBHOOK_SECRET`; remote targets require an explicit acknowledgment flag.
See the [judge demo](docs/demo/judge-demo.md) for the exact flow.

Authenticated Prometheus metrics are available at `GET /internal/metrics` to a principal holding only
`metrics:read`. Labels contain registered route templates, method, and status—never merchant or
payment identifiers.

The Kubernetes release template under `deploy/kubernetes` separates migration, API, processors, and
web workloads, commits no Secret, and enforces non-root/read-only containers, probes, resources,
disruption budgets, and default-deny networking. It deliberately contains placeholder origins and
external dependency addresses. Follow the
[production runbook](docs/operations/production-runbook.md) and replace image tags with registry
digests before applying it. See
[Phase 10 architecture](docs/architecture/phase-10-production-hardening.md) for the complete control
and evidence contract.

## Quality gate

    make check

The gate runs Python linting, formatting, strict type checking, tests with branch coverage, web linting, web tests, and a production web build.

PostgreSQL and Neo4j integration proofs run when `CHAKRAVYUH_TEST_POSTGRES_DSN` and
`CHAKRAVYUH_TEST_NEO4J_URI` are defined. CI always runs them against isolated services.

## Migrations

    make migrate
    make migration-check

Application startup never edits the schema implicitly. A release must apply the reviewed Alembic
migrations before starting the API and worker processes.

## Repository boundaries

    src/chakravyuh/domain          Pure domain contracts and invariants
    src/chakravyuh/application     Use cases and ports
    src/chakravyuh/infrastructure  Database, graph, queue, and provider adapters
    src/chakravyuh/api             HTTP transport
    src/chakravyuh/worker          Asynchronous process entrypoint
    src/chakravyuh/projector_worker Neo4j projection process entrypoint
    src/chakravyuh/diagnosis_worker Evidence-grounded model diagnosis process entrypoint
    apps/web                       Operator interface
    docs                           Architecture decisions and review evidence

Synced material under sources/ is reference-only and is not used or modified by the application.
