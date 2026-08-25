# Phase 11B external Razorpay evidence

- Status: passed in an isolated Razorpay Test Mode environment
- Date: 2026-08-25
- Money mode: Test Mode only; no real funds moved

## Provider-backed lifecycle

The public HTTPS webhook route was registered in the Razorpay Test Mode Dashboard with a fresh
signature secret. The hosted Checkout then authorized one server-fixed ₹10 INR order using manual
capture. The browser callback was accepted only after Checkout HMAC verification and an
authoritative payment fetch agreed on the exact order, payment, amount, currency, `authorized`
status, and `captured=false`.

Redacted identifiers:

- payment: `pay_TTrF…MLO9`
- order: `order_TTrA…Xww`
- incident: `80554293-3adc-5188-b136-ce69e358965a`
- proposal: `714db526-a43e-482a-bc9c-ca9efe160b86`

The signed public webhook entered PostgreSQL at 2026-08-25 03:42:14 UTC. The isolated demo used a
60-second authorization grace period, compared with the production default of 900 seconds. The
deterministic engine raised `authorized_not_captured` at 03:43:13 UTC. The finding never depended
on Gemini or Neo4j availability.

## Grounded diagnosis and recovered dependency failure

The first Gemini 3.5 Flash attempts received a provider HTTP 429 after the free-tier project quota
was exhausted. Five bounded attempts produced the stable payload-free code
`diagnosis_model_unavailable` and a visible dead letter; detection and provider state were
unaffected.

The live failure exposed that diagnosis dead letters lacked a reviewed replay path. Migration
`20260825_0011` adds `ledger.diagnosis_replays`, append-only guards, a state-checked repository
transition, and `chakravyuh-diagnosis-replay`. Two operator-attributed replay records preserve the
prior error, source revision, target version, reason, and time. After verifying availability of the
supported `gemini-3.5-flash-lite` model, attempt 11 completed at 03:53:02 UTC.

The post-model guard accepted a confidence-1.00 `capture_not_completed` diagnosis with three cited
evidence facts and the incident-allowlisted `capture_payment` recommendation. Its bounded graph
contains five facts and six relationships.

## Dual control and exact recovery

Three distinct short-lived principals completed the recovery:

1. `proof-maker` created the server-derived proposal.
2. The maker's approval request was denied with HTTP 403 before repository access.
3. `proof-checker` independently approved the exact target, amount, evidence, and policy hash.
4. `proof-executor` obtained one execution lease, fetched authoritative provider state, wrote one
   mutation authorization, and sent one exact ₹10 capture request.

Razorpay returned captured state, then delivered signed `payment.captured` and `order.paid`
webhooks. The invariant engine appended the resolution at 03:55:09 UTC. PostgreSQL contains exactly
one execution claim, one mutation authorization, and one execution result for the proposal.

An immediate execution replay initially returned `stale` because the capture webhook had already
resolved the incident. The control plane was corrected so terminal success returns its immutable
receipt before current-incident freshness checks. A regression test resolves the incident before
replay, and the real proposal replay returned HTTP 200 with the original result hash and no provider
request.

## Immutable proof hashes

- Checkout verification: `ef27ac943ba796ff101689ad17815999fe2848b2936c59f0303465085598d97b`
- Authorized webhook body: `19a274ec86ad283fd46b8056ea51d7d506af0c113e4269d1cfddef31485ec3e7`
- Captured webhook body: `a37d09dd1f7de8dd4c5801034dbfb9ab024738d2e6e687a1e4ff72817eb52a72`
- Order-paid webhook body: `f43d6bd544ed0169703e2e7bd1afab1b155cbb231b3d6c9724c382bef5b5ed00`
- Incident finding: `7191996f7b9963c7c968f5cf393e108ffc0b0ece4ea70cd94f2f0b4631fce669`
- Journey state: `481457d516d6fc66bb5dd1aa58f0790695cdf65f56c4f2661ae539a401897e74`
- Diagnosis prompt: `4ae9df855f5dbd07c70df993b5c994e52441dd831bb55d409eece30c5e379ad0`
- Evidence subgraph: `9efe04cd81eea82ced4d47f295e3d92055ca74df64b26303161127e7dc0cef40`
- Action proposal: `403c4eb99cbb2ec29b54ae9627953d23518f3242c4d0c063137d641866f84c58`
- Policy input: `1f982fc56a2c3cdaf97170f1c3749d2a2618f3479d4f9110b12e8306a092c9ec`
- Execution result: `6d65099941f33c3eb5f1ac67cc30dcde7b9a432a3d93d74e77854e645fb3dcb7`

No API key, webhook secret, Checkout signature, operator token, card data, raw provider response, or
customer contact value is included in this evidence.

## Release verification

- Migration head `20260825_0011` applied cleanly and `alembic check` reported no metadata drift.
- Ruff formatting/lint and strict mypy passed across 148 configured source files.
- All 337 backend tests passed against isolated PostgreSQL and Neo4j with 94.27 percent branch
  coverage.
- All 7 web tests, Biome, TypeScript, and the optimized Next.js build passed.
- The 1,500-case deterministic judge proof passed with precision and recall 1.0, zero labelled
  false positives, zero labelled false negatives, all chaos/policy checks green, and stable proof
  SHA-256 `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
