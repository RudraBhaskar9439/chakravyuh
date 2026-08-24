# Phase 9 verification evidence

- Status: release gate in progress
- Date: 2026-08-24

## Implemented safety case

Phase 9 closes one bounded recovery loop. A guarded diagnosis may lead to an immutable server-derived
proposal, but deterministic policy owns eligibility. Capture is restricted to exact-amount Razorpay
Test Mode and requires a second principal. Provider ambiguity is reconciled by read-only fetch after
a durable mutation checkpoint; capture is never blindly retried.

## Official contract basis

- Razorpay Test Mode uses separate credentials and no real money:
  <https://razorpay.com/docs/payments/dashboard/test-live-modes/>
- Payment fetch contract: <https://razorpay.com/docs/api/payments/fetch-with-id/>
- Capture changes only `authorized` to `captured` and requires the exact order amount:
  <https://razorpay.com/docs/api/payments/capture/>
- Razorpay documents idempotency support for payout/composite APIs rather than payment capture:
  <https://razorpay.com/docs/api/x/payout-idempotency/make-request/>

## Local quality gate

- Ruff formatting and lint passed across 126 Python source, test, and migration files.
- Mypy strict mode passed across 75 application source files and the configured test/migration set.
- Backend tests: 272 passed, including the real PostgreSQL and Neo4j integration proofs.
- Backend branch coverage: 94.49 percent.
- Biome and TypeScript strict checks passed.
- Web tests: 4 passed, including the maker-checker execution receipt state.
- The Next.js production build passed.
- Browser QA authenticated against the real local API at 1440-by-1000 and 390-by-844 viewports.
  It verified the successful exact-capture receipt, five-node evidence mesh, no horizontal overflow,
  no browser warnings/errors, and 44-pixel mobile safety controls. The gate found and corrected a
  clipped mobile control row before the final pass.

## Real service evidence

The PostgreSQL-and-Neo4j proof creates an authorized payment journey, detects the late-capture
incident, assembles and checkpoints its evidence graph, and stores a guarded capture recommendation.
It then proves server-derived proposal creation, deterministic `require_approval`, maker self-approval
denial, distinct-checker approval, authoritative preflight, mutation checkpoint, exact capture,
immutable provider receipt, and idempotent repeated execution with no second provider call.

The same proof verifies append-only database triggers by attempting to tamper with the proposal and
delete the result. Both operations are rejected by PostgreSQL.

A configured Razorpay Test credential was checked against the real payment collection endpoint with
a read-only bounded request. Authentication succeeded, the account returned an empty collection,
and no provider mutation or fabricated payment was attempted.

## Migration and container evidence

- A separate empty database upgraded through all nine migrations, downgraded Phase 9, re-upgraded
  to head, and reported no metadata drift. The temporary database was removed afterward.
- Backend and web production images built successfully and run as non-root UID/GID 10001.
- The backend image reports version 0.9.0 and migration head `20260824_0009`; the web image runs on
  Node.js 24.
- The local `.env` remains ignored, and exact configured Razorpay and Gemini credential values were
  confirmed absent from every tracked file.

## Private CI

Pending implementation commit and private CI completion.

## Deliberate limitations

- The external contract test uses a deterministic in-process Razorpay transport; a configured
  credential smoke check is read-only and does not fabricate an authorized payment.
- Static bearer tokens and two distinct principals demonstrate maker-checker semantics but do not
  replace workforce OIDC and permission scopes.
- Live money movement, non-INR capture, payment links, automated replay, and refunds remain denied.
