# Phase 5 verification evidence

- Status: local verification complete; private CI pending implementation push
- Date: 2026-08-24

## Quality gate

The complete local gate passed against real PostgreSQL and Neo4j:

- Ruff lint and formatting passed across `src`, `tests`, and `migrations`.
- Mypy strict mode passed across 82 Python files.
- Backend tests: 154 passed, including every PostgreSQL and Neo4j integration proof.
- Backend branch coverage: 98.83 percent.
- Biome and TypeScript strict checking passed.
- Web tests: 2 passed.
- The Next.js production build passed.

## Real two-database evidence

Nine Phase 5 integration tests prove:

- a graph transaction commits before its PostgreSQL attempt and checkpoint;
- repeating a graph commit before checkpoint is idempotent;
- an expired lease is reclaimable and the old owner cannot fail or checkpoint it;
- a graph generation newer than an expired writer is retained;
- a state change during projection leaves a new target pending;
- three concurrent projectors partition six correlations without overlap;
- bounded failures dead-letter and recover through an audited rebuild;
- rebuild finalization removes a real graph-only journey and appends exactly one completion receipt;
- graph projection audit tables reject update, delete, and truncate; and
- invalid lease, retry, receipt, load, and rebuild inputs fail closed.

The stale-writer proof runs against real Neo4j. A newer generation commits first, the older public
projector call raises `StaleGraphProjectionError`, and the stored generation remains newer. The
rebuild proof then assigns a later epoch and successfully reconstructs all states, including a case
where the prior graph generation was ahead of PostgreSQL. Before finalization, health reports the
unfinished rebuild. The real Neo4j sweep removes an injected generation-99 ghost journey while
preserving every current-epoch journey, then duplicate completion becomes a no-op.

## Migration evidence

- The working database upgraded to revision `20260824_0005`, downgraded to Phase 4, upgraded again,
  and matched SQLAlchemy metadata with no generated operations.
- A separately created empty database upgraded through Phase 4 and Phase 5, downgraded Phase 5,
  upgraded to head, and reported migration head `20260824_0005` with no schema drift.
- The isolated verification database was removed afterward.

## Runtime evidence

- A final audited rebuild enqueued 335 authoritative journeys under one new epoch.
- The real version 0.5.0 projector drained them in seventeen batches: sixteen batches of 20 and one
  batch of 15, then logged one successful rebuild finalization.
- Every runtime batch reported zero retries, zero dead letters, and zero lost leases.
- The live graph-health endpoint returned HTTP 200 with zero pending, processing, dead-lettered, and
  unfinished-rebuild work, and zero version or time lag.
- PostgreSQL contained 335 completed work rows and nine uniquely paired rebuild/completion records.
- Neo4j contained 335 journeys, 305 merchants, 353 financial entities, and 365 event-evidence nodes
  behind four unique constraints. No `MoneyEvent` node had a payload property.
- SIGINT produced a clean `projector_worker_stopped` shutdown after the queue reached idle.
- Both production images built and ran as non-root UID 10001. The backend image contained version
  0.5.0, migration head `20260824_0005`, the projector, and audited rebuild command. A real projector
  container connected to both databases and logged clean start and SIGTERM shutdown.

## Private CI

The implementation commit and exact private GitHub Actions run will be recorded here after the push.

## Deliberate limitations

- Neo4j is a derived traversal index, not financial truth and not the Phase 6 incident detector.
- Projection health is aggregate operational evidence, not complete deployment monitoring.
- Model diagnosis, recovery proposals, operator approvals, and bounded Test Mode actions remain later
  phases; Phase 5 cannot call an LLM or move money.
- Production deployment still requires encrypted backups, least-privilege roles, supervised workers,
  alert delivery, and a reviewed retention and capacity policy.
