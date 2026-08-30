# ADR 0015: merchant-scoped authority precedes production rollout

- Status: accepted
- Date: 2026-08-30

## Context

The public buildathon deployment is an isolated Razorpay Test Mode environment. Its server-held
maker, checker, and executor credentials make the judge journey usable without exposing operator
tokens, but they are not a production workforce identity system. A real deployment must prevent an
operator, replay job, event, graph node, proposal, or receipt from crossing merchant boundaries.

## Decision

PostgreSQL remains the authorization boundary. Every financial record and action is addressed by
`merchant_id`; provider targets and amounts are derived again from immutable merchant-scoped
diagnosis evidence before execution. Browser-supplied merchant IDs, amounts, provider keys, and
roles are never trusted.

The production identity adapter will accept short-lived OIDC sessions from the operator's identity
provider and map immutable subject IDs to merchant-scoped roles. Maker, checker, and executor remain
separate permissions. The checker must be a different subject from the maker. Service identities
receive narrower worker scopes and cannot open browser sessions. Authorization denials and reads
remain auditable.

The buildathon deployment deliberately retains its isolated, server-side Test Mode principals. It
must not be relabelled as production authentication, connected to live credentials, or shared
between merchants.

## Required production gates

1. Select an identity provider and verify issuer, audience, signature, expiry, and nonce.
2. Add a reviewed `(subject_id, merchant_id, role)` membership store and deny by default.
3. Apply PostgreSQL row-level security or an equivalent transaction-scoped tenant guard.
4. Prove cross-merchant reads, proposals, approvals, replays, and executions fail in integration
   tests.
5. Rotate service credentials through a managed secret store and rehearse revocation.

## Consequences

The current public site is safe for its stated Test Mode scope and frictionless for judges. It is
also explicit about the remaining external identity and tenant-isolation work, avoiding the false
claim that a demonstration token model is suitable for live merchant operations.
