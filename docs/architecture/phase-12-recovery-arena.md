# Phase 12: Recovery Arena

## Objective

Measure confirmed revenue recovery over a locked held-out batch while exposing false actions,
manual-review cost, model cost, stopping behavior, exceptions, and the immutable evidence path for
every result.

## Evidence pyramid

1. A local deterministic provider twin runs 10,005 held-out journeys through no-intervention,
   retry-all, and Chakravyuh strategies.
2. A signed-ingress probe delivers up to 100,000 mixed and duplicate webhook requests through the
   real HTTP boundary.
3. A stratified 100-case sample calls the configured OpenRouter/Gemini chain under a hard one-dollar
   cost ceiling.
4. The completed real Razorpay Test Mode recovery anchors provider semantics without claiming that
   synthetic portfolio money was real.

## Locked v1 boundary

- Development seeds: `0..39999`.
- Validation seeds: `40000..49999`.
- Held-out seeds: `50000..50666`, producing 10,005 cases at 15 cases per seed.
- Strategies: no intervention, retry all, and Chakravyuh.
- Recoverable incident: authorization left uncaptured.
- Executable action: exact INR capture.
- Recovery confirmation: authoritative `payment.captured` webhook only.
- Live-model calls: at most 100 and at most 1,000,000 micro-USD ($1).
- Signed deliveries: at most 100,000 with concurrency at most 50.

The contract and held-out manifest are canonical JSON commitments with SHA-256 digests. The manifest
contains no expected outcome or recoverability field. Later slices add a private evaluator-only
oracle, provider twin, economic outcomes, tournament runner, dashboard, and per-case proof tree
without weakening this contract.

## Deterministic provider twin

The in-process Razorpay-shaped twin implements the same narrow fetch/capture gateway protocol as the
real Test Mode adapter. An evaluator-owned plan fixes initial state, one optional capture fault,
fault attempt, state-change outcome, duplicate confirmation count, identities, and time before a
strategy runs. Independent twin instances created from the same plan have identical hashes and do
not share state.

The strategy receives a three-method gateway view only: fetch, capture, and close. It cannot request
the plan, mutation ledger, snapshot, pending webhooks, or oracle. The evaluator retains those
surfaces and atomically drains provider-shaped `payment.captured` events into later pipeline stages.

Every fetch and capture appends a content-hashed operation receipt with before/after state hashes,
outcome, mutation bit, and deterministic identity. The twin serializes concurrent calls and applies
at most one capture mutation. It supports permanent rejection, timeout before mutation, timeout
after mutation, and a predetermined non-recovery state change during capture. A timeout after
mutation emits confirmation and lets the real control plane reconcile through fetch without a
second mutation.

## Held-out economic portfolio and baselines

The original 15-case fault family is independently re-keyed for every seed so 10,005 cases can
coexist without payment, order, event, or correlation collisions. Strategy-facing identities are
opaque; scenario name, seed, expected incident, action eligibility, recoverability, provider fault,
and oracle hash exist only in the evaluator envelope. Each observed case carries exact repriced INR
events and a content-hashed merchant capture policy across 25 deterministic merchants.

Observed-case and oracle-case hashes form separate Merkle-style roots. The manifest reports family,
fault, merchant, volume, and oracle-recoverable aggregates while binding every leaf. This separates
reproducibility from oracle visibility.

Two baselines run against independent twins created from the same per-case plan. No intervention
makes no call. Retry all fetches the latest observed payment and attempts exact capture whenever it
is uncaptured, ignoring incident truth, grace windows, merchant policy, and action eligibility. The
evaluator counts a recovery only when the case is oracle-recoverable and at least one unique
`payment.captured` confirmation exists; any attempted action outside eligibility incurs the locked
incorrect-action cost.

## Guarded Chakravyuh tournament

Chakravyuh receives the same observed case and narrow provider gateway as the baselines. It reduces
the complete temporal journey, evaluates production invariants at the locked case time, and permits
only one exact `authorized_not_captured` finding to enter recovery. A server-derived proposal then
passes through the production deterministic policy and `RecoveryActionControlPlane`.

The arena action repository implements the same repository protocol and state transitions as the
PostgreSQL action store: immutable seed load, idempotent proposal, policy decision, independent
checker decision, execution claim and lease, mutation checkpoint, terminal result, and idempotent
repeat. It is deliberately isolated from operational tables so 10,005 synthetic cases cannot pollute
merchant evidence. Every transition enters a per-case SHA-256 hash chain; all case audit roots then
form a tournament commitment. Phase 12F separately proves the complete signed HTTP, PostgreSQL,
Neo4j, and worker path under load.

Provider errors remain visible. A timeout after mutation is reconciled by authoritative fetch and
receives credit only when the twin emits `payment.captured`. A timeout before mutation becomes an
uncertain exception because the mutation checkpoint forbids blind retry. The evaluator therefore
separates detector false negatives, eligible-action misses, and provider-failure misses.

The locked result recovers the same ₹157,280 as retry all, but with 457 exact actions instead of
4,002 attempts, zero incorrect actions instead of 3,545, and positive ₹148,140 net value after
₹9,140 of explicit checker cost. Incident-type precision, recall, and F1 are each 1.0 over 4,002
positive cases; exact executable targeting is 457 of 457. These are synthetic held-out measurements,
not production merchant claims.

## Budgeted live-AI evidence-mesh evaluation

The live-model slice is isolated from recovery execution. A deterministic stratifier chooses 100
observed incidents across all six invariant types before any request is sent. Each request contains
only a bounded connected evidence subgraph and incident-specific cause/action allowlists; it never
contains the evaluator oracle. The provider receives no action gateway or Razorpay credential.

The run contract binds the sample and model, limits output to 512 tokens, caps route prices, allows
at most 100 calls and $1 total, and requires at least 90 accepted provider responses. A conservative
pre-call reservation makes the local cost stop safe even when a failed response has no usage
record. Accepted responses use provider-reported metered cost. Each result is fsynced to an ignored
secret-free checkpoint so an interrupted or repeated command cannot duplicate completed calls.

Strict provider JSON schema is only the first gate. The production deterministic diagnosis guard
then verifies exact graph citations, requires an invariant citation, applies per-incident cause and
action allowlists, and enforces the confidence floor. Failed validation becomes abstention, never an
action. Provider usage receipts and their canonical hashes are supported by the append-only
diagnosis ledger.

The completed run accepted 99 of 100 provider responses, converted one weak citation into a guarded
abstention, and exposed zero unsafe effective decisions. Total conservatively accounted cost was
$0.127755. Exact commitments and limitations are recorded in
[Phase 12E evidence](../review/phase-12e-evidence.md).

## Production-code rule

The complete Phase 12 proof must use the real normalization, temporal reduction, invariant,
diagnosis guard, policy, maker-checker, execution, webhook, and resolution paths. Phase 12D proves
the production reducer-through-execution slice against an isolated repository implementation;
Phase 12F adds signed HTTP intake, PostgreSQL, Neo4j, and workers. Baselines may be smaller, but they
receive the same observed inputs and predetermined provider outcomes. No strategy reads the oracle.

## Claims boundary

Arena amounts are labelled synthetic INR portfolio values. Provider requests, action success, or AI
recommendations do not count as recovered revenue. Real-provider claims remain limited to the
separate Razorpay Test Mode evidence already recorded in Phase 11.
