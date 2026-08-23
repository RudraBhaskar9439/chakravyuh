# Phase 1: production foundation

## Objective

Create a reviewable architecture in which payment correctness remains deterministic as graph, model, and provider adapters are introduced.

## Process boundaries

The initial deployment has three processes:

1. The API accepts operator requests, merchant events, and provider webhooks.
2. The worker normalizes events, builds projections, detects incidents, and executes approved work.
3. The web application displays graph and audit state and submits operator approvals.

These processes share one Python package so domain rules cannot drift between separately versioned services.

## Dependency direction

    HTTP / queue adapters
            ↓
    application ports and use cases
            ↓
    pure domain contracts

Infrastructure implements application ports. Domain code does not import FastAPI, SQLAlchemy, Neo4j, Redis, Razorpay, or model SDKs.

## Data ownership

PostgreSQL will own:

- raw immutable events;
- normalized immutable events;
- canonical payment and merchant state;
- incidents, proposals, decisions, approvals, and outcomes;
- idempotency and action-attempt records.

Neo4j will own no authoritative state. It is a projection optimized for evidence-path traversal and visualization. A graph can be dropped and rebuilt from PostgreSQL without changing any financial outcome.

Redis will provide transient work delivery and coordination. Losing Redis may delay work but may not lose an accepted event or completed action.

## AI boundary

The model receives a redacted incident subgraph and an allowlisted set of candidate actions. Its output is a typed ActionProposal. It cannot:

- read credentials;
- choose arbitrary tools;
- bypass deterministic policy;
- approve its own action;
- write authoritative state.

## Phase 1 readiness

The API readiness endpoint checks configuration only. PostgreSQL, Redis, and Neo4j probes will be added in the same phase that their adapters become required. Reporting a dependency as healthy before a real adapter exists would be false operational confidence.

## Deferred work

- Database schemas and migrations
- Razorpay adapter
- Webhook verification and event ingestion
- Graph projection
- Invariant engine
- AI planner
- Recovery execution

Each deferred concern has an application port or explicit repository boundary.

