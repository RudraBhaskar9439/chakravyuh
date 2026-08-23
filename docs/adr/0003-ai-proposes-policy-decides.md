# ADR 0003: AI proposes; deterministic policy decides

- Status: accepted
- Date: 2026-08-23

## Context

Language models can interpret ambiguous evidence but cannot provide hard guarantees about amounts, permissions, idempotency, or payment state.

## Decision

Models may emit schema-validated diagnoses and action proposals. A versioned deterministic policy engine decides whether to deny, require approval, or allow a proposal. The action executor performs a final authoritative-state check.

## Consequences

- Model failure degrades diagnosis instead of financial correctness.
- Every action has an auditable policy decision.
- Candidate actions must be enumerated and deliberately implemented.
- Evaluation must separately measure diagnosis quality and action safety.

