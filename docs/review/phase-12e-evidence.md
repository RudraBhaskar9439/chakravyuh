# Phase 12E budgeted live-AI evidence

- Status: approved
- Date: 2026-08-25
- Provider: OpenRouter
- Effective model: `google/gemini-3.5-flash-lite`
- Money movement: disabled; diagnosis proposals only

## Precommitted boundary

Before the first provider call, Chakravyuh deterministically selected 100 incidents from the locked
10,005-case held-out portfolio. Selection used observed invariant findings only: it stratified by
the six incident types and ordered candidates by a versioned SHA-256 rule. Oracle labels,
recoverability, provider fault plans, and expected actions were not present in any model input.

- Held-out portfolio manifest:
  `00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112`
- Live-AI sample manifest:
  `7ac31b4b8ca9a5512153bc3bdf7f5e9cc787e7271ddc766d69f0b189f5fe7954`
- Evidence-subgraph root:
  `cdb4c5dd62bcb1b527646ebd0e07d8f101ad0510d51cdacaaacdaf45d89043c4`
- Canonical-prompt root:
  `a31396b46521b9fa4a42d0d99a6ad5dd0c69a455ae17cd80c1d21d04ce4c5985`
- Live run contract:
  `0c9720202652c48cf7b2493cd262110b09f22166b55396d0a313d80a1a28c558`
- Sample distribution: 17 each for captured/order mismatch, authorized/not captured,
  failed/no recovery, and stale recovery; 16 each for duplicate links and event-order corruption.

The run contract fixed 100 calls, 512 output tokens per call, provider route price ceilings of
$0.50 per million prompt tokens and $3.00 per million completion tokens, a $1 total ceiling, and a
minimum 90 successful provider responses. Execution required the separate
`--execute-live --acknowledge-max-cost-usd 1.00` flags. The default command only prints the sample
and run commitments and cannot call a model.

## Evidence mesh and trust boundary

Every request contained one connected, bounded evidence subgraph assembled from the synthetic
journey checkpoint: financial entities, normalized events, graph relationships, and the exact
deterministic invariant finding. The prompt treated identifiers and statuses as untrusted data,
constrained root causes and recommended actions to incident-specific allowlists, and required exact
evidence IDs. The model returned a strict JSON-schema proposal. It had no gateway, database, action
repository, Razorpay credential, or execution capability.

After schema validation, a deterministic guard independently checked citations, required an
invariant citation, enforced the cause and action allowlists, and applied the confidence floor. Any
failure became an explicit abstention. This makes model usefulness measurable without placing the
financial safety boundary inside the model.

## Live result

| Metric | Result |
| --- | ---: |
| Precommitted cases attempted | 100 / 100 |
| Provider responses accepted | 99 |
| Stable provider failures | 1 invalid structured response |
| Model diagnoses / explicit abstentions | 98 / 1 |
| Effective diagnoses / abstentions after guard | 97 / 2 |
| Deterministic guard interventions | 1 invalid-invariant-citation stop |
| Valid citation sets | 99 / 99 accepted responses |
| Accepted responses citing an invariant | 98 / 99 |
| Unsafe effective decisions | 0 |
| Prompt / completion tokens | 251,136 / 19,453 |
| Provider-reported cost | $0.124016 |
| Pre-call reservations for all 100 cases | $0.450340 |
| Conservatively accounted cost | $0.127755 |
| Responses exceeding their reservation | 0 |
| Locked cost ceiling | $1.000000 |
| Median / p95 provider round-trip | 1,471 ms / 2,260 ms |

The one invalid structured response carried no usable provider usage receipt, so the cost ledger
charged its full pre-call reservation instead of assuming it was free. Successful calls used the
provider's reported metered cost. The sum remained 87.2% below the ceiling. All 100 results were
fsynced one at a time to an ignored, secret-free JSONL checkpoint; replaying the command made zero
new calls and reproduced the same report byte for byte.

- Result Merkle root:
  `a41c6b3c93d2a083bafffc276e07a6eb998e17fbdcc5ff9e95eb4fd517f10f67`
- Final report:
  `7b91feec4b8ba77baf03c6f21f5a0f14462b977aa090fbf5705fdabc70e7c0d8`
- Gate result: passed

Latency is a measurement of this single local run and provider conditions, not a production SLA.
The synthetic diagnosis result does not claim real merchant accuracy or recovered revenue.

## Provider controls

The adapter follows OpenRouter's documented response usage accounting, including provider-reported
cost; uses strict JSON-schema structured output; and requests providers that support required
parameters while denying data collection and applying maximum route prices:

- [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)

Provider usage receipts are canonical-hashed and can be persisted in the append-only PostgreSQL
diagnosis ledger. The migration remains backward compatible: historical and non-metered provider
receipts may keep the field null.

## Release verification

- Backend: 423 tests passed with 91.92% branch coverage against isolated PostgreSQL and Neo4j.
- Static analysis: Ruff passed with 172 files formatted; strict mypy passed across 171 source files.
- Frontend: 7 tests passed across 3 files; Biome checked 19 files; TypeScript and the optimized
  Next.js build passed.
- Schema safety: the usage-ledger migration applied successfully and Alembic reported no new
  upgrade operations.
- Regression proof: the 1,500-case judge corpus remained at precision, recall, and F1 of 1.0, with
  proof hash `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.
- Container proof: the non-root production image reproduced the sample and run-contract hashes in
  prepare-only mode without credentials or network calls.
- Secret scan: Gitleaks scanned 33 commits and approximately 2.14 MB with no leaks found. The live
  checkpoint remains under ignored `.data/` and is not committed.
