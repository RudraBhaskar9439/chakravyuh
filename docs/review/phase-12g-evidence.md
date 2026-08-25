# Phase 12G read-only judge dashboard evidence

## Delivered surface

The static `/judge` route is the Recovery Arena evidence room. It exposes five focused views:

- the three-strategy counterfactual tournament and net recovery economics;
- the 10,005 → 4,002 → 667 → 457 → 402 recovery funnel;
- the signed-webhook-to-confirmation connected evidence mesh;
- nine explicit retry, ordering, crash, projection, and provider failure outcomes; and
- an exception ledger that reports missed recovery, invalid-model, guard, abstention, and lost-HTTP-
  response cases instead of hiding them.

Every proof source remains labelled. Held-out synthetic INR, metered live AI, the separate ₹10
Razorpay Test Mode payment, and local PostgreSQL/Neo4j scale measurements are never combined into a
single real-revenue or production-SLA claim. Tournament, live-AI, signed-ingress, and full-pipeline
SHA-256 roots are visible beside their claims.

## Authority boundary

The page is presentation-only. It has no form, operator token, execution client, mutation request,
or capture, retry, refund, approval, or execute control. Its five buttons only select local React
views. The sole provider-proof link navigates to the separately bounded Test Mode checkout proof;
it does not call a provider action from the judge room.

## Verification

- Formatter and TypeScript checks passed across 23 frontend files.
- Vitest passed 9 tests in 4 files, including traversal of all five views and a negative assertion
  that no money-action button exists.
- The production Next.js build completed and emitted `/judge` as a static route.
- The page was inspected in the in-app browser at desktop size and at a 390 × 844 mobile viewport.
  The mobile document had no horizontal overflow, no form, and no action-labelled control.
- Browser console inspection reported zero warnings or errors.

The dashboard contains no claim that depends on a live provider or model call at presentation time.
It therefore remains demonstrable offline after the proof constants have been reviewed.
