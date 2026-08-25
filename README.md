# Chakravyuh

Chakravyuh is a self-healing money graph for Razorpay payment journeys. It detects missing or contradictory state transitions, assembles an evidence path, and proposes a bounded recovery action.

The project is implemented in twelve auditable phases. Phase 10 hardens the complete evidence and
action mesh with scoped operator authority, fail-closed throttling, deterministic correctness and
chaos proofs, and production deployment manifests. Phase 11 adds a separately gated Razorpay Test
Checkout that can create the exact authorized-but-uncaptured payment used in the recovery proof. AI
remains non-executable: deterministic policy, immutable maker-checker approval, exact-amount
preflight, and Test-Mode-only Razorpay adapters control every outbound operation.

The judge-facing [`/recovery-story`](http://localhost:3000/recovery-story) route presents one
completed Razorpay Test Mode recovery as a simple, read-only visual replay. It exposes the exact
evidence, model receipt, safety boundaries, and tamper-evident hashes without tokens, role switching,
or an action API. The full operator console remains available separately for engineering inspection.

Repository policy: private access only. The source and generated evaluation artifacts must not be published without the owner's explicit approval.

## Architecture principles

- PostgreSQL is the authoritative event and financial state store.
- Neo4j is a rebuildable graph projection, never the source of truth.
- Every financial action passes through deterministic policy and approval checks.
- AI produces structured diagnoses and proposals; it cannot execute tools directly.
- Raw events are append-only and derived state is replayable.
- External events are assumed to be duplicated, delayed, and out of order.

## Local prerequisites

- Python 3.12
- uv
- Node.js 24+
- pnpm 11+
- Docker with Compose

## Bootstrap

    cp .env.example .env
    make bootstrap
    make infra-up

Run the API and web application in separate terminals:

    make api
    make worker
    make projector
    make diagnosis-worker
    make web

The API liveness endpoint is http://localhost:8000/health/live. The web application is available at http://localhost:3000.

`make infra-up` waits for local dependencies and applies all database migrations. The readiness
endpoint at http://localhost:8000/health/ready returns success only when PostgreSQL answers a real
query.

## Verified webhook intake

Configure a Test Mode merchant identity, account identity, and webhook secret in `.env`, then use:

    POST /v1/webhooks/razorpay/{merchant_id}

The endpoint:

- reads a size-bounded stream rather than an unbounded request body;
- verifies `X-Razorpay-Signature` over the exact raw bytes before parsing JSON;
- requires `X-Razorpay-Event-Id` as the provider idempotency identity;
- supports the current and previous secret during safe secret rotation;
- commits the verified body to PostgreSQL before returning 2xx;
- returns `202` for a new event and `200` for an identical provider retry;
- returns `409` if one provider event ID is reused with different content.

PostgreSQL rejects row updates, deletes, and table truncation on the raw ledger. Provider events
may arrive late or out of order; ordering is not inferred at intake.

## Durable normalization worker

The worker claims pending raw events directly from PostgreSQL and emits one canonical payment,
order, refund, or payment-link event. Multiple worker replicas can run safely. Contract failures
become visible dead letters; unexpected failures roll back to pending without a partial output.

Run it locally after applying migrations:

    make worker

After deploying reviewed normalizer support, an authorized operator can replay one dead letter:

    uv run chakravyuh-replay RAW_EVENT_UUID \
      --requested-by operator@example.com \
      --reason "Reviewed normalizer support deployed"

Replay is intentionally a host/database-authorized operation rather than a public HTTP endpoint.
See [Phase 3 architecture](docs/architecture/phase-3-durable-normalization.md) for the transaction
and failure guarantees.

## Temporal payment journeys

Every committed normalized event marks its merchant correlation dirty in PostgreSQL. The same worker
then rebuilds the correlation from its complete immutable history, using event time plus stable
tie-breakers rather than arrival order. A successful reduction atomically writes:

- one replaceable current state in `state.payment_journey_states`;
- one immutable, content-hashed revision in `ledger.payment_journey_revisions`;
- one immutable attempt record; and
- the completed queue generation.

Generate an offline proof without credentials or network access:

    chakravyuh-simulate --scenario out_of_order_delivery --seed 42

The output includes delivered events, expected payment status, reduced state, and its SHA-256 hash.
Available scenarios cover success, authorization without capture, capture without order payment,
failed-then-recovered payment, partial refund, out-of-order delivery, and duplicate delivery.

After a reviewed reducer release or a corrected safety limit, an authorized operator can request a
rebuild without deleting history:

    chakravyuh-journey-replay merchant-id correlation-id \
      --requested-by operator@example.com \
      --reason "Reviewed temporal reducer release deployed"

See [Phase 4 architecture](docs/architecture/phase-4-temporal-journeys.md) for ordering, transaction,
and replay guarantees.

## Rebuildable money graph

The separate projector process leases dirty journey correlations from PostgreSQL and replaces one
complete Neo4j subgraph per managed transaction. The graph contains merchants, payment journeys,
financial entities, event evidence, and explicit provider-backed relationships. Raw webhook payloads
and secrets are never copied into Neo4j.

Run the projector alongside the main normalization/reduction worker:

    make projector

`GET /health/graph` checks both Neo4j connectivity and PostgreSQL-authoritative queue lag. It fails
closed for an unreachable graph, dead letters, or lag beyond the configured threshold. After an
operator reviews a graph-wide recovery, every journey can be re-enqueued under a new audited epoch:

    uv run chakravyuh-graph-rebuild \
      --requested-by operator@example.com \
      --reason "Reviewed Neo4j recovery and projection rebuild"

Epoch-plus-generation guards prevent an expired worker from overwriting newer graph state while
allowing PostgreSQL to remain authoritative after disaster recovery. See
[Phase 5 architecture](docs/architecture/phase-5-rebuildable-money-graph.md) for the complete
transaction, crash, and observability contract.

## Deterministic incidents

Every journey-state commit now enqueues invariant evaluation in PostgreSQL. The main worker evaluates
six conservative payment contracts at database time. It reschedules incomplete transitions to their
exact grace-window deadline instead of raising a premature incident. A completed evaluation,
current incident changes, immutable lifecycle revisions, and its queue checkpoint commit in one
transaction.

Run the evaluation-only held-out benchmark without credentials, databases, or network access:

    chakravyuh-evaluate-invariants --seed-start 10000 --seed-count 100

Each seed supplies six labelled positive faults and nine adversarial negative journeys. The JSON
result reports exact-label precision, recall, F1, false-positive and false-negative counts, and an
explicit manual-review cost. This is repeatable contract evidence on synthetic cases, not a claim of
zero false negatives on real merchant traffic.

Incident detection never calls Gemini or queries Neo4j. Evaluations and incident revisions are
append-only; stable incident IDs survive evidence changes, resolution, and recurrence. See
[Phase 6 architecture](docs/architecture/phase-6-invariants-and-incidents.md) for the rule, timing,
transaction, and audit contract.

## Grounded AI diagnosis

Every non-resolved incident revision now advances an isolated diagnosis queue. The diagnosis worker
loads the immutable PostgreSQL checkpoint, reads one bounded allowlisted Neo4j subgraph, requires an
exact generation and state-hash match, and calls the explicitly configured model-provider chain
with strict JSON Schema output, provider-specific privacy controls, and no tools. OpenRouter can be
primary with direct Gemini as an independent application-level fallback:

    CHAKRAVYUH_DIAGNOSIS_PRIMARY_PROVIDER=openrouter
    CHAKRAVYUH_DIAGNOSIS_FALLBACK_PROVIDER=gemini
    CHAKRAVYUH_OPENROUTER_API_KEY=stored-outside-git
    CHAKRAVYUH_OPENROUTER_MODEL=google/gemini-3.5-flash-lite

    make diagnosis-worker

The deterministic post-model guard requires real citations including invariant evidence, an
incident-allowlisted root cause and action, and minimum confidence. Anything unsafe or weak becomes
an explicit abstention. The model cannot create or resolve incidents and its recommendation cannot
execute. Receipts, attempts, prompt hashes, evidence hashes, retries, provider exhaustion, dead
letters, and guard interventions are immutable audit records. See
[Phase 7 architecture](docs/architecture/phase-7-grounded-ai-diagnosis.md) for the complete boundary.

After the cause of a temporary provider or graph outage is verified as recovered, an operator can
requeue exactly one dead-lettered diagnosis. The command records the operator, reason, prior stable
error, source incident revision, and target version before returning the item to the queue:

    chakravyuh-diagnosis-replay incident-uuid \
      --requested-by operator-id \
      --reason "Verified model capacity and graph health recovered"

## Operator evidence mesh

The internal operator API reads PostgreSQL incident truth and immutable diagnosis receipts through
three authenticated endpoints under `/v1/operator`: overview, bounded cursor-paginated incident
list, and incident detail. Every authorized read appends a principal-attributed access record and
returns `Cache-Control: no-store`.

Issue a high-entropy local credential:

    uv run chakravyuh-operator-token --principal local-reviewer

Store the one-time `operator_token` output in a password manager. Put only the emitted
`environment_value` JSON into `CHAKRAVYUH_OPERATOR_TOKEN_HASHES`, restart the API, open
http://localhost:3000, and paste the raw token for that browser session. The browser never writes it
to local storage, cookies, a URL, or server-rendered output.

The console renders the exact evidence mesh stored with the latest diagnosis, including its
SHA-256 hash and incident revisions. Production transport must use TLS and an exact CORS allowlist. See
[Phase 8 architecture](docs/architecture/phase-8-operator-control-plane.md) for the authentication,
pagination, audit, and interface contract.

## Guarded Test Mode recovery

Phase 9 implements only two provider actions: an authoritative payment fetch and exact-amount
capture of an `authorized` payment. All other model recommendations are recorded as policy denials.
The outbound kill switch defaults off, and application startup rejects enabled actions unless the
configured key begins with `rzp_test_`.

For a local Test Mode proof, configure two different operator principals, retain only their token
hashes in `CHAKRAVYUH_OPERATOR_TOKEN_HASHES`, and then set:

    CHAKRAVYUH_RAZORPAY_ACTIONS_ENABLED=true

A proposal is derived entirely on the server from the latest immutable diagnosis. Read-only fetch
can execute after policy approval. Capture additionally requires a decision from a principal other
than the proposal maker. Before capture, the adapter fetches current Razorpay state and verifies the
payment ID, `authorized` status, exact integer amount, and currency. It persists a mutation-started
checkpoint before the POST.

Razorpay does not provide the general payment-capture idempotency header available on its payout
APIs. Therefore, any crash or timeout after the checkpoint permits fetch-only reconciliation and
never a blind capture retry. Every proposal, policy decision, checker decision, execution claim,
mutation authorization, result, and operator access event is append-only. See
[Phase 9 architecture](docs/architecture/phase-9-guarded-test-mode-actions.md) for the complete
safety and failure contract.

## Real Razorpay Test Checkout proof

Phase 11 can create one fixed ₹10 Razorpay Test Mode order with per-order manual capture, launch the
official hosted Checkout, and verify its signed success response against authoritative provider
state. The capability has its own `test-checkout:operate` scope and kill switch, stores neither the
Checkout signature nor raw provider bodies, and writes immutable order and verification hashes.

After applying migrations and issuing an operator token with the Test Checkout scope, enable the
capability only in an isolated local or staging environment:

    CHAKRAVYUH_TEST_CHECKOUT_ENABLED=true

Open `http://localhost:3000/demo-checkout`, paste the scoped token, and authorize the displayed ₹10
Test Mode order using Razorpay's documented test credentials. Do not manually capture the payment.
The screen proves the exact provider order, authorized payment, amount, uncaptured state, and
verification hash. The public HTTPS webhook and final provider-backed incident-to-recovery run have
also been completed and are recorded without provider secrets or customer data in the external
evidence review.

See [Phase 11 architecture](docs/architecture/phase-11-real-test-checkout.md) for the complete
boundary, [Phase 11 checklist](docs/review/phase-11-checklist.md) for the passed gates, and
[external evidence](docs/review/phase-11b-external-evidence.md) for the provider-backed run.

## Recovery Arena

Phase 12 measures batch recovery rather than extrapolating from one successful payment. Its locked
v1 contract compares no intervention, retry all, and Chakravyuh over a 10,005-case held-out
portfolio. It fixes an exact INR cost model, limits live model usage to 100 calls and $1, bounds the
signed-ingress probe at 100,000 deliveries with concurrency 50, and credits synthetic revenue only
after an authoritative `payment.captured` webhook.

Print the canonical contract and held-out commitment without credentials, a database, or network:

    chakravyuh-recovery-arena-contract

Run the full 10,005-case held-out portfolio against no-intervention and naive retry-all baselines:

    chakravyuh-recovery-arena-baselines

Run the reproducible three-way tournament through Chakravyuh's reducer, detector, policy,
maker-checker, execution checkpoint, provider twin, and confirmation scoring:

    chakravyuh-recovery-arena-tournament

Prepare the stratified 100-case live-AI evidence-mesh sample without making a network call:

    chakravyuh-recovery-arena-live-ai

Live execution is resumable, uses OpenRouter only, cannot move money, and requires both the API key
and an explicit acknowledgement of the locked one-dollar ceiling:

    chakravyuh-recovery-arena-live-ai --execute-live --acknowledge-max-cost-usd 1.00

On the locked portfolio, Chakravyuh detects all 4,002 expected incident types, selects all 457
eligible captures with zero incorrect actions, and produces 402 provider-confirmed recoveries. It
matches retry-all's ₹157,280 recovered value while retaining ₹148,140 after explicit review cost;
retry all falls to negative ₹197,220 after 3,545 incorrect actions. These are deterministic
synthetic INR measurements, not merchant revenue claims.

The held-out manifest exposes its seed range and generator version but contains no oracle outcome or
recoverability label. Only `authorized_not_captured` is recoverable in v1 and only exact capture is
executable; every other incident must stop, deny, or escalate. See
[Phase 12 architecture](docs/architecture/phase-12-recovery-arena.md) and
[ADR 0014](docs/adr/0014-held-out-counterfactual-recovery-arena.md). The separate live-AI sample
completed 100 calls for a conservatively accounted $0.127755, with 99 accepted provider responses,
one guard intervention, and zero unsafe effective decisions; see
[Phase 12E evidence](docs/review/phase-12e-evidence.md). The full local pipeline proof then accepted
100,000 unique signed events plus 10,000 confirmed redeliveries and converged to 1,000 PostgreSQL and
Neo4j journeys with zero dead letters, retries, lease losses, or incidents; see
[Phase 12F evidence](docs/review/phase-12f-evidence.md).

Start the web app and open `http://localhost:3000/judge` for the read-only Recovery Arena evidence
room. It keeps held-out synthetic results, live-AI measurements, the real Razorpay Test Mode proof,
and local scale results visibly separate. Its tournament, recovery funnel, connected evidence mesh,
chaos, and honest exception views expose proof hashes but import no execution client and offer no
money-action control. See [Phase 12G evidence](docs/review/phase-12g-evidence.md).

Build the final machine- and human-readable proof pack against an exact full Git revision, then
verify both that revision and the printed root:

    uv run chakravyuh-recovery-proof-pack build \
      --output-dir proof/phase-12 \
      --code-revision e52178e43c9de457f403b12fe1a714373385675a
    uv run chakravyuh-recovery-proof-pack verify \
      --input-dir proof/phase-12 \
      --expected-code-revision e52178e43c9de457f403b12fe1a714373385675a \
      --expected-proof-root 8ddaeee4d689d91810a89ed0c1d53cfb3b93ab630171ef6a3e02ee3da240bc53

Generation refuses to overwrite an existing directory. The verifier checks the outer checksum
file, typed manifest, every canonical JSONL record and embedded result hash, the per-case Merkle
root, and optional external trust anchors. The committed `proof/phase-12` directory can be checked
with `make proof-pack-verify` and contains no credential, customer, or live-provider payload.
Exact artifact commitments and final release gates are recorded in
[Phase 12H evidence](docs/review/phase-12h-evidence.md).

## Production hardening and proof

Operator identities now receive explicit scopes for incident reads, proposal creation, checker
decisions, execution requests, and metric scrapes. Local/test environments retain a bounded
in-process limiter for development; production refuses configured operator tokens unless every
principal has explicit scopes and the cluster-wide Redis limiter is selected. Limiter failure denies
authentication.

Run the complete offline judge proof without credentials or services:

    uv run chakravyuh-judge-demo --seed-start 50000 --seed-count 100

It reports held-out exact-label precision/recall and false-positive/false-negative counts, duplicate
and out-of-order state-hash checks, recovery-policy safety checks, local latency/throughput, and a
stable proof SHA-256. This is evidence on labelled synthetic cases, not a guarantee about unseen
merchant traffic.

For an authorized isolated environment, `chakravyuh-load-probe` sends bounded signed webhook events
and proves both durable new-event acknowledgements and duplicate retries. The secret is accepted only
through `CHAKRAVYUH_LOAD_WEBHOOK_SECRET`; remote targets require an explicit acknowledgment flag.
The Phase 12 scale form groups events into bounded journeys and uses idempotent transport retries:

    chakravyuh-load-probe \
      --base-url http://127.0.0.1:8000 \
      --merchant-id merchant_test \
      --account-id acc_test \
      --run-id scale01 \
      --unique-events 100000 \
      --journey-count 1000 \
      --duplicate-deliveries 10000 \
      --concurrency 50

After that report passes, an explicitly isolated and migrated PostgreSQL/Neo4j environment can be
drained through all four production workers:

    chakravyuh-pipeline-scale-proof \
      --merchant-id merchant_test \
      --run-id scale01 \
      --expected-events 100000 \
      --expected-journeys 1000 \
      --ingress-report ingress.json \
      --acknowledge-isolated-database

Never point the drain command at production. It rejects production configuration but still requires
an operator to supply a disposable, isolated database because it consumes all pending work in that
database.
See the [judge demo](docs/demo/judge-demo.md) for the exact flow.

Authenticated Prometheus metrics are available at `GET /internal/metrics` to a principal holding only
`metrics:read`. Labels contain registered route templates, method, and status—never merchant or
payment identifiers.

The Kubernetes release template under `deploy/kubernetes` separates migration, API, processors, and
web workloads, commits no Secret, and enforces non-root/read-only containers, probes, resources,
disruption budgets, and default-deny networking. It deliberately contains placeholder origins and
external dependency addresses. Follow the
[production runbook](docs/operations/production-runbook.md) and replace image tags with registry
digests before applying it. See
[Phase 10 architecture](docs/architecture/phase-10-production-hardening.md) for the complete control
and evidence contract.

## Quality gate

    make check

The gate runs Python linting, formatting, strict type checking, tests with branch coverage, web linting, web tests, and a production web build.

PostgreSQL and Neo4j integration proofs run when `CHAKRAVYUH_TEST_POSTGRES_DSN` and
`CHAKRAVYUH_TEST_NEO4J_URI` are defined. CI always runs them against isolated services.

## Migrations

    make migrate
    make migration-check

Application startup never edits the schema implicitly. A release must apply the reviewed Alembic
migrations before starting the API and worker processes.

## Repository boundaries

    src/chakravyuh/domain          Pure domain contracts and invariants
    src/chakravyuh/application     Use cases and ports
    src/chakravyuh/infrastructure  Database, graph, queue, and provider adapters
    src/chakravyuh/api             HTTP transport
    src/chakravyuh/worker          Asynchronous process entrypoint
    src/chakravyuh/projector_worker Neo4j projection process entrypoint
    src/chakravyuh/diagnosis_worker Evidence-grounded model diagnosis process entrypoint
    apps/web                       Operator interface
    docs                           Architecture decisions and review evidence

Synced material under sources/ is reference-only and is not used or modified by the application.
