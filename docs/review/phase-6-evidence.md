# Phase 6 verification evidence

- Status: approved under standing owner authorization
- Date: 2026-08-24

## Quality gate

The complete local gate passed against real PostgreSQL and Neo4j:

- Ruff lint and formatting passed across 92 Python source, test, and migration files.
- Mypy strict mode passed across 91 Python files.
- Backend tests: 181 passed, including every PostgreSQL and Neo4j integration proof.
- Backend branch coverage: 98.87 percent.
- Biome and TypeScript strict checking passed.
- Web tests: 2 passed.
- The Next.js production build passed.

## Deterministic rule evidence

The evaluator covers six explicitly bounded contracts: captured payment with order not paid,
authorization not captured, failure without a later recovery, stale recovery link after payment,
duplicate active recovery links, and a terminal-state event regression. Unit proofs confirm:

- grace windows emit no premature finding and return the exact future deadline;
- successful, recovered, refunded, out-of-order, and duplicate-delivery journeys remain negative;
- every positive finding has a stable incident key, content-sensitive finding hash, amount, and
  provider-backed evidence references;
- reversing delivery order does not alter duplicate-link identity or evidence hash; and
- changing any reviewed grace threshold changes the evaluator version.

The offline release benchmark evaluated seeds 10000 through 10099. It generated 1,500 exact-label
cases: 600 positive fault cases and 900 adversarial negatives. Version
`payment-invariants-v1-8d124f62b8be` reported 600 true positives, zero false positives, zero false
negatives, precision 1.0, recall 1.0, F1 1.0, and zero INR-subunit review cost. These are held-out
synthetic contract results, not a claim of zero error on production merchant traffic.

## Real PostgreSQL evidence

Eight Phase 6 integration tests prove:

- a within-grace authorization completes one evaluation, leaves the same generation scheduled, and
  creates no incident;
- detection, evidence-changing update, resolution, and recurrence append the four correct revisions;
- recurrence preserves the incident UUID and increments occurrence count;
- an identical finding refreshes current state without appending a redundant revision;
- three concurrent workers partition six correlations without duplicate incident creation;
- a bounded history overflow appends one stable dead-letter evaluation and no incident;
- an unexpected evaluator failure rolls back work, evaluation, revision, and current state; and
- evaluation and incident-revision ledgers reject update, delete, and truncate.

The repository implementation reached 100 percent statement and branch coverage in the full gate.
Integration fixtures now remove their replaceable state and operational queue rows after each test,
so repeated local runs cannot contaminate graph-rebuild eligibility. Immutable audit rows remain.

## Migration and container evidence

- The working database upgraded to revision `20260824_0006` and matched SQLAlchemy metadata with no
  generated operations.
- A separately created empty database upgraded through all six revisions, downgraded Phase 6,
  re-upgraded to head, and reported no schema drift. The isolated database was removed afterward.
- Both production images built successfully.
- The backend image ran as non-root UID 10001, reported application version 0.6.0 and migration head
  `20260824_0006`, and contained the worker, projector, and invariant-evaluation commands.
- The evaluator ran inside the production backend image and returned perfect exact-label metrics for
  its one-seed smoke set without credentials, database access, or network access.

## Private CI

Implementation commit `8d8c334bafeb993c4452b4dcd1c0e2f8f37cab49` passed private GitHub Actions
run [`32746621370`](https://github.com/RudraBhaskar9439/chakravyuh/actions/runs/32746621370).
The run passed the private-repository policy, fresh PostgreSQL and Neo4j migrations, schema-drift
check, lint, formatting, strict typing, all tests, frontend gates, both production image builds,
non-root execution, installed-command checks, and the in-container invariant benchmark. GitHub
reported zero open Dependabot alerts after the run.

## Deliberate limitations

- The synthetic benchmark demonstrates specified behavior and reproducibility; real-world false
  negatives require consented shadow traffic, reviewed labels, and population-drift monitoring.
- Phase 6 does not call Gemini. Phase 7 may explain evidence and propose a schema-constrained action,
  but it cannot create, suppress, resolve, or execute an incident.
- No public incident API, operator graph, approval interface, or outbound Razorpay mutation exists yet.
- Alert delivery, audit retention, incident reconstruction, deployment supervision, and production
  capacity thresholds remain later hardening work.
