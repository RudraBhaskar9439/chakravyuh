# ADR 0007: Project Neo4j through PostgreSQL leases and rebuild epochs

- Status: Accepted
- Date: 2026-08-24

## Context

Neo4j is useful for traversing payment evidence but cannot become a second financial source of
truth. A database-spanning transaction between PostgreSQL and Neo4j is unavailable. A worker may
crash before or after the graph commit, a lease may expire during a slow write, and disaster recovery
may restore PostgreSQL to a snapshot older than the disposable graph.

A generation check alone stops an expired writer from overwriting a newer journey, but it also stops
an authoritative rebuild after PostgreSQL is restored behind Neo4j. An unconditional force flag
would solve the rebuild but reintroduce the stale-writer race.

## Decision

PostgreSQL owns one projection work row per merchant correlation. The journey-state trigger advances
its target version in the same transaction that changes authoritative state. Projectors claim short,
expiring leases with `FOR UPDATE SKIP LOCKED`, load a complete state plus immutable normalized-event
evidence, and replace one Neo4j journey subgraph in a managed transaction.

Every projection carries an ordered pair `(projection_epoch, state_generation)`. Neo4j accepts a
write only when its epoch is newer, or when epochs match and its generation is at least the stored
generation. Ordinary state changes retain their epoch and advance generation. An audited global
rebuild assigns a new database timestamp epoch to every work row. This gives an authoritative rebuild
priority over an older graph without granting a permanent force capability.

The worker checkpoints PostgreSQL only after Neo4j commits and only while the exact unexpired lease
is still owned. A crash after the graph commit leaves the checkpoint pending; lease recovery repeats
the idempotent replacement. Once every applicable work row has reached a rebuild epoch, the projector
deletes graph journeys from older epochs and then appends a unique completion receipt. This sweep is
idempotent across a crash and removes graph-only residue after a point-in-time restore. PostgreSQL
attempt, rebuild, and rebuild-completion records are append-only.

## Consequences

- PostgreSQL remains the sole authority and can reconstruct Neo4j from reviewed derived data.
- A graph commit may repeat, but identical epoch/generation input produces the same graph and receipt.
- An expired writer cannot overwrite a newer generation or checkpoint a result after lease expiry.
- A newer audited rebuild epoch can repair a graph that is ahead of a restored PostgreSQL snapshot.
- A completed rebuild converges both additions and deletions; graph-only journeys cannot survive the
  epoch finalization sweep.
- There is no distributed transaction. Correctness depends on idempotent graph replacement, graph-side
  ordering, and PostgreSQL-side lease validation, all of which require real two-database tests.
- Graph availability is isolated from webhook intake and journey reduction by a separate process.
