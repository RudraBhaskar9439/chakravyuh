# Phase 4: deterministic temporal payment journeys

## Objective

Materialize one replayable payment-journey state from duplicated, delayed, and out-of-order normalized
events without allowing delivery order or an AI model to decide financial truth.

## Commit path

    normalized event insert
      └── trigger increments operations.journey_reduction_work generation

    worker transaction
      ├── SELECT dirty correlations FOR UPDATE SKIP LOCKED
      ├── read complete ledger.normalized_events correlation history
      ├── deterministic versioned reducer
      ├── UPSERT state.payment_journey_states
      ├── INSERT ledger.payment_journey_revisions (immutable)
      ├── INSERT ledger.journey_reduction_attempts (immutable)
      └── mark claimed generation completed

The work-row lock serializes a single correlation while allowing unrelated journeys to reduce in
parallel. A normalized event committed during reduction cannot disappear: its trigger waits for the
lock and then advances the generation, leaving the correlation pending for another pass.

## Temporal semantics

The reducer first deduplicates identical internal event identities, rejects conflicting reuse of one
identity, and verifies all inputs belong to one merchant correlation. It then uses this total order:

1. provider event occurrence time;
2. local verified observation time;
3. event type;
4. provider event identity; and
5. deterministic normalized event UUID.

This ordering is independent of the list or database arrival order supplied to the reducer. Unknown
future provider statuses remain visible with no guessed effective status. Missing optional fields are
merged from earlier snapshots; malformed optional amounts or references are ignored rather than
invented. Processed refund entities contribute to a payment's derived partial/full refund status.

## State and graph-ready edges

The provider-neutral state contains stable entity references, provider and effective payment status,
exact integer-subunit money, first/last occurrence times, latest event identity, and event counts. It
also emits only relationships backed by explicit identifiers:

- payment to Razorpay order;
- refund to payment; and
- payment link to Razorpay order.

The current state is replaceable because it can be rebuilt. Revisions, attempts, and replay requests
are database-enforced append-only evidence. Each revision stores a canonical SHA-256 state hash and
the reducer version that produced it.

## Failure and rebuild boundary

An unexpected code or database failure rolls the entire batch transaction back, leaving work pending
with no attempt, revision, or partial current state. A correlation exceeding
`CHAKRAVYUH_JOURNEY_MAX_EVENTS` receives stable code `journey_too_large` and no new state. An operator
can use the host-authorized `chakravyuh-journey-replay` command after reviewing a reducer or limit
change. Completed journeys can also be rebuilt at a new generation for reproducibility checks.

## Synthetic evidence

`chakravyuh-simulate` is offline and cannot write PostgreSQL or call Razorpay. A seed deterministically
controls identities. Named scenarios carry an expected payment status and emit both delivery events
and reduced state, enabling repeatable tests now and labelled invariant evaluation in Phase 6.

## Deliberate boundaries

- PostgreSQL is authoritative; no Neo4j write exists until Phase 5.
- No incident is opened until the Phase 6 invariant engine.
- No model call, outbound Razorpay request, or money movement exists.
- Live retention, encryption, least-privilege roles, and queue-age alerting remain deployment work.
