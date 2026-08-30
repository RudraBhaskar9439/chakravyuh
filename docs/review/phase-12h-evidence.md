# Phase 12H final proof-pack evidence

- Status: approved
- Date: 2026-08-30
- Bound implementation revision: `95e27f09b69c869f4da60376967f6159b5a5f36f`
- Proof root: `f1eb7fd4ca6263ca9212bd3897340bc6fefabcb06a23a09c6d2a58c3e2e1cd6f`

## Sealed artifacts

The committed `proof/phase-12` directory contains a typed JSON manifest, 10,005 canonical JSONL
case records, a three-strategy CSV, a self-contained human-readable HTML summary, and `SHA256SUMS`.
The case ledger is 29,628,207 bytes. Its SHA-256 is
`6aa4d56f428ec1e5feea8f050bb04c471c8b3a70172472338c363dba3607a3ff`.

Every case record binds its index and identity, the exact Git revision, locked contract, portfolio
and tournament roots, observed-input hash, evaluator-only oracle hash, economic label, and the
validated scored results for no intervention, retry all, and Chakravyuh. Those 10,005 record hashes
produce case Merkle root `9e2516f2dd28fbfe8d7dd9cf44c5434701b67a8ed4e490087ff04e874acbd62f`.
The manifest binds that root, all strategy metrics, and the hash and byte length of every content
artifact. The checksum file additionally binds the manifest itself.

The exact full held-out build was executed twice into independent directories with the same source
revision. `cases.jsonl`, `strategy-summary.csv`, `index.html`, `manifest.json`, and `SHA256SUMS` were
byte-identical across both runs. The verifier also passed with the expected revision and proof root
supplied as external trust anchors.

## Negative control

The executable negative-control test changes one byte of a generated case ledger. Verification then
fails because `SHA256SUMS` no longer matches. Separate tests prove refusal to overwrite an existing
pack and rejection of both a wrong code revision and a wrong trusted proof root. Four focused proof-
pack tests passed.

## Final release gates

- Ruff lint and format checks passed across 180 Python source, test, and migration files.
- Mypy strict mode passed across 179 configured source, test, and migration files.
- All 474 backend tests passed, including isolated PostgreSQL and Neo4j integration proofs.
- Backend branch coverage was 90.53 percent.
- Biome and TypeScript checks passed; all 34 frontend tests passed in 12 files.
- The production Next.js build emitted both live provider journeys, the judge workspace, Money
  Trace, verified recovery, reliability, operations, and sealed evidence routes.
- Alembic reported head `20260825_0012` and no new upgrade operations.
- The committed container manifests retain a non-root UID, read-only filesystem, dropped Linux
  capabilities, bounded resources, readiness probes, and separate worker processes.

The proof remains deterministic synthetic INR evidence. It does not convert the separate Razorpay
Test Mode payment into a live-revenue claim and it does not claim production-SLA performance.
