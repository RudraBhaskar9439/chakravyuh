# Design-partner validation kit

This kit turns the technical proof into merchant evidence without using live funds. Run it with
three to five payments or finance-operations practitioners. Do not ask for production credentials,
customer data, or screenshots containing personal information.

## Twenty-minute session

1. Ask the participant to describe the last failed-payment or authorized-but-uncaptured incident
   they investigated. Record the tools, hand-offs, elapsed time, and final outcome.
2. Show the two Chakravyuh journeys without explaining the controls first. Ask them to find the
   affected payment, evidence path, proposed recovery, and final provider receipt.
3. Ask them to explain the result back to you. If they cannot distinguish detection, AI diagnosis,
   policy approval, execution, and provider confirmation, record that as a usability failure.
4. Show the replay, stale-proposal, duplicate-delivery, and model-unavailable behaviors.
5. Ask whether they would pilot it in a Test Mode or shadow environment and what evidence their
   security and finance teams would require.

## Evidence to capture

| Measure | Before | With Chakravyuh | Acceptance gate |
| --- | ---: | ---: | ---: |
| Time to identify the broken journey | minutes | minutes | at least 50% lower |
| Time to assemble supporting evidence | minutes | minutes | at least 70% lower |
| Incorrect recovery actions proposed | count | count | zero in reviewed cases |
| Duplicate provider mutations | count | count | zero |
| Participant can explain why action is safe | yes/no | yes/no | yes |
| Participant requests a shadow pilot | yes/no | yes/no | at least two partners |

Also record the participant's role, business model, monthly payment-volume band, current tools, and
the exact objection that would block adoption. Do not record company or person names in the public
proof without consent.

## Pilot boundary

- Start read-only with Test Mode or redacted historical events.
- Run deterministic detection and evidence reconstruction first; keep actions disabled.
- Compare findings against the merchant's existing incident process.
- Enable Test Mode maker-checker recovery only after the merchant signs off on the findings.
- Live money movement remains a separate security, legal, reliability, and Razorpay review gate.

## Honest judge claim

Until these sessions happen, say: “The provider path and synthetic scale evidence are verified; the
design-partner validation kit is ready, but merchant demand has not yet been independently proven.”
Afterward, publish aggregate results and anonymized objections, never invented testimonials.
