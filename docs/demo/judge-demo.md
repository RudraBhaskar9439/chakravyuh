# Judge demonstration

## The five-minute story

1. Show one intentionally broken payment journey as a connected evidence mesh: merchant, journey,
   payment, order, immutable events, incident, and diagnosis.
2. Open the cited evidence and explain that deterministic invariants—not Gemini—own incident truth.
3. Create the server-derived exact-capture proposal. Show its policy hash, cap, confidence, target,
   and immutable maker identity.
4. Demonstrate that the maker cannot self-approve, then use the checker identity and execute the
   bounded Test Mode action. Show authoritative preflight, mutation checkpoint, provider receipt,
   and an idempotent second execution with no second provider mutation.
5. Run the proof command and point to exact false-positive/false-negative counts, chaos checks, policy
   denial checks, latency, throughput, and the stable SHA-256 proof.

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
- “How do you know duplicate/out-of-order events are safe?” The proof compares state hashes, while
  database constraints and queue generations enforce the same design under concurrency.
- “Are zero false negatives guaranteed?” No. The reported zero applies only to the labelled held-out
  synthetic set. Unknown live distributions require monitoring, merchant-specific evaluation, and
  staged rollout.
- “Is this production?” It is production-shaped and directly deployable after the external gates in
  the runbook; live money movement remains deliberately unsupported.
