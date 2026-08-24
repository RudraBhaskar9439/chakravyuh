# Phase 4 verification evidence

- Status: local implementation proof complete; private CI pending
- Date: 2026-08-24

## Quality gate

The complete local gate passed against real PostgreSQL:

- Ruff lint and formatting passed across `src`, `tests`, and `migrations`.
- Mypy strict mode passed across 64 Python files.
- Backend tests: 116 passed, including 19 real PostgreSQL integration proofs across Phases 2–4.
- Backend branch coverage: 98.92 percent.
- Biome and TypeScript strict checking passed.
- Web tests: 2 passed.
- The Next.js production build passed.

## Temporal and synthetic evidence

- All seven named synthetic scenarios reproduce byte-stable identities and expected effective payment
  status from the same seed.
- Reversing a successful delivery produced the same canonical state and SHA-256 hash.
- Duplicate delivery reduced four unique events from five delivered inputs.
- A processed partial refund produced exact subunit totals and a refund-to-payment edge.
- Unknown future provider status remained visible with no fabricated effective status.
- CLI scenario `out_of_order_delivery`, seed `42`, reduced four delivered events to captured state with
  hash `f02fce00c4b1a9f0a0ab10569067f77637e06dd9f0c2d8fedbcc277c4d95f564`.

## Real PostgreSQL evidence

Eight Phase 4 integration tests proved:

- trigger-based work creation and one atomic current state, revision, attempt, and completion;
- full-history recomputation after a late earlier event without regressing the latest payment state;
- three concurrent workers claimed six distinct correlations exactly once;
- an oversized correlation dead-lettered without state and recovered through an audited replay;
- a completed correlation rebuilt at a new generation with the same content hash;
- an injected unexpected reducer exception rolled back to pending with zero attempt or partial state;
- invalid operational bounds and replay states were rejected; and
- PostgreSQL rejected UPDATE, DELETE, and TRUNCATE against all Phase 4 audit ledgers.

The existing database upgraded from Phase 3 with zero normalized correlations missing a Phase 4 work
row. The proof database contained 114 current journey states, 123 immutable revisions, and 126
attempts after the combined test and runtime exercises.

## Migration evidence

- The existing Phase 3 database upgraded to revision `20260824_0004`.
- A separate empty database upgraded to head, downgraded to base, and upgraded to head again.
- Alembic reported no difference between migration head and SQLAlchemy metadata.
- The isolated verification database was removed afterward.

## Runtime and container evidence

- A real version 0.4.0 worker committed a 17-item pipeline batch and shut down cleanly on SIGINT.
- The offline simulator emitted schema-shaped JSON containing delivery, truth, state, and state hash.
- `chakravyuh-api:phase-4` built with migration head `20260824_0004`, worker, simulator, normalization
  replay, and journey replay commands.
- The production backend container ran as non-root UID 10001, connected to PostgreSQL, and logged a
  clean SIGINT shutdown.
- `chakravyuh-web:phase-4` built successfully and ran as non-root UID 10001.

## Private CI

Pending the Phase 4 implementation push. The successful run URL and exact commit are added before
the phase is closed.

## Deliberate limitations

- The reducer records provider contradictions rather than hiding them; Phase 6 will classify those
  contradictions through deterministic invariants.
- Current state is replaceable; immutable revisions and normalized events are the reproducibility
  evidence.
- Neo4j, incident creation, model calls, outbound Razorpay calls, and financial actions remain absent.
- Production deployment still requires encrypted storage and backups, least-privilege roles, queue
  age/dead-letter/worker alerting, and an approved retention policy.
