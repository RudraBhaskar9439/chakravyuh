# Security policy

## Reporting

Do not open a public issue for a suspected vulnerability involving credentials, payment state, or personally identifiable information. Report it privately to the repository owner.

## Development requirements

- The source repository must remain private. Do not publish, create a public fork, or enable public Pages/Actions artifacts.
- Use Razorpay Test Mode credentials only.
- Never commit API secrets, webhook secrets, customer contact details, or raw production events.
- Verify webhook signatures against the unmodified request body.
- Never log webhook bodies. The raw ledger can contain payment and customer data and must run on
  encrypted-at-rest PostgreSQL with access-restricted backups in any non-local deployment.
- Rotate webhook secrets by retaining the previous secret only for Razorpay's retry window, then
  remove it.
- Keep the application database role unable to alter schemas, triggers, or ledger protections.
- Treat every external event as replayable and potentially out of order.
- Keep model prompts free of credentials and unnecessary PII.
- Require deterministic policy validation before every external action.
- Default to read-only or approval-required behavior when state is uncertain.

## Supported versions

Only the latest revision on the main development branch is supported during the buildathon.
