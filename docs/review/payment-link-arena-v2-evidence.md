# Payment Link Recovery Arena v2 evidence

## Outcome

The failed-payment extension passed its locked held-out gates over 10,005 observed journeys. It
keeps Recovery Arena v1 unchanged and exercises the production `failed_without_recovery` detector,
Payment Link policy, maker-checker controls, mutation checkpoint, provider reconciliation, and
webhook-only recovery scoring.

## Locked results

| Measurement | No intervention | Link every failure | Chakravyuh |
| --- | ---: | ---: | ---: |
| Action attempts | 0 | 1,334 | 577 |
| Incorrect actions | 0 | 757 | 0 |
| Unique confirmed recoveries | 0 | 203 | 203 |
| Duplicate link creations | 0 | 0 | 0 |
| Gross synthetic recovery | ₹0 | ₹63,210 | ₹63,210 |
| Net synthetic value | ₹0 | −₹12,490 | ₹51,670 |

Chakravyuh incident precision, incident recall, action precision, and action recall are all 1.0.
Its 265 paid-webhook deliveries deduplicate to 203 unique provider event identities. Unconfirmed
links earn ₹0.

## Trust anchors

- implementation revision: `a5e5f870642c440ece752c4a1ec5a9638489fe37`
- base portfolio manifest: `00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112`
- v2 contract: `6a05b77743d48a2d8ea1d2396a157083f9b844093fa84d282f96f309c132e933`
- v2 oracle root: `5a10b39697e69f52769f25ddce9891ad22054b99911d41ca99d1a4de307579a8`
- Chakravyuh results root: `ea802954f6ae912dafeebf2793cc20500fd7f578a11bff3a2c52b98c7a5cd1a4`
- final report: `f5f689c51eda2076b6ef480f52832a250711448eebbf0a779fedda168142e72b`

The committed report is
[`proof/phase-12/payment-link-arena-v2.json`](../../proof/phase-12/payment-link-arena-v2.json).

## Verification

```bash
uv run chakravyuh-payment-link-arena \
  --verify proof/phase-12/payment-link-arena-v2.json \
  --expected-code-revision a5e5f870642c440ece752c4a1ec5a9638489fe37 \
  --expected-report-sha256 f5f689c51eda2076b6ef480f52832a250711448eebbf0a779fedda168142e72b
```

The verifier parses every typed nested hash, checks both external anchors, regenerates the complete
held-out tournament, and requires byte-equivalent report semantics.

## Claims boundary

This is deterministic synthetic INR evaluation over provider-shaped Razorpay Test Mode semantics.
It does not establish live customer conversion, merchant revenue lift, a production SLA, or a
Razorpay endorsement. A completed hosted Test Mode failed-payment journey remains the separate
real-provider proof.
