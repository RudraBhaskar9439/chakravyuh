# Chakravyuh

Chakravyuh is a self-healing money graph for Razorpay payment journeys. It detects missing or contradictory state transitions, assembles an evidence path, and proposes a bounded recovery action.

The project is being implemented in auditable phases. Phase 4 adds a deterministic temporal reducer,
immutable journey revisions, audited rebuilds, and an offline synthetic payment-journey generator.
No outbound Razorpay call or financial action exists yet.

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

## Quality gate

    make check

The gate runs Python linting, formatting, strict type checking, tests with branch coverage, web linting, web tests, and a production web build.

PostgreSQL integration proofs run when `CHAKRAVYUH_TEST_POSTGRES_DSN` is defined. CI always runs
them against an isolated PostgreSQL service.

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
    apps/web                       Operator interface
    docs                           Architecture decisions and review evidence

Synced material under sources/ is reference-only and is not used or modified by the application.
