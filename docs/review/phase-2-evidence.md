# Phase 2 verification evidence

- Status: implementation complete; awaiting owner review
- Date: 2026-08-24

## Quality gate

The complete local gate passed against real PostgreSQL:

- Ruff lint and formatting: passed across `src`, `tests`, and `migrations`.
- Mypy strict mode: passed across 40 Python files.
- Backend tests: 52 passed, including 5 PostgreSQL integration proofs.
- Backend branch coverage: 98.56 percent.
- Biome and TypeScript strict checking: passed.
- Web tests: 2 passed.
- Next.js production build: passed.

## Migration evidence

- An empty isolated database upgraded through revisions `20260824_0001` and
  `20260824_0002` to head.
- That database downgraded to base and upgraded to head again.
- Alembic reported no difference between reviewed migrations and application metadata.
- The isolated verification database was removed afterward.

## Delivery evidence

A real HTTP server and PostgreSQL instance produced:

- first signed delivery: `202`, accepted `true`;
- identical retry: `200`, accepted `false`, with the same internal event ID;
- same provider event ID with different signed bytes: `409`;
- PostgreSQL-backed readiness: `200`, with configuration and PostgreSQL checks successful.

Integration tests sent concurrent identical inserts and proved that exactly one returned inserted.
They also proved the database rejects UPDATE, DELETE, and TRUNCATE against the ledger.

## Container evidence

- `chakravyuh-api:phase-2` built with both migrations and reported revision
  `20260824_0002 (head)` from inside the image.
- `chakravyuh-web:phase-2` built successfully after one transient Docker Hub TLS timeout.
- Both images declare the non-root `chakravyuh` runtime user.
- Running API and web containers returned successful health responses.
- Temporary proof containers and the Compose network were removed; development volumes were kept.

## Deliberate limitations

- Intake supports one configured Razorpay merchant per process. A later secrets repository can
  implement multi-tenant secret lookup without changing the application use case.
- Payload retention, encrypted-at-rest storage, restricted backup access, TLS termination, and
  provider IP allowlisting are deployment controls required before real production data.
- The Phase 2 worker does not consume or normalize the ledger yet.
- No Neo4j write, model call, outbound Razorpay request, or money action exists.
- Private GitHub CI remains the last verification item before owner review.
