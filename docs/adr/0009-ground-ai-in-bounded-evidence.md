# ADR 0009: Ground AI diagnosis in a bounded immutable evidence subgraph

- Status: Accepted
- Date: 2026-08-24

## Context

An LLM can explain a broken payment path and suggest the next investigation more clearly than a
large set of hand-written templates. It must not, however, become the incident detector, query an
unbounded merchant graph, receive raw webhook payloads, invent citations, or acquire execution
authority. Provider latency and malformed output must also be ordinary queue failures rather than
partial financial state changes.

Neo4j is a rebuildable projection, so a graph traversal is useful only when it matches the exact
PostgreSQL state generation and hash that produced the incident revision. A newer revision may
arrive while a slow model call is running. The system must preserve that newer target without
allowing the expired result to overwrite it.

## Decision

Every non-resolved incident revision advances one leased diagnosis work item in PostgreSQL. The
worker loads the immutable incident snapshot and matching immutable journey revision, then performs
one bounded, read-only Neo4j traversal. The traversal returns only allowlisted journey, entity,
event, status, amount, and relationship fields. Raw provider payloads are never graph or model
inputs.

The assembler rejects a foreign, stale, incomplete, open-edged, duplicate, or oversized graph. It
adds the deterministic invariant evidence and links every invariant event citation to its projected
event. Canonical JSON is hashed before the model call.

Gemini receives one data-only prompt through the stable v1 Interactions API. Storage and streaming
are disabled, no tools are declared, and JSON Schema constrains the response. A deterministic guard
then requires:

- all citations to exist in the frozen subgraph;
- at least one cited deterministic invariant fact;
- a root cause allowlisted for the incident type;
- an action allowlisted for the incident type; and
- confidence at or above the configured threshold.

Any guard failure becomes an explicit abstention. Even a valid recommendation remains a
non-executable proposal. Phase 7 contains no Razorpay mutation adapter.

The final receipt, model draft, effective guarded decision, prompt hash, subgraph hash, provider
interaction identity when supplied, attempt, and failure code are immutable PostgreSQL records. A
database-time lease fences completion. If a newer revision arrives during processing, the old
receipt may be recorded for its exact target, but the work returns to pending for the new target.
Expired workers cannot commit.

## Consequences

- Model output cannot create, suppress, resolve, or execute an incident.
- Diagnoses are reproducible back to the exact incident revision and evidence graph content.
- Model outages retry independently from detection, intake, reduction, and graph projection.
- Permanent evidence-bound failures dead-letter immediately; transient graph/model failures use a
  bounded retry budget.
- Prompt-injected identifiers remain untrusted JSON data and the provider receives no tools.
- A syntactically valid but semantically unsupported model answer is visible as an abstention.
- Real diagnosis-quality calibration still requires consented, reviewed production examples; no
  model training or production-accuracy claim is made in this phase.
