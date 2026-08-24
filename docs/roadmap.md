# Review-gated implementation roadmap

Every phase must leave the repository deployable and produce executable evidence. The owner granted
standing authorization on 2026-08-24 to complete and push the remaining phases sequentially without
an approval pause. Each phase still receives a separate review record and release commit. Later
phases may extend an earlier schema only through a migration.

| Phase | Production slice | Status |
| --- | --- | --- |
| 1 | Architecture, domain invariants, process and container foundation | Approved |
| 2 | Authenticated Razorpay webhook intake and immutable PostgreSQL ledger | Approved |
| 3 | Durable normalization worker, replay, and dead-letter handling | Approved |
| 4 | Deterministic temporal payment-state reducer and synthetic journey generator | Approved |
| 5 | Rebuildable Neo4j projection and projection-lag observability | Approved |
| 6 | Invariant engine, incident lifecycle, and labelled fault-injection evaluation set | In progress |
| 7 | Evidence-subgraph assembly and schema-constrained AI diagnosis with abstention | Not started |
| 8 | Operator graph, incident explanation, and approval interface | Not started |
| 9 | Deterministic policy engine and bounded Test Mode recovery adapters | Not started |
| 10 | Load, chaos, security, evaluation, deployment, and judge-demo hardening | Not started |

No model training is required before Phase 7. The detection source of truth remains deterministic;
the model will explain evidence and propose an allowlisted action, not decide whether money moves.
