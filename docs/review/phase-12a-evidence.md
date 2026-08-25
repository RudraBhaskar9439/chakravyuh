# Phase 12A locked benchmark contract evidence

- Status: implementation and release verification passed
- Date: 2026-08-25
- Money mode: no payment created, captured, refunded, or mutated

## Implemented boundary

The Recovery Arena v1 contract fixes three strategies, disjoint identity partitions, a 10,005-case
held-out commitment, exact INR cost units, one recoverable incident type, one executable action,
authoritative-webhook-only recovery credit, a 100-call/$1 live-model ceiling, and a bounded
100,000-delivery/concurrency-50 local load envelope.

The held-out manifest carries only the generator version, seed range, declared scale, contract hash,
and proof rules. It deliberately contains no expected, recoverable, action, or provider-outcome
label. Scope, confirmation-rule, count, visibility, overlap, and hash tampering are rejected by
executable validation.

## Stable commitments

- Contract SHA-256: `b99775ca382196d5077b01caf0a675ee56f3b173f6be7ccf607edd458e87d1a3`
- Held-out manifest SHA-256: `126b34cf79786ace693c8e0a60f24737574ed93cac804dcb27410e7507ad09a4`
- Held-out identity range: seeds 50,000 through 50,666
- Declared held-out cases: 10,005

## Release verification

- All 366 backend tests passed against isolated PostgreSQL and Neo4j with 94.26 percent branch
  coverage.
- Ruff format/lint and strict mypy passed across 156 typed source files.
- All 7 frontend tests, Biome, TypeScript, and the optimized Next.js build passed.
- Alembic reported no missing migration operations.
- The 1,500-case deterministic judge proof retained precision, recall, and F1 of 1.0, zero labelled
  false positives or false negatives, and proof SHA-256
  `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
- The production API image built as non-development version `0.12.0` and executed the packaged
  Recovery Arena contract command with the same two stable hashes.
- A redacted full-history Gitleaks scan covered 28 commits and 1.89 MB with no findings; `.env`
  remains ignored by repository policy.
