# Phase 12F full-pipeline scale and chaos evidence

- Status: approved
- Date: 2026-08-25
- Execution host: Apple silicon MacBook Pro
- Environment: isolated local PostgreSQL 17 and Neo4j 5.26; no live Razorpay mutation

## Locked execution boundary

The proof started from an empty, migrated PostgreSQL database and an empty Neo4j database. It used
one local API process and the production webhook verifier, immutable event store, normalization
worker, temporal journey reducer, invariant evaluator, and Neo4j projector. The workload was fixed
at 100,000 unique signed events, 10,000 deliberate redeliveries, 1,000 invoice-correlated journeys,
and concurrency 50.

The API readiness check now fails if the minimum immutable-ledger schema has not been migrated. The
scale command rejects production, requires an explicit isolated-database acknowledgement, bounds
events at 100,000 and timeout at four hours, and refuses a failed or mismatched ingress report.
Merchant and account identifiers are represented only by SHA-256 digests in both reports.

## Signed HTTP ingress

All 110,000 logical deliveries crossed the real HTTP endpoint with independently computed Razorpay
HMAC signatures. One response was lost at the transport boundary. The bounded client repeated the
same event ID and body, received the duplicate acknowledgement, and proved the first attempt was
durable without inserting a second row.

| Metric | Result |
| --- | ---: |
| Unique signed events | 100,000 / 100,000 |
| Deliberate redeliveries | 10,000 / 10,000 confirmed duplicate |
| Logical deliveries / physical attempts | 110,000 / 110,001 |
| Transport failures / recovered / unrecovered | 1 / 1 / 0 |
| Final HTTP statuses | 100,000 `202`; 10,000 `200` |
| Ledger cardinality after redelivery | 100,000 |
| Median / p95 request latency | 153.06 ms / 718.59 ms |
| Logical deliveries per second | 212.45 |
| Ingress report SHA-256 | `abd03fab3f2869db03875515dcc541f8b440b9041090f415edef488d920abd48` |

The report was parsed again through its frozen Pydantic contract after the run. Its canonical hash,
pass flag, exact counts, identifier digests, and retry accounting all validated.

## Complete worker and graph drain

The four stages ran sequentially so their durable counts and stage timings were attributable. Each
stage drained until an empty claim and the final gate compared every PostgreSQL and Neo4j count to
the locked contract.

| Stage | Completed | Batches including empty claim | Time | Dead letters / retries / lease loss |
| --- | ---: | ---: | ---: | ---: |
| Normalization | 100,000 | 201 | 169.04 s | 0 / 0 / 0 |
| Journey reduction | 1,000 | 3 | 6.52 s | 0 / 0 / 0 |
| Invariant evaluation | 1,000 | 3 | 3.80 s | 0 / 0 / 0 |
| Graph projection | 1,000 | 11 | 101.21 s | 0 / 0 / 0 |

PostgreSQL ended with exactly 100,000 raw events, 100,000 normalized events, 1,000 journey states
whose `event_count` sum was 100,000, 1,000 invariant evaluations, and zero incidents. All four work
tables and all 1,000 graph attempts were `completed`. Neo4j ended with one merchant, 1,000 journeys,
100,000 financial entities, and 100,000 money events.

- Drain time: 280.80 seconds.
- Drain throughput: 356.13 events per second.
- Ingress-to-graph median / p95: 772,293.91 ms / 810,067.05 ms.
- Pipeline report SHA-256:
  `d390a1625bd2de6fbdab6b45315b6563c2f527a303d97214ebc26b08bfe52915`.
- Gate result: passed.

End-to-end latency deliberately includes queue time while all 110,000 HTTP deliveries completed
before the sequential drain began. It is an honest single-process local observation, not a
production SLA or a horizontally scaled capacity claim.

## Chaos and financial-safety gates

Nine focused adversarial tests passed in 11.97 seconds against isolated real PostgreSQL and Neo4j
where relevant:

1. Concurrent redelivery inserted one immutable webhook event.
2. Reordered delivery produced the same canonical journey hash.
3. A late event rebuilt the full journey without state regression.
4. An oversized journey dead-lettered and recovered only through audited replay.
5. Repeating a graph commit before its checkpoint produced no duplicate graph mutation.
6. Projection failure dead-lettered, appeared in lag, and recovered through audited rebuild.
7. Crash recovery after a claimed action reconciled provider state and never posted again.
8. A timeout after one provider mutation reconciled to success with exactly one mutation.
9. Total diagnosis-provider outage failed closed.

The independently rerun 10,005-case tournament also passed with zero Chakravyuh incorrect actions,
zero duplicate mutations, 457/457 correct eligible actions, and 402/402 recoveries backed by
provider-shaped confirmation webhooks. Its report hash was
`b4086ba1516fbbe2b590b112ca4e43aa3ea291e1cfdeb103cf37b72edc712812`.

## Claims boundary

The 100,000-event run proves local correctness, bounded throughput, exact deduplication, durable
drain, graph convergence, and recovery safety under the tested faults. It does not establish a
Razorpay production SLA, real merchant incident prevalence, or real recovered revenue. Live
provider semantics remain anchored separately by the ₹10 Razorpay Test Mode proof in Phase 11.

## Release verification

- Backend: 437 tests passed with 90.88% branch coverage, including real PostgreSQL and Neo4j.
- Static analysis: Ruff passed with 174 files formatted; strict mypy passed across 173 source files.
- Frontend: Biome checked 19 files, 7 tests passed across 3 files, and the optimized Next.js build
  completed.
- Schema safety: Alembic reported `20260825_0012 (head)` and no new upgrade operations.
- Container proof: the production image ran as UID 10001, contained both scale commands, and exposed
  the expected migration head.
- Secret scan: Gitleaks scanned 33 commits and approximately 2.14 MB with no leaks found.
