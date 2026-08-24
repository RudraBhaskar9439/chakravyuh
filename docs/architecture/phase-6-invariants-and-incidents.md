# Phase 6: deterministic invariants and durable incidents

## Objective

Turn replayable payment journeys into conservative, explainable incident truth without allowing an
AI model, Neo4j availability, or a worker crash to decide whether a merchant has lost money.

## Commit path

PostgreSQL remains authoritative. Neo4j is not queried during detection.

    payment_journey_states INSERT or UPDATE
      └── trigger advances operations.invariant_evaluation_work

    main worker, after reduction
      ├── claims due correlations with FOR UPDATE SKIP LOCKED
      ├── loads current state and complete normalized-event evidence
      ├── evaluates versioned pure rules at database time
      ├── appends ledger.invariant_evaluations
      ├── reconciles state.incidents
      ├── appends lifecycle changes to ledger.incident_revisions
      └── completes or precisely reschedules the work row

The evaluation and lifecycle reconciliation share one PostgreSQL transaction. A crash cannot leave
an incident without its evaluation, a revision without its current state, or a completed checkpoint
without both.

## Rules and false-positive controls

Version `payment-invariants-v1` detects six narrow contracts:

| Rule | Required evidence | False-positive control |
| --- | --- | --- |
| Captured payment with order not paid | Captured payment and its explicit `order_id` | Five-minute grace; paid order suppresses it |
| Authorization not captured | Payment remains authorized | Fifteen-minute capture window |
| Failed payment without recovery | Failed payment and no later captured payment in the correlation | Thirty-minute recovery window |
| Recovery link active after success | Paid order and explicit active link reference | Five-minute link-shutdown window |
| Duplicate active recovery links | At least two active links for the same explicit order | Stable sorted group identity |
| Terminal event regression | A later created, authorized, or failed event after capture for one payment | Event-time ordering plus stable tie-breakers |

All windows are bounded environment settings and participate in the evaluator version hash. While a
deadline is in the future, the engine emits no incident and schedules one exact re-evaluation. A
captured, refunded, or partially refunded payment counts as successful where appropriate. Recovery
requires a later capture, preventing an unrelated earlier success from hiding a failure.

Evidence contains normalized entity IDs and event UUIDs only. Raw webhook bodies, arbitrary payloads,
credentials, and model-generated statements are absent from incidents and revisions.

## Incident identity and lifecycle

`incident_key` is a SHA-256 hash of merchant, correlation, rule, and affected entity. A UUIDv5 derived
from that key is the durable incident ID. `finding_hash` additionally commits to rule version,
evidence, type, and amount at risk.

| Observation | Current-state result | Immutable revision |
| --- | --- | --- |
| New key | Detected, occurrence 1 | `detected` |
| Same key and same finding hash | Last-seen/checkpoint refresh | None |
| Same key with changed evidence | Existing status retained | `updated` |
| Active key absent from complete result | Resolved with timestamp | `resolved` |
| Resolved key appears again | Detected, same ID, occurrence +1 | `reopened` |

Evaluations record evaluator version, state generation and hash, worker, attempt, result count,
deadline, and database timestamp. Oversized histories dead-letter once with a stable code and no
partial incident. Unexpected exceptions roll back the entire claimed batch transaction.

## Held-out proof set

`chakravyuh-evaluate-invariants` builds evaluation-only cases from seed identities that are not used
to configure the rules. Every seed produces six positive faults and nine adversarial negatives,
including within-grace transitions, success, recovery, partial refund, duplicate delivery,
out-of-order delivery, a single valid recovery link, and an inactive post-success link.

The command scores exact `(incident type, affected entity type, affected entity ID)` labels. It emits
machine-readable precision, recall, F1, false-positive and false-negative counts, and a transparent
INR 20 manual-review assumption for every false positive. This proves deterministic behavior on the
specified contracts; production calibration still requires consented shadow traffic and reviewed
labels.

## Deliberate boundaries

- No model is trained or called in this phase.
- No diagnosis, action proposal, public incident API, approval, or Razorpay mutation exists yet.
- The worker logs aggregate lifecycle counts, never merchant identifiers or evidence payloads.
- Rule additions are code and policy changes requiring review, migration-compatible output, and
  fresh positive and negative evaluation cases.
- Alert delivery, retention, incident rebuild tooling, and real-traffic shadow calibration remain
  deployment and Phase 10 responsibilities.
