# Phase 6 review checklist

## Detection authority and timing

- [x] Deterministic versioned rules are the only incident-detection authority.
- [x] Gemini, Neo4j, and external network availability cannot create or suppress an incident.
- [x] Complete current state and normalized-event history are the only rule inputs.
- [x] Expected asynchronous transitions use bounded grace windows and exact scheduled re-evaluation.
- [x] Policy thresholds participate in the evaluator version hash.
- [x] Findings contain stable identity, content hash, amount, and verifiable evidence references.

## Transactions and lifecycle

- [x] Journey-state commits enqueue invariant work in the same PostgreSQL transaction.
- [x] Concurrent workers claim non-overlapping due correlations with row locks and skip-locked.
- [x] Evaluation, incident reconciliation, revisions, and checkpoint commit atomically.
- [x] New, changed, resolved, and recurring findings produce distinct immutable revision reasons.
- [x] Identical findings do not create duplicate lifecycle revisions.
- [x] Recurrence preserves the incident ID and increments occurrence count.
- [x] Unexpected failures roll back to pending without partial audit or current state.
- [x] Oversized histories dead-letter once with a bounded payload-free error code.

## Storage and audit

- [x] Evaluations commit worker, attempt, evaluator version, state generation/hash, count, and time.
- [x] Evaluation work permits same-generation scheduled retries without weakening generation bounds.
- [x] Evaluation and incident-revision ledgers reject update, delete, and truncate.
- [x] Current incident rows enforce status/resolution, amount/currency, hash, and evidence constraints.
- [x] Migration backfills every existing journey, matches metadata, and supplies a downgrade.

## Evaluation and operational boundary

- [x] Every rule has positive evidence and adversarial negative cases.
- [x] The offline benchmark scores exact incident/entity labels, not only incident category.
- [x] Precision, recall, F1, false positives, false negatives, and manual-review cost are reported.
- [x] Evaluation cases are explicitly held-out synthetic data and are never described as production truth.
- [x] Worker logs expose only aggregate evaluation and lifecycle counts.
- [x] Configuration bounds batch size, history size, and every grace period.

## Review outcome

Covered by the owner's standing authorization of 2026-08-24. Final local, container, and private CI
evidence is recorded in `phase-6-evidence.md` before Phase 7 begins.
