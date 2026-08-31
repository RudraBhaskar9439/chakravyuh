# Payment Link Recovery Arena v2

## Why this is a separate arena

Recovery Arena v1 is an immutable proof for `authorized_not_captured -> capture_payment`. Changing
its incident, action, provider twin, or confirmation rule would invalidate the published hashes.
Arena v2 therefore extends the evidence beside v1 and reuses only the already committed 10,005
observed held-out journeys.

## Locked boundary

- Incident: `failed_without_recovery`.
- Action: one exact `create_payment_link` operation.
- Maximum amount: ₹1,000 (100,000 subunits).
- Link lifetime: 24 hours.
- Confirmation: unique authoritative `payment_link.paid` event identity.
- Strategies: no intervention, link every failed payment, and Chakravyuh.
- Review cost: ₹20 per independently checked proposal.
- Incorrect-action cost: ₹100 per ineligible link attempt.
- Claims: synthetic INR outcomes over provider-shaped Test Mode semantics only.

The oracle stays outside every strategy. It binds expected incident, exact payment and amount,
action eligibility, recoverability, and a predetermined provider outcome into a separate case hash.

## Provider fault matrix

The deterministic Payment Link twin covers eight outcomes:

1. created and later paid;
2. paid with duplicate webhook delivery;
3. paid but the create response is lost;
4. created and never paid;
5. timeout before provider mutation;
6. timeout after provider mutation;
7. expired provider response;
8. conflicting-amount provider response.

The twin implements the same narrow gateway used by the deployed Razorpay adapter. It exposes only
fetch payment, create Payment Link, and fetch-by-reference to a strategy. Each strategy gets an
independent twin. Operation receipts, provider snapshot, oracle, per-case result, and aggregate
roots are deterministic SHA-256 commitments.

## Production path exercised

Chakravyuh reduces the complete temporal journey, runs the production invariant evaluator, selects
exactly one supported finding, constructs a server-derived proposal, evaluates the production
Payment Link policy, records independent maker/checker decisions, writes the mutation checkpoint,
and calls the production `RecoveryActionControlPlane`.

Timeout after create never causes a second POST. The control plane reconciles by the unique
reference. A returned `created` link proves only action success; it earns no recovery credit. A paid
confirmation is deduplicated by provider event identity before scoring.

## Acceptance gates

- incident precision and recall are both 1.0;
- action precision and recall are both 1.0;
- zero incorrect Chakravyuh actions;
- zero duplicate Payment Link creations;
- the guarded strategy matches the unsafe baseline's confirmed recoveries;
- guarded net recovery value exceeds both baselines;
- every recovery credit has a unique paid confirmation.

Run the full arena without credentials, network, PostgreSQL, or Neo4j:

```bash
chakravyuh-payment-link-arena --code-revision "$(git rev-parse HEAD)"
```

Use `--output PATH` to publish a new report. The command refuses to overwrite an existing artifact.
