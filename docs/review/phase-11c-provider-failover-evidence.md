# Phase 11C OpenRouter provider failover evidence

- Status: implementation and live synthetic probe passed
- Date: 2026-08-25
- Money mode: no payment created or mutated

## Resilience change

The diagnosis worker now owns a provider-neutral `StructuredDiagnostician` chain. Configuration
selects one primary and one optional, distinct fallback. The verified local order is OpenRouter
first and direct Gemini second. API-key presence never changes routing implicitly.

Both adapters receive the same canonical bounded evidence prompt, require the same strict
`DiagnosisDecision` JSON Schema, pass no tools, and submit no action authority. OpenRouter further
requires parameter-capable endpoints and denies provider data collection. Retryable timeout,
transport, HTTP, incomplete-response, and invalid-response failures may advance to the fallback.
Non-retryable failures stop immediately. If every provider fails, the existing bounded retry and
dead-letter workflow records `diagnosis_model_failover_exhausted`.

Tests cover primary success, retryable fallback, total exhaustion, single-provider error
preservation, non-retryable fail-closed behavior, strict request controls, malformed output,
transport failure, timeout, explicit configuration, and dependency shutdown.

## Live synthetic proof

A live call through the configured OpenRouter credential used
`google/gemini-3.5-flash-lite`. It operated on the deterministic synthetic
`authorized_not_captured` fixture, not the Razorpay payment or customer data. The response carried a
provider receipt, passed strict Pydantic validation and the deterministic citation/cause/action/
confidence guard, and produced an effective `diagnosed` disposition with no guard intervention.

Immutable input commitments from that probe:

- Prompt SHA-256: `846cdc36d2895f304d6700ab9ef41b7db04dc451e882d5fd96780730738ec06c`
- Evidence subgraph SHA-256: `c46124902c66d75c59fa42e11062d4cb15bd4cf1a882166d89f18114f0e2aefc`

No OpenRouter or Gemini key, prompt body, raw model response, provider receipt value, payment ID,
merchant ID, customer value, or card data is included in this evidence.

## Release verification

- Ruff format/lint and strict mypy passed across 153 configured source files.
- All 350 backend tests passed against isolated PostgreSQL and Neo4j with 94.20 percent branch
  coverage.
- All 7 frontend tests, Biome, TypeScript, and the optimized Next.js build passed.
- The production API image built successfully and contains both the diagnosis worker and the
  OpenRouter adapter.
- The unchanged 1,500-case deterministic judge proof retained precision, recall, and F1 of 1.0,
  zero labelled false positives or negatives, and proof SHA-256
  `aee31f9debab090bb1c2f9748629f686dabef20551cc79544772cda1c149c233`.

## Remaining external boundary

Failover removes one application-level single point of failure; it does not create unlimited model
capacity. Production still requires funded accounts, per-key budgets, provider monitoring, retained
structured logs, alerting on fallback/exhaustion, and a tested no-model operating posture. Payment
incident truth remains deterministic and continues when every model provider is unavailable.
