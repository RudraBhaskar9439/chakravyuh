# Threat model

## Protected assets

The highest-value assets are Razorpay credentials, webhook secrets, raw provider events, canonical
financial state, incident and diagnosis history, operator credentials, approval records, mutation
checkpoints, and provider receipts. PostgreSQL is authoritative; Neo4j and the UI are derived views.

## Trust boundaries and controls

| Boundary | Primary threats | Enforced controls |
| --- | --- | --- |
| Razorpay webhook to API | Forgery, replay, oversized body, event-ID collision | Exact-byte HMAC, bounded stream, durable idempotency identity, collision rejection |
| API to PostgreSQL | Partial commits, tampering, stale work | Transactions, leases/generations, append-only triggers, migrations outside startup |
| PostgreSQL to Neo4j | Projection drift, stale overwrite | Rebuildable projection, epoch/generation fencing, lag health |
| Neo4j/model diagnosis | Prompt injection, unsupported claim, stale evidence, provider outage | Allowlist, bounded subgraph, strict schema, no tools, citation guard, abstention, explicit failover |
| Browser/operator API | Token theft, excessive privilege, cache leakage, brute force | In-memory session only, hashed tokens, scopes, no-store, trusted host/CORS, rate limits |
| Recovery action to Razorpay | Wrong target/amount, single-person action, crash retry | Deterministic policy, maker-checker, preflight, exact amount, mutation checkpoint, no blind retry |
| Runtime platform | Root breakout, lateral movement, secret committed in Git | Non-root/read-only workloads, dropped capabilities, seccomp, default-deny network, external Secret |

## Explicit non-claims

This repository cannot prove operator-device security, cluster security, managed-service backups,
real-merchant recall, internet-scale capacity, workforce lifecycle, pager response, or Razorpay
approval for a live rollout. The production runbook makes those external gates mandatory. A failed
model response cannot move money, and a failed reliability gate cannot be presented as a pass.
