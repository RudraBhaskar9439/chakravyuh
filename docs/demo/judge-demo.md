# Judge demonstration

## The five-minute story

1. Open `/payments/authorize` and authorize the fixed ₹10 Razorpay Test Mode order. Show its signed,
   authoritative `authorized` and `captured=false` proof without exposing a key secret.
2. Show the resulting broken payment journey as a connected evidence mesh: merchant, journey,
   payment, order, immutable events, incident, and diagnosis.
3. Open the cited evidence and explain that deterministic invariants—not Gemini—own incident truth.
4. Create the server-derived exact-capture proposal. Show its policy hash, cap, confidence, target,
   and immutable maker identity.
5. Demonstrate that the maker cannot self-approve, then use the checker identity and execute the
   bounded Test Mode action. Show authoritative preflight, mutation checkpoint, provider receipt,
   and an idempotent second execution with no second provider mutation.
6. Run the proof command and point to exact false-positive/false-negative counts, chaos checks, policy
   denial checks, latency, throughput, and the stable SHA-256 proof.

Then show the revenue-recovery variant at `/payments/recover-failure`: create a deliberate Razorpay
Test Mode failure, verify that failed state from Razorpay, watch the deterministic incident appear,
and execute the policy-bounded action. This action creates one expiring Razorpay Payment Link. A
provider-confirmed `payment_link.paid` event—not a successful API response—closes the incident.

The first step requires a reviewed isolated environment, Test Mode credentials, a scoped operator
token, and `CHAKRAVYUH_TEST_CHECKOUT_ENABLED=true`. Keep the capability disabled everywhere else.

## Reproducible commands

The offline proof needs no credential or service:

    uv run chakravyuh-judge-demo --seed-start 50000 --seed-count 100

The signed-ingress probe must target an isolated local or staging database. Provide its secret only
through the environment and use a unique run ID:

    CHAKRAVYUH_LOAD_WEBHOOK_SECRET='isolated-target-secret' \
      uv run chakravyuh-load-probe \
      --base-url http://127.0.0.1:8000 \
      --merchant-id merchant-load-proof \
      --account-id acc-loadproof \
      --run-id judgeproof01 \
      --unique-events 500 \
      --duplicate-deliveries 100 \
      --concurrency 25

Never run a load probe against a shared or production endpoint without the service owner's explicit
authorization. The remote-target flag is an acknowledgment, not authorization.

## Questions to invite

- “What happens if the model hallucinates?” It abstains or its unsupported recommendation is denied;
  model output never owns incident truth or provider access.
- “What happens if capture times out?” The durable mutation checkpoint forces fetch-only
  reconciliation; capture is never blindly retried.
- “What happens if Payment Link creation times out?” Chakravyuh looks up the deterministic provider
  reference before doing anything else. It never issues a second blind create request.
- “How do you know duplicate/out-of-order events are safe?” The proof compares state hashes, while
  database constraints and queue generations enforce the same design under concurrency.
- “Are zero false negatives guaranteed?” No. The reported zero applies only to the labelled held-out
  synthetic set. Unknown live distributions require monitoring, merchant-specific evaluation, and
  staged rollout.
- “Is this production?” It is production-shaped and directly deployable after the external gates in
  the runbook; live money movement remains deliberately unsupported.
- “Did the repository fabricate the provider proof?” No. The immutable verification is written only
  after Checkout HMAC verification and an authoritative Razorpay payment fetch agree on order,
  amount, `authorized` status, and `captured=false`; the external run is reported separately.
