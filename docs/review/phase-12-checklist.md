# Phase 12 Recovery Arena review checklist

## 12A: locked benchmark contract

- [x] Three canonical counterfactual strategies are fixed before evaluation.
- [x] Development, validation, and held-out seed ranges are disjoint.
- [x] The held-out commitment declares 10,005 cases without exposing oracle labels.
- [x] Only authorization left uncaptured is recoverable in v1.
- [x] Only exact capture is executable in v1.
- [x] Revenue requires authoritative `payment.captured` webhook confirmation.
- [x] Live-model and local-machine resource ceilings are encoded and validated.
- [x] Contract and manifest tampering fail executable validation.

## 12B: deterministic provider twin

- [x] Independent strategy clones receive identical predetermined provider behavior.
- [x] Provider fetch, capture, confirmation webhook, and mutation ledger are deterministic.
- [x] Before/after-mutation timeout and state-change faults are supported.
- [x] Oracle state is not present in the strategy input contract.

## 12C: held-out economic portfolio and baselines

- [x] The exact held-out portfolio root commits all 10,005 case hashes.
- [x] Amounts, merchant policies, case families, and chaos outcomes are reported.
- [x] No-intervention and retry-all baselines produce independently scored results.

## 12D: Chakravyuh tournament

- [x] The recovery strategy traverses the production-shaped control plane.
- [x] Every strategy starts from an independent clone of the same case.
- [x] Revenue, false-action, review, provider, and exception metrics are honest; end-to-end latency
  remains explicitly assigned to the full-pipeline Phase 12F gate.

## 12E: budgeted live AI

- [x] A stratified 100-case held-out sample is selected before model execution.
- [x] Exact provider-reported token and cost usage is recorded.
- [x] Cache, resume, call-count, and dollar stop rules prevent unbounded spend.
- [x] Citation, root-cause, action, abstention, and guard metrics are reported.

## 12F: full-pipeline scale and chaos

- [x] Up to 100,000 bounded signed deliveries traverse the real HTTP intake.
- [x] Pipeline drain, p50/p95 latency, throughput, duplicates, and dead letters are reported.
- [x] Crash-after-checkpoint, duplicate/out-of-order, replay, and provider outage gates pass.
- [x] Zero duplicate mutation, policy violation, and unconfirmed recovery gates pass.

## 12G: judge dashboard

- [x] Tournament, funnel, evidence mesh, chaos, and exception views are available.
- [x] Synthetic and real-provider evidence are visibly separated.
- [x] Judge controls cannot reach real Razorpay mutations.

## 12H: final proof pack

- [ ] JSON, JSONL, CSV, HTML, and SHA-256 artifacts are reproducible.
- [ ] Per-case hashes bind to a root proof and the code revision.
- [ ] An intentional negative control makes the proof gate fail.
- [ ] Full backend, frontend, migration, container, security, and secret gates pass.
