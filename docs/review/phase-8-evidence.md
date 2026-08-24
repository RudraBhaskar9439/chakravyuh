# Phase 8 verification evidence

- Status: approved
- Date: 2026-08-24

## Implemented safety case

Phase 8 adds an authenticated, audited, read-only operator API and a production-built evidence-mesh
console. PostgreSQL supplies current incident truth and the exact immutable diagnosis receipt. The
web client holds its bearer token only in session memory. No action proposal, approval, queue, or
Razorpay mutation endpoint exists.

## Real service evidence

The PostgreSQL-and-Neo4j integration proof creates a deterministic incident and immutable diagnosis,
then reads overview, filtered list, and detail through the real operator read model. It verifies the
stored evidence hash, matched incident, three principal-attributed audit rows, and the database
append-only guard. API tests separately prove fail-closed authentication, generic rejection,
request-ID propagation, no-store responses, bounded filters/cursors, and audited not-found behavior.

## Local quality gate

- Ruff lint and formatting passed across 116 Python source, test, and migration files.
- Mypy strict mode passed across 115 Python files.
- Backend tests: 236 passed, including all real PostgreSQL and Neo4j integration proofs.
- Backend branch coverage: 97.09 percent.
- Biome and TypeScript strict checks passed.
- Web tests: 3 passed.
- The Next.js production build passed.
- Browser QA authenticated against the real API at 1280-by-720 and 390-by-844 viewports. The active
  diagnosed incident, graph selection, disabled action boundary, no-overflow responsive layout, and
  cleared end-session state were verified with no browser warnings or errors.

## Migration and container evidence

- A separate empty database upgraded through all eight migrations, downgraded Phase 8, re-upgraded
  to head, and reported no metadata drift. The temporary database was removed afterward.
- Backend and web production images built successfully and run as non-root UID 10001.
- The backend image reports version 0.8.0 and migration head `20260824_0008`, and contains both the
  diagnosis worker and one-time operator-token issuer commands.

## Private CI

- Implementation commit: `37e3f3c637d9b60e4152f2a8a0c24ae230f8e00e`.
- Private CI run: <https://github.com/RudraBhaskar9439/chakravyuh/actions/runs/32752182489>.
- Repository policy, backend, web, and production-container jobs all passed.
- GitHub reported zero open Dependabot alerts at approval time.

## Deliberate limitations

- Phase 8 is an internal inspection plane, not a general merchant dashboard.
- Static bearer hashes do not replace production workforce OIDC, short-lived sessions, role scopes,
  revocation distribution, TLS termination, or secret-manager delivery.
- “Request approval” is intentionally disabled. Phase 9 must add deterministic policy, immutable
  proposals, dual control, idempotency, and bounded Test Mode adapters before any financial action.
