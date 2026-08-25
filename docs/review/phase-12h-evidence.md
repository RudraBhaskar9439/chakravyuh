# Phase 12H final proof-pack evidence

- Status: approved
- Date: 2026-08-25
- Bound implementation revision: `e52178e43c9de457f403b12fe1a714373385675a`
- Proof root: `8ddaeee4d689d91810a89ed0c1d53cfb3b93ab630171ef6a3e02ee3da240bc53`

## Sealed artifacts

The committed `proof/phase-12` directory contains a typed JSON manifest, 10,005 canonical JSONL
case records, a three-strategy CSV, a self-contained human-readable HTML summary, and `SHA256SUMS`.
The case ledger is 29,628,207 bytes. Its SHA-256 is
`160d5efe56d21edc20be6a57a8e65ba5bfecd375250ca9258bb42792664f2c69`.

Every case record binds its index and identity, the exact Git revision, locked contract, portfolio
and tournament roots, observed-input hash, evaluator-only oracle hash, economic label, and the
validated scored results for no intervention, retry all, and Chakravyuh. Those 10,005 record hashes
produce case Merkle root `afa6cfd2ef0fa84633f36be7cfbc0b9d0b6834a30a8f24c78763b053e4fed2a5`.
The manifest binds that root, all strategy metrics, and the hash and byte length of every content
artifact. The checksum file additionally binds the manifest itself.

The exact full held-out build was executed twice into independent directories with the same source
revision. `cases.jsonl`, `strategy-summary.csv`, `index.html`, `manifest.json`, and `SHA256SUMS` were
byte-identical across both runs. The verifier also passed inside the non-root production backend
container with the expected revision and proof root supplied as external trust anchors.

## Negative control

The executable negative-control test changes one byte of a generated case ledger. Verification then
fails because `SHA256SUMS` no longer matches. Separate tests prove refusal to overwrite an existing
pack and rejection of both a wrong code revision and a wrong trusted proof root. Four focused proof-
pack tests passed.

## Final release gates

- Ruff lint and format checks passed across 176 Python source, test, and migration files.
- Mypy strict mode passed across 175 configured source, test, and migration files.
- All 441 backend tests passed, including isolated PostgreSQL and Neo4j integration proofs.
- Backend branch coverage was 90.62 percent.
- Biome and TypeScript checks passed; all 9 frontend tests passed in 4 files.
- The production Next.js build emitted `/`, `/demo-checkout`, and `/judge`; `/judge` is static.
- Alembic reported head `20260825_0012` and no new upgrade operations.
- Backend and web production images built and ran as UID 10001. The backend image contained the
  proof command and verified the committed pack from a read-only mount.
- The Python and production JavaScript dependency audits reported no known vulnerabilities.
- Gitleaks scanned all 36 committed revisions without a finding, then independently scanned the
  complete 29.64 MB proof directory without a finding.

The proof remains deterministic synthetic INR evidence. It does not convert the separate Razorpay
Test Mode payment into a live-revenue claim and it does not claim production-SLA performance.
