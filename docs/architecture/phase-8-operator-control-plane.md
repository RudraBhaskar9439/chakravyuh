# Phase 8: audited operator evidence mesh

## Objective

Give a payment operator one production-shaped place to understand a detected money-path break while
preserving the system's deterministic source of truth and zero-execution boundary.

## Read path

    browser session-memory bearer token
      └── authenticated internal operator API
            ├── overview: incident counts, amount at risk, diagnosis queue health
            ├── list: status filter plus bounded opaque cursor
            └── detail: incident lifecycle, revisions, latest immutable diagnosis receipt
                  └── same transaction appends ledger.operator_read_audit

The detail path reads the evidence subgraph stored in `ledger.diagnoses`. It does not query Neo4j or
rerun Gemini. The interface therefore shows the exact facts, relationships, prompt-bound graph
hash, model draft, effective guarded result, and lifecycle revision that existed at diagnosis time.

## Authentication and secret boundary

`CHAKRAVYUH_OPERATOR_TOKEN_HASHES` is a JSON object from stable principal IDs to lowercase SHA-256
token hashes. The service starts with operator access disabled when this map is empty. Authentication
hashes the presented bearer credential and performs constant-time comparisons against every
configured hash before returning the matched principal.

The credential issuer uses 32 random bytes and emits the raw token once with its configuration hash:

    uv run chakravyuh-operator-token --principal local-reviewer

The raw token belongs in a password manager. Only the emitted `environment_value` belongs in
`CHAKRAVYUH_OPERATOR_TOKEN_HASHES`. The web application stores the token in memory only, never in a
cookie, local storage, session storage, URL, or server-rendered document. It uses
`credentials: omit`, sends `Cache-Control: no-store` requests, and clears all sensitive state when
the operator ends the session. Production deployment requires TLS and an exact CORS allowlist.

## Bounded query and audit semantics

The incident list accepts only known status enums, limits a page to 100 rows, and orders by
`last_detected_at DESC, incident_id DESC`. Its URL-safe cursor contains only that ordered boundary;
malformed, oversized, naive-time, and structurally unexpected cursors fail as one generic client
error.

Authorized overview, list, detail, and not-found detail reads append one database record containing:

- the authenticated principal ID and propagated request ID;
- an allowlisted read action;
- resource type and resource ID when present;
- success or not-found outcome; and
- bounded query-result metadata without bearer tokens, raw webhook bodies, or diagnosis content.

The audit insert and the corresponding read share one transaction. Database triggers reject update,
delete, and truncate, matching the other financial audit ledgers.

## Interface contract

The operator console has four explicit layers:

1. queue health and amount-at-risk overview;
2. current incident selection with provider entity and status;
3. guarded diagnosis and a disabled policy-gated recommendation; and
4. the exact evidence mesh plus append-only incident lifecycle.

The evidence mesh uses a deterministic four-column layout for invariant, journey, entity, and event
facts. Relationships are rendered from the immutable receipt, selectable fact chips show the source
description, and the stored SHA-256 subgraph hash remains visible. No force layout, generative graph
completion, or browser-side evidence inference can change the picture.

## Failure behavior

- Unconfigured auth fails closed without touching the read model.
- Invalid credentials disclose no principal or configuration detail.
- Invalid filters and cursors produce bounded generic errors.
- A missing incident is audited as not found before the API returns `404`.
- PostgreSQL failure prevents both the result and its audit from committing.
- The browser exposes a stable error state and never retries a financial mutation because none exists.

## Deliberate boundaries

- There is no HTTP mutation route in Phase 8.
- “Request approval” is disabled until Phase 9 policy, idempotency, and dual-control records exist.
- The static bearer scheme is suitable for a private buildathon deployment boundary, not the final
  workforce identity design; OIDC, expiry, revocation distribution, and role scopes remain Phase 10.
- Evidence and provider identifiers require a defined retention and privacy policy before live data.
