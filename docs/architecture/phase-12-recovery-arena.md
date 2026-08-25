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

## Production-code rule

Chakravyuh must use the real normalization, temporal reduction, invariant, diagnosis guard, policy,
maker-checker, execution, webhook, and resolution paths. Baselines may be smaller, but they receive
the same observed inputs and predetermined provider outcomes. No strategy reads the oracle.

## Claims boundary

Arena amounts are labelled synthetic INR portfolio values. Provider requests, action success, or AI
recommendations do not count as recovered revenue. Real-provider claims remain limited to the
separate Razorpay Test Mode evidence already recorded in Phase 11.
