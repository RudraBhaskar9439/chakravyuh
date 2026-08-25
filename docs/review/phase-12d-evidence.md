# Phase 12D guarded Chakravyuh tournament evidence

- Status: approved
- Date: 2026-08-25
- Provider mode: one independent deterministic Razorpay twin per case and strategy
- Money mode: synthetic INR only; no Razorpay or model API called

## Locked held-out result

All three strategies ran over the same 10,005 evaluator envelopes committed by portfolio manifest
`00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112`. A strategy received only
the opaque observed case, normalized event history, merchant policy, and narrow provider gateway.
Oracle incident labels, action eligibility, recoverability, and provider fault plans remained on the
evaluator side.

| Metric | No intervention | Retry all | Chakravyuh |
| --- | ---: | ---: | ---: |
| Action attempts | 0 | 4,002 | 457 |
| Correct actions | 0 | 457 | 457 |
| Incorrect actions | 0 | 3,545 | 0 |
| Action precision | n/a | 11.42% | 100% |
| Eligible-action recall | 0% | 100% | 100% |
| Confirmed recoveries | 0 | 402 | 402 |
| Confirmed recovered value | ₹0 | ₹157,280 | ₹157,280 |
| Manual-review cost | ₹0 | ₹0 | ₹9,140 |
| Incorrect-action cost | ₹0 | ₹354,500 | ₹0 |
| Net recovery value | ₹0 | -₹197,220 | ₹148,140 |
| Duplicate provider mutations | 0 | 0 | 0 |

Chakravyuh detected 4,002 expected incident types with 0 incident-type false positives and 0
incident-type false negatives: precision, recall, and F1 are each 1.0. Executable payment targeting
is measured separately and was exact for all 457 eligible captures. Incident metrics intentionally
score business-incident identity per case; when two duplicate recovery links are equivalent, the
metric does not pretend that choosing one equivalent link identity is a financial error.

## Guarded control path

The strategy uses the production temporal reducer, deterministic invariant evaluator, recovery
policy, proposal builder, maker-checker service, execution lease, mutation checkpoint, exact-amount
preflight, ambiguity reconciliation, and provider gateway contract. Its arena repository is an
isolated deterministic implementation of the production repository protocol. It mirrors the
PostgreSQL state machine and emits a hash-chained audit trace without writing benchmark cases into
operator or merchant tables. Full HTTP, PostgreSQL, Neo4j, and worker-path load evidence remains a
separate Phase 12F gate.

- 667 capture incidents produced server-derived proposals.
- Merchant kill switches and exact amount ceilings denied 210 proposals before review.
- 457 independent checker reviews approved exactly the 457 oracle-eligible actions.
- Maker, checker, and executor are three distinct principals.
- 3,162 control transitions were content hashed across executed and policy-denied cases.
- 949 provider operations produced 402 applied mutations and 402 unique confirmations.
- 39 executions stopped on an authoritative-state mismatch and 16 on provider rejection.
- 19 otherwise recoverable cases stopped after timeout-before-mutation ambiguity. They are counted
  as missed recovery, not hidden as success. The detector still found each incident; the control
  plane refused a blind second capture after its durable mutation checkpoint.
- Live model calls and model cost were both zero. Deterministic financial safety does not depend on
  model availability; the budgeted diagnosis experiment is isolated in Phase 12E.

## Reproducibility commitments

- Locked baseline report:
  `d58a681121480d489a3e30eb4b1ca86a37cb864ef2a94ede23dc35abcf32c2c9`
- Chakravyuh per-case result root:
  `c6ed181f90b61951f96ca70f1ed6616606367c8b32ebff459cd4ae53b61651dc`
- Chakravyuh control-audit root:
  `14011ba6fdbd8ae141479e08f529eaa4b0d0efcf8761da188528a53d27f8203b`
- Three-way tournament report:
  `b4086ba1516fbbe2b590b112ca4e43aa3ea291e1cfdeb103cf37b72edc712812`

These are deterministic synthetic counterfactual measurements, not merchant revenue, live-system
latency, or a guarantee of real-world incident precision.

## Release verification

- Backend: 411 tests passed with 93.17% branch coverage against isolated PostgreSQL and Neo4j.
- Static analysis: Ruff passed with 168 files formatted; strict mypy passed across 167 source files.
- Frontend: 7 tests passed across 3 files; Biome checked 19 files; TypeScript and the optimized
  Next.js build passed.
- Schema safety: Alembic reported no new upgrade operations.
- Regression proof: the 1,500-case judge corpus remained at precision, recall, and F1 of 1.0,
  with proof hash `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
- Container proof: the non-root production image executed the complete three-way 10,005-case
  tournament and reproduced every baseline, portfolio, audit, result, and report hash above.
- Secret scan: Gitleaks scanned 32 commits and approximately 2.07 MB with no leaks found.
- Repository hygiene: `git diff --check` passed and `.env` remains ignored.
