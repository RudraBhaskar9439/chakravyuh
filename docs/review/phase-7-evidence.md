# Phase 7 verification evidence

- Status: release verification in progress
- Date: 2026-08-24

## Implemented safety case

Phase 7 adds a separate leased diagnosis worker, a bounded read-only evidence traversal, canonical
evidence and prompt hashes, Gemini structured output, deterministic abstention, and immutable
receipts. The model has no tools and no path to incident detection, incident status, action queues,
or Razorpay APIs.

## Real service evidence

The integration proof created a captured-payment/order-state incident through the real PostgreSQL
pipeline, projected its exact journey to a real Neo4j 5.26 service, and assembled the evidence back
under its PostgreSQL generation and state hash. It proved:

- the subgraph contained closed, citable journey, entity, event, and invariant facts;
- raw webhook bodies were absent;
- completing the exact lease atomically wrote one immutable diagnosis and attempt;
- update and delete against both audit tables failed with the append-only database guard;
- a permanent oversized-evidence failure dead-lettered immediately; and
- an expired worker could not commit after a replacement worker acquired the lease.

Migration `20260824_0007` applied successfully to the working database and Alembic reported no
metadata drift.

## Live provider evidence

A live call using the locally configured Gemini credential and `gemini-3.5-flash` completed twice
without logging the credential or prompt evidence. The final guarded response diagnosed the
synthetic authorization-not-captured case as `capture_not_completed`, cited only supplied evidence,
recommended the incident-allowlisted `capture_payment` action, and required no guard intervention.
Both the prompt and evidence subgraph produced 64-character SHA-256 audit hashes. Provider storage
was disabled and no tools were supplied. This proves compatibility and guard behavior for the
fixture; it is not a model-accuracy claim on production traffic.

## Local quality gate

- Ruff lint and formatting passed across 107 Python source, test, and migration files.
- Mypy strict mode passed across 106 Python files.
- Backend tests: 216 passed, including the real PostgreSQL and Neo4j diagnosis proof.
- Backend branch coverage: 97.29 percent.
- Biome and TypeScript strict checks passed.
- Web tests: 2 passed.
- The Next.js production build passed.

## Migration and container evidence

- A separate empty database upgraded through all seven migrations, downgraded Phase 7, re-upgraded
  to head, and reported no metadata drift. The temporary database was removed afterward.
- The working database also upgraded to `20260824_0007` and reported no metadata drift.
- Backend and web production images built successfully.
- The backend image runs as non-root UID 10001, reports version 0.7.0 and migration head
  `20260824_0007`, and contains the isolated `chakravyuh-diagnosis-worker` command.

## Pending release evidence

The implementation commit and private GitHub Actions run will be appended before the phase status
advances.
