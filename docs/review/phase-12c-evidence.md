# Phase 12C held-out economic portfolio and baseline evidence

- Status: approved
- Date: 2026-08-25
- Provider mode: independent deterministic twins; no Razorpay or model API called
- Money mode: synthetic INR portfolio only

## Locked portfolio

- Cases: 10,005 from 667 held-out seeds and 15 balanced case families
- Merchants: 25 deterministic policies
- Synthetic payment volume: 629,606,000 subunits (₹6,296,060)
- Oracle-recoverable revenue: 16,641,000 subunits (₹166,410)
- Portfolio manifest SHA-256: `00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112`
- Observed cases root: `172634169db73579a5004564fde0bf281d3ec9233a76840230ebc6164b0fc4a8`
- Oracle cases root: `03f094697261edf808a3ef4e324c72da8d03280cf4b5016d4a992bf05fef65f6`

Every family contributes exactly 667 cases. Provider plans include 9,479 normal, 133 rejected,
143 timeout-before-mutation, 124 timeout-after-mutation, and 126 state-change outcomes. The
strategy-facing case JSON contains no family, seed, expected incident, action eligibility,
recoverability, provider plan, or oracle field.

## Counterfactual baselines

No intervention recovered ₹0 and missed all 421 recoverable cases. Naive retry all attempted 4,002
captures, produced 2,266 provider confirmations, but only 402 confirmations were legitimate
recoveries. It made 3,545 incorrect actions, recovered ₹157,280 of the ₹166,410 oracle-recoverable
amount, incurred ₹354,500 of declared incorrect-action cost, and therefore produced net recovery
value of negative ₹197,220. No case produced more than one provider mutation.

- Baseline report SHA-256: `d58a681121480d489a3e30eb4b1ca86a37cb864ef2a94ede23dc35abcf32c2c9`
- No-intervention result root: `1e53d97acb1787749aa91faa1d22f8eb617ad1d439137b2ab565cbe7b31f3cf0`
- Retry-all result root: `393b59f81d9b9c215d391f8b20e6924db0a4c03832769fd08f4e7023727eaa3d`

These figures are synthetic counterfactual evidence, not merchant revenue or a production claim.

## Release verification

- Backend: 404 tests passed with 93.79% branch coverage.
- Static analysis: Ruff passed; strict mypy passed across 163 source files.
- Frontend: 7 tests passed; Biome, TypeScript, and the optimized Next.js build passed.
- Schema safety: Alembic reported no new upgrade operations.
- Regression proof: the 1,500-case judge corpus remained at precision, recall, and F1 of 1.0,
  with proof hash `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
- Container proof: the production image executed the complete 10,005-case baseline command and
  reproduced the portfolio, observed, oracle, strategy, and report hashes above.
- Secret scan: Gitleaks scanned 30 commits and approximately 1.95 MB with no leaks found.
- Repository hygiene: `git diff --check` passed and `.env` remains ignored.
