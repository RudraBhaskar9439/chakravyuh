# Phase 3 verification evidence

- Status: approved
- Date: 2026-08-24

The owner approved Phase 3 on 2026-08-24 through the explicit instruction to start Phase 4.

## Quality gate

The complete local gate passed against real PostgreSQL:

- Ruff lint and formatting: passed across `src`, `tests`, and `migrations`.
- Mypy strict mode: passed across 50 Python files.
- Backend tests: 82 passed, including 11 real PostgreSQL integration proofs across Phases 2 and 3.
- Backend branch coverage: 98.92 percent.
- Biome and TypeScript strict checking: passed.
- Web tests: 2 passed.
- Next.js production build: passed.

## Migration evidence

- The existing Phase 2 database upgraded from `20260824_0002` to `20260824_0003`, and every old
  raw event received a pending work row.
- A separate empty database upgraded to head, downgraded to base, and upgraded to head again.
- Alembic reported no difference between migration head and SQLAlchemy metadata.
- The isolated verification database was removed afterward.

## Concurrency and failure evidence

Real PostgreSQL tests proved:

- four workers concurrently claimed eight events in batches of two;
- all eight raw events produced exactly eight normalized outputs and eight attempt records;
- a supported event committed its output, attempt, and completed status together;
- a permanent unsupported event committed a payload-free dead-letter code and no normalized output;
- an injected unexpected exception rolled the transaction back to pending with zero output and zero
  attempt rows;
- a completed event could not be replayed;
- a dead letter replay retained operator, reason, identity, and database time, incremented its attempt
  sequence, and preserved the prior failure;
- PostgreSQL rejected UPDATE, DELETE, and TRUNCATE against normalized events, attempts, and replay
  audit tables.

## Runtime evidence

- A real version 0.3.0 worker drained all six pending rows in one committed batch and then logged a
  clean SIGINT shutdown.
- The installed `chakravyuh-replay` command created replay
  `239fe77f-60d0-4688-a4fe-35d8f083ebaf` for one test dead letter.
- A worker consumed that replay, appended a second failed attempt, and returned it to dead-letter
  state because the same unsupported contract was intentionally still deployed.
- Batch and failure logs contained counts and error classes, never webhook payloads.

## Container evidence

- `chakravyuh-api:phase-3` built with worker, replay command, and migration revision
  `20260824_0003 (head)`.
- The production worker container ran as UID 10001, connected to PostgreSQL, and logged a clean
  SIGTERM shutdown.
- `chakravyuh-web:phase-3` built successfully and declares UID 10001.
- The temporary worker proof container was removed; the local PostgreSQL development volume was
  retained.

## Private CI

Private GitHub Actions run
[`32734520074`](https://github.com/RudraBhaskar9439/chakravyuh/actions/runs/32734520074)
passed the private-repository policy, real-PostgreSQL backend gate, frontend gate, migration check,
non-root image check, installed-worker check, and both production container builds.
GitHub reports no open Dependabot alerts after this run.

## Deliberate limitations

- This normalizer intentionally supports only payment, order, refund, and payment-link event
  families. Other verified Razorpay families remain recoverable in the raw ledger and become visible
  dead letters rather than guessed graph facts.
- Replay uses host and database authorization. A future operator API must add strong authentication,
  role checks, and the same audit contract before exposing this capability over HTTP.
- Production deployment still requires encrypted storage and backups, least-privilege database roles,
  alerting on queue age/dead letters/worker absence, and an approved payload-retention schedule.
- No model training, Neo4j projection, outbound Razorpay call, or financial action exists in Phase 3.
