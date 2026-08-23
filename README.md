# Chakravyuh

Chakravyuh is a self-healing money graph for Razorpay payment journeys. It detects missing or contradictory state transitions, assembles an evidence path, and proposes a bounded recovery action.

The project is being implemented in review-gated phases. Phase 1 establishes the production foundation; no live financial action exists yet.

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
    make web

The API liveness endpoint is http://localhost:8000/health/live. The web application is available at http://localhost:3000.

## Quality gate

    make check

The gate runs Python linting, formatting, strict type checking, tests with branch coverage, web linting, web tests, and a production web build.

## Repository boundaries

    src/chakravyuh/domain          Pure domain contracts and invariants
    src/chakravyuh/application     Use cases and ports
    src/chakravyuh/infrastructure  Database, graph, queue, and provider adapters
    src/chakravyuh/api             HTTP transport
    src/chakravyuh/worker          Asynchronous process entrypoint
    apps/web                       Operator interface
    docs                           Architecture decisions and review evidence

Synced material under sources/ is reference-only and is not used or modified by the application.
