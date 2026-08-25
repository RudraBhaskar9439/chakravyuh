# ADR 0014: recovery claims require a locked counterfactual arena

- Status: accepted
- Date: 2026-08-25

## Context

One successful Test Mode capture proves provider integration but does not measure batch recovery.
A benchmark built after viewing its results can leak labels, reward the system for issuing requests
instead of recovering money, or compare strategies against different provider behavior. Sending a
large synthetic load to Razorpay would test the external provider rather than Chakravyuh.

## Decision

Phase 12 uses a versioned Recovery Arena contract committed before portfolio generation. It fixes
three strategies, disjoint development/validation/held-out seed ranges, exact INR cost units,
100 live-model calls, a one-dollar model-cost ceiling, 100,000 webhook deliveries, and local-machine
concurrency at 50.

The v1 recovery scope is intentionally narrow: only `authorized_not_captured` is recoverable and
only exact `capture_payment` may execute. All other incident types test abstention, denial, or
escalation. Synthetic revenue is credited only after an authoritative `payment.captured` webhook;
an AI recommendation, approval, outbound request, HTTP success, or action receipt is insufficient.

The held-out manifest exposes the generator version and seed identity range but no oracle label.
Strategies receive only observed case state. The evaluator owns predetermined provider outcomes and
runs every strategy against an independent clone of the same case.

## Consequences

- Batch recovery can be compared with no-intervention and retry-all baselines without favourable
  outcome selection.
- The 10,005-case arena and 100,000-delivery probe remain bounded for a 16 GB local machine.
- Model unavailability or budget exhaustion cannot stop deterministic detection and policy.
- Results are explicitly synthetic; the separate completed Razorpay Test Mode journey remains the
  real-provider anchor.
- Expanding beyond capture requires a new contract version, provider adapter, policy matrix, held-out
  labels, and evidence rather than a configuration toggle.
