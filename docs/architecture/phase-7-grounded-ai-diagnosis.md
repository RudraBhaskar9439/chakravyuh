# Phase 7: bounded evidence and grounded AI diagnosis

## Objective

Explain an authoritative payment incident and recommend a bounded next step without giving the
model authority over incident truth, graph scope, or money movement.

## Processing path

    ledger.incident_revisions INSERT (except resolved)
      └── trigger advances operations.diagnosis_work

    isolated diagnosis worker
      ├── claims work using PostgreSQL database-time leases
      ├── loads the immutable incident and journey revision
      ├── reads one bounded Neo4j journey subgraph
      ├── verifies merchant, correlation, state generation, and state hash
      ├── adds deterministic invariant evidence and canonical hash
      ├── calls the explicit provider chain with strict JSON Schema and no tools
      ├── applies citation, cause, action, and confidence guards
      └── atomically appends receipt plus attempt and advances the checkpoint

Detection and diagnosis are separate processes and queues. Model-provider or Neo4j failure cannot
stop the main webhook, normalization, reduction, or invariant worker.

## Evidence boundary

The graph reader starts at one `(merchant_id, correlation_id)` journey and rejects truncation rather
than silently omitting facts. Configured defaults cap a diagnosis at 128 facts and 256 relationships.
Each edge must close over a returned fact. The assembler additionally requires the projected state
generation and SHA-256 state hash to match the immutable PostgreSQL revision.

Allowed fact fields are deliberately small:

- journey checkpoint time;
- normalized event UUID, type, and occurrence time;
- financial entity type and provider ID;
- provider and effective payment status;
- normalized amount and currency; and
- explicit graph relationship type.

Raw webhook bodies, arbitrary normalized payload dictionaries, credentials, customer contact data,
and model-generated text are excluded. Every invariant evidence item that names an event must link
to the corresponding graph event or assembly fails closed.

`subgraph_hash` commits to the complete canonical input, including incident revision, state
checkpoint, facts, relationships, and assembly time. `prompt_hash` commits to the exact canonical
prompt, allowed root causes, and allowed actions.

## Model and guard boundary

The direct Gemini adapter uses the stable v1 Interactions API with a strict `DiagnosisDecision` JSON
Schema and provider storage disabled. The OpenRouter adapter uses Chat Completions with strict JSON
Schema, parameter-capable endpoint routing, and data-collection denial. Both disable streaming,
pass no tools, enforce independent timeouts, and record the effective model and provider receipt
identifier. The prompt says that all identifiers and statuses are untrusted data and that
insufficient or contradictory evidence requires abstention.

Routing is configuration, not key-presence magic. The worker constructs the primary and optional
distinct fallback in a fixed order. Only sanitized, retryable `DiagnosisProcessingError` failures
advance to the next provider. A successful fallback receives the identical canonical prompt and
passes the identical schema and deterministic guard. A permanent failure stops immediately;
complete exhaustion becomes the stable `diagnosis_model_failover_exhausted` code.

Schema validation is necessary but not sufficient. The deterministic post-model guard rejects:

| Model proposal defect | Effective result |
| --- | --- |
| Missing, invented, or graph-only citations | Abstain: invalid citations |
| Action outside the incident allowlist | Abstain: unsupported action |
| Root cause outside the incident allowlist | Abstain: unsupported root cause |
| Confidence below the configured threshold | Abstain: low confidence |
| Explicit schema-valid model abstention | Preserve abstention |

The result is explanatory only. It does not call Razorpay, enqueue an action, alter incident status,
or bypass the future policy and approval layers.

## Lease, retry, and audit semantics

One work row per incident tracks target and applied versions. Incident revisions advance the target
without taking a lease away from an in-flight worker. Claims use `FOR UPDATE SKIP LOCKED` and
database time. Completion requires the same owner, attempt, and unexpired lease.

A resolved revision synchronously advances and completes the checkpoint while revoking any active
lease, so a stale diagnosis cannot be published after the incident disappears. A later reopen
creates a fresh pending target.

Transient graph unavailability/staleness and exhausted model-provider chains retry with a bounded
delay. Oversized evidence is a permanent failure. A newer target resets the failure counter; an
older claim cannot dead-letter the newer revision. Exhausted or permanent failures become visible
dead letters with stable payload-free codes. Structured fallback logs contain provider names and
stable codes only—never prompts, responses, keys, or raw provider errors.

After an operator verifies that the external dependency recovered, one dead-lettered diagnosis can
be requeued through `chakravyuh-diagnosis-replay`. The transition is accepted only from the
dead-letter state. An append-only record stores the operator, reason, prior stable error, exact
source revision, target version, and database time before the existing attempt sequence continues.
Concurrent or repeated replay requests fail closed.

`ledger.diagnoses`, `ledger.diagnosis_attempts`, and `ledger.diagnosis_replays` reject update,
delete, and truncate. A completed
receipt contains both the raw schema-valid model decision and the guarded effective decision, making
every abstention intervention observable.

## Deliberate boundaries

- Phase 7 does not train or fine-tune a model.
- Incident detection remains the deterministic Phase 6 invariant engine.
- The graph remains rebuildable and never becomes authoritative financial state.
- No public diagnosis endpoint or operator interface exists until Phase 8.
- No recovery proposal can execute until Phase 9 policy and approval enforcement.
- Live merchant quality, drift, privacy retention, and capacity remain deployment gates. Provider
  failover is implemented and tested, but managed production capacity is still external.
