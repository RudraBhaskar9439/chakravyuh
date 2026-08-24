# Phase 5: rebuildable money graph

## Objective

Materialize a traversal-friendly payment evidence graph without allowing Neo4j availability,
delivery timing, or an expired worker to alter authoritative financial state.

## Authority and commit path

PostgreSQL owns normalized events, reduced journey state, projection intent, leases, checkpoints, and
immutable audit records. Neo4j owns only a disposable projection.

    journey state INSERT or UPDATE
      └── PostgreSQL trigger advances target_version and desired_at

    projector process
      ├── lease correlations with FOR UPDATE SKIP LOCKED
      ├── load current state and complete normalized-event evidence
      ├── verify state hash, event count, identities, and journey ownership
      ├── Neo4j managed transaction replaces one journey subgraph
      ├── graph rejects an older (epoch, generation)
      └── PostgreSQL transaction records the attempt and checkpoint

The checkpoint transaction requires the same worker, attempt number, processing status, and an
unexpired database-time lease. If state changes while a projection is running, the trigger advances
the target version. The old checkpoint records what committed but leaves the work pending for the
new target.

## Crash and concurrency contract

| Failure point | Durable outcome | Recovery |
| --- | --- | --- |
| Before Neo4j commit | No graph or checkpoint change | Retry after failure delay or lease expiry |
| After Neo4j commit, before checkpoint | Graph may be ahead; PostgreSQL remains pending | Repeat the idempotent graph transaction, then checkpoint |
| Lease expires before checkpoint | Old owner is rejected | Replacement worker owns the next attempt |
| Old graph writer finishes after a newer writer | Graph epoch/generation guard rejects it | No newer graph state is overwritten |
| State changes during graph write | Old target may checkpoint, newer target stays pending | Next pass projects complete new state |
| Neo4j remains unavailable | Stable retry codes progress to a visible dead letter | Restore connectivity, request audited rebuild |
| PostgreSQL restore leaves graph-only journeys | Rebuild remains operationally pending | Epoch finalizer prunes older journeys and orphan nodes |

There is deliberately no cross-database transaction. Safety comes from independent guards on both
sides rather than an assumption of exactly-once delivery.

## Graph model

Each key is a deterministic SHA-256 digest scoped by merchant and provider identity. Unique
constraints cover all node classes.

- `Merchant -[:OWNS]-> PaymentJourney`
- `PaymentJourney -[:CONTAINS]-> FinancialEntity`
- `PaymentJourney -[:HAS_EVENT]-> MoneyEvent`
- `MoneyEvent -[:DESCRIBES]-> FinancialEntity`
- `FinancialEntity -[:RELATES_TO {kind}]-> FinancialEntity`

The complete journey-owned edge set is replaced in one transaction. Orphaned prior-version entity
and event nodes are removed only when no journey owns them. Shared entity facts use event time so a
placeholder or an older journey snapshot cannot erase newer provider-backed facts.

Neo4j receives normalized identifiers, integer-subunit amounts, statuses, timestamps, hashes, and
explicit relationships. Raw webhook bodies, arbitrary provider payloads, API credentials, and
webhook secrets never enter graph parameters.

## Rebuild epochs

The graph compares `(projection_epoch, state_generation)` lexicographically. Normal processing keeps
the epoch stable, making generation the stale-worker fence. `chakravyuh-graph-rebuild` requires a
bounded operator identity and reason, appends an immutable rebuild record, assigns a new PostgreSQL
timestamp epoch to every journey, and re-enqueues all current states. The newer epoch authorizes an
authoritative reconstruction even if Neo4j contains a numerically higher generation from an older
database snapshot. After all work at or before that epoch is complete, the projector transaction
removes older-epoch journeys, then unowned events, entities, and merchants. A unique append-only
completion receipt checkpoints the sweep. A crash before that receipt repeats a safe idempotent
cleanup; later-epoch nodes are never eligible for deletion.

## Observability and failure boundary

`GET /health/graph` combines a real Neo4j connectivity check with PostgreSQL-authoritative counts for
pending, processing, and dead-lettered work, maximum version lag, and oldest desired projection age.
It returns failure when Neo4j is unreachable, any dead letter exists, the lag query fails, or oldest
lag exceeds `CHAKRAVYUH_GRAPH_PROJECTION_LAG_THRESHOLD_SECONDS`. It also remains unhealthy while any
rebuild lacks its graph-pruning completion receipt. The response contains no merchant, correlation,
provider, payload, or secret values.

Errors are stored only as stable codes. Projector logs contain batch counts and exception types, not
payloads. A separate projector process means graph degradation cannot block verified webhook commits
or deterministic PostgreSQL reduction.

## Deliberate boundaries

- Phase 5 creates no incidents; deterministic invariant classification begins in Phase 6.
- It performs no model call, outbound Razorpay request, approval, or money movement.
- Health is service-level, not a public merchant troubleshooting API.
- Production still requires encrypted backups, least-privilege database roles, supervised processes,
  alert routing, retention policy, and deployment-specific capacity thresholds.
