# Phase 9 review checklist

## Policy and authority

- [x] Model output remains non-executable and all request fields are server-derived.
- [x] Unsupported action types deny by default with stable reason codes.
- [x] Live keys are rejected when the action kill switch is enabled.
- [x] Merchant, incident type, target type, risk, exact amount, currency, cap, evidence, and confidence are checked.
- [x] Capture requires an immutable approval from a principal distinct from the maker.
- [x] Rejection, expiry, stale revision/diagnosis, resolution, and terminal execution fail closed.

## Idempotency and provider safety

- [x] Economic action identity has a canonical SHA-256 idempotency key.
- [x] Repeated proposal requests return the original immutable proposal.
- [x] Repeated successful execution returns the stored receipt without provider I/O.
- [x] Preflight verifies authoritative payment ID, status, exact integer amount, and currency.
- [x] Mutation intent is durable before the capture POST.
- [x] Timeout/crash after mutation can reconcile by GET only and cannot blindly retry POST.
- [x] Raw provider errors, credentials, and non-allowlisted response fields are never persisted.

## Durability and interface

- [x] Proposals, policy decisions, approvals, claims, mutation authorizations, results, and access audits are append-only.
- [x] Execution work uses fenced IDs, attempt numbers, leases, and a mutation-attempted bit.
- [x] Operator action responses and reads use authenticated no-store requests without cookies.
- [x] UI exposes policy version, exact amount/target, maker-checker step, terminal state, and result hash.
- [x] Uncertain results are explicit terminal states rather than false success.

## Operational proof

- [x] Official Razorpay Test/Live, payment fetch, capture, and idempotency documentation informed the adapter.
- [x] Unit tests cover policy denial matrix, HTTP sanitization, path validation, exact capture, timeout reconciliation, and no-blind-retry behavior.
- [x] Real PostgreSQL and Neo4j proof covers diagnosis through maker-checker capture receipt and idempotent replay.
- [x] Real database proof rejects proposal tampering and execution-result deletion.
- [x] Migration upgrades to head and matches SQLAlchemy metadata.
- [ ] Full local quality gate, production containers, private CI, and dependency audit are recorded.

## Review outcome

The local quality, service, migration, container, secret, and responsive-browser gates passed. Final
approval awaits the private GitHub CI run and dependency audit under the owner's standing
authorization of 2026-08-24.
