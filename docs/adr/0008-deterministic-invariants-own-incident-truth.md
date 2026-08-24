# ADR 0008: Let deterministic invariants own incident truth

- Status: Accepted
- Date: 2026-08-24

## Context

Payment events are delayed, duplicated, and sometimes contradictory. A rule that fires immediately
on an incomplete asynchronous transition creates expensive false positives. An LLM classifier can
add useful language understanding later, but nondeterministic output is unsuitable as the source of
truth for a financial incident and makes false negatives difficult to reproduce or audit.

Detection must also survive worker crashes. A finding may remain identical, change as stronger
evidence arrives, disappear after recovery, and recur later. Replacing the current incident row
without immutable revisions would destroy the evidence needed to explain those transitions.

## Decision

A pure, versioned invariant engine evaluates the complete PostgreSQL materialized journey and its
immutable normalized-event history. Its allowlisted rules use provider-backed fields only. Rules
with expected asynchronous delay return a future database-time deadline instead of a finding while
inside a configured grace window.

PostgreSQL owns one evaluation-work row per merchant correlation. The journey-state transaction
enqueues or advances that work through a trigger. Workers claim due rows with `FOR UPDATE SKIP
LOCKED`; one transaction appends an immutable evaluation, reconciles current incidents, appends any
lifecycle revisions, and updates the queue checkpoint.

An incident key hashes merchant, correlation, rule, and affected entity identity. Its finding hash
also includes rule version, evidence, and amount. This separates stable incident identity from
evidence changes. A missing prior finding resolves the incident; a later recurrence reopens the same
incident ID and increments its occurrence count. Identical findings update observation time without
creating redundant revisions.

Oversized histories permanently dead-letter with a stable payload-free code. Unexpected failures
roll the transaction back to pending. Evaluations and lifecycle revisions reject update, delete, and
truncate. The current incident table is intentionally mutable derived state and can be rebuilt from
those records in a later recovery tool.

The held-out synthetic benchmark is evaluation-only. It measures exact incident/entity labels,
precision, recall, F1, and an explicit per-false-positive review cost. Its zero-error result is proof
of the coded contracts on the generated cases, not a claim of zero production false negatives.

## Consequences

- Detection is reproducible, versioned, replayable, and independent of Gemini availability.
- Grace-window work remains pending at a precise deadline without polling every journey continuously.
- Multiple workers safely partition due correlations and commit an incident lifecycle atomically.
- Operators can distinguish a new detection, changed evidence, resolution, and recurrence.
- The same incident identity survives evidence changes and resolution cycles.
- AI diagnosis in Phase 7 can explain an authoritative incident but cannot invent or suppress one.
- New rules require labelled positive and adversarial negative cases plus a reviewed policy version.
- Synthetic precision and recall do not replace shadow evaluation on real, consented merchant data.
