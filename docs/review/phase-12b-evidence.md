# Phase 12B deterministic provider twin evidence

- Status: implementation and release verification passed
- Date: 2026-08-25
- Provider mode: deterministic local twin; no Razorpay or model API called
- Money mode: synthetic INR state only; no payment created or mutated

## Implemented boundary

The provider twin implements the production payment gateway fetch/capture/close protocol behind a
strategy-visible view that exposes no plan, snapshot, pending webhook, mutation ledger, or oracle.
Evaluator-owned plans and every operation receipt are canonical SHA-256 commitments. Independent
twins created from the same plan produce identical state and evidence without sharing mutable state.

The twin validates exact payment identity, exact integer INR amount, authorized precondition,
single-mutation behavior, and deterministic confirmation generation. It supports capture rejection,
timeout before mutation, timeout after mutation, state change during capture, duplicated
confirmation delivery, closed-provider failure, invalid identity/amount, and concurrent requests.

A contract test passes the twin through the real `RecoveryActionControlPlane`: timeout after the
mutation creates one provider mutation and one confirmation event, then the control plane fetches
the captured state and completes as reconciled success without posting again.

## Release verification

- All 387 backend tests passed against isolated PostgreSQL and Neo4j with 94.31 percent branch
  coverage.
- Twenty direct provider-twin tests and the real-control-plane reconciliation test passed without
  network or credentials.
- Ruff format/lint and strict mypy passed across 158 typed source files.
- All 7 frontend tests, Biome, TypeScript, and the optimized Next.js build passed unchanged.
- Alembic reported no missing migration operations.
- The 1,500-case deterministic judge proof retained precision, recall, and F1 of 1.0, zero labelled
  false positives or false negatives, and proof SHA-256
  `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
- The production API image built successfully and imported the packaged deterministic twin.
- A redacted full-history Gitleaks scan covered 29 commits and 1.91 MB with no findings.
