# Phase 9: deterministic policy and guarded Razorpay Test Mode actions

## Objective

Close one recovery loop without giving the model, browser, or a single operator authority to move
money. The implementation is production-shaped but deliberately limited to Razorpay Test Mode.

## Control flow

    immutable diagnosis receipt
      -> server derives action, target, evidence, exact amount, and idempotency key
      -> recovery-policy-v1: deny | allow | require_approval
      -> immutable proposal + policy decision
      -> second principal approves or rejects capture
      -> execution lease validates current incident/revision/diagnosis and TTL
      -> authoritative Razorpay payment GET
      -> durable mutation-started checkpoint
      -> exact capture POST
      -> immutable allowlisted provider receipt

AI contributes only the already guarded recommendation. It cannot supply a target, amount,
credential, endpoint, approval, policy result, HTTP body, or tool call.

## Deterministic policy v1

All action paths require the explicit kill switch, verified Test Mode credential prefix, exact
merchant scope, and cited evidence. The implemented matrix is:

| Action | Required shape | Policy outcome |
| --- | --- | --- |
| Fetch authoritative payment | Payment target, read-only risk, no amount | Allow |
| Capture payment | `authorized_not_captured`, payment target, exact positive INR amount below cap, money-movement risk, confidence threshold | Require approval |
| Replay event, create/cancel link, abstain, or unknown | No production adapter | Deny |

Policy inputs and outcomes are SHA-256 checkpointed. Configuration defaults to actions disabled,
₹10,000 maximum capture, 0.90 confidence, 15-minute proposal TTL, and a 30-second execution lease.
Changing a limit changes the policy input hash.

## Maker-checker and freshness

The proposal records its maker principal. A capture decision from that same principal is rejected.
Checker decisions are immutable and unique per proposal/principal. Any rejection terminates
execution eligibility.

Every decision and execution locks current PostgreSQL rows and verifies:

- the incident still exists and is not resolved;
- the proposal references the latest incident revision and latest diagnosis;
- the proposal has not expired;
- policy did not deny it;
- required approval came from a different principal; and
- no active execution lease or terminal failure already exists.

The idempotency key hashes the incident, revision, diagnosis, action, target, and exact amount. A
repeated proposal request returns the existing immutable record. A repeated execution after success
returns the existing receipt without another provider call.

## Provider boundary

The client is fixed to `https://api.razorpay.com`, rejects redirects, ignores ambient proxy
credentials, uses bounded timeouts and response size, validates payment IDs before path construction,
and sends Basic authentication only through the HTTP authentication object. Raw provider errors,
email, contact, notes, card data, and response bodies never enter the ledger.

The allowlisted provider state contains payment ID, status, integer amount, currency, captured flag,
and optional order ID. Capture proceeds only when the preflight object exactly matches the proposal.
An already-captured exact payment is recorded as idempotent success without POST.

## Crash and timeout semantics

`operations.action_execution_work` owns a fenced attempt number, execution ID, principal, lease,
and `mutation_attempted` bit. Claims, mutation authorizations, and results are separate immutable
records.

- Failure before mutation checkpoint: record retryable; a later claim may preflight again.
- Failure after mutation checkpoint: fetch once to reconcile.
- Exact captured state after ambiguity: success with `already_applied=true`.
- Authorized, changed, invalid, or unavailable state after ambiguity: terminal uncertain/blocked;
  never POST again.
- Expired processing lease with mutation checkpoint: the next claim is `reconcile`, not `execute`.

## Database ledgers

Phase 9 adds append-only tables for proposals, policy decisions, checker decisions, execution claims,
mutation authorizations, execution results, and action-access audit. Database triggers reject update,
delete, and truncate. Only the execution coordination row is mutable.

## Deliberate boundaries

- No live credential is accepted, even if a caller sets the kill switch.
- Capture is the only provider mutation and INR is the only capture currency in policy v1.
- Payment-link creation/cancellation and merchant replay remain denied until independently designed.
- Static bearer identities demonstrate separation of duties; workforce OIDC, roles, revocation,
  rate limiting, and deployment secret delivery remain Phase 10 controls.
- A production rollout would require Razorpay review, merchant-specific caps, staged canaries, and
  operational ownership beyond this buildathon proof.
