import { createHash } from "node:crypto";

export type EvidenceSource = "synthetic" | "live-ai" | "real-provider" | "local-scale";

export type ScaleEvidenceReport = ReturnType<typeof createScaleEvidenceReport>;

const evidence = {
  reportVersion: "chakravyuh-scale-evidence-v1",
  evidenceRunAt: "2026-08-25T00:00:00+05:30",
  claimsBoundary:
    "Reproducible Test Mode and synthetic measurements; not a production SLA or merchant revenue claim.",
  proofRoots: {
    portfolio: "00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112",
    tournament: "b4086ba1516fbbe2b590b112ca4e43aa3ea291e1cfdeb103cf37b72edc712812",
    liveAi: "7b91feec4b8ba77baf03c6f21f5a0f14462b977aa090fbf5705fdabc70e7c0d8",
    signedIngress: "abd03fab3f2869db03875515dcc541f8b440b9041090f415edef488d920abd48",
    fullPipeline: "d390a1625bd2de6fbdab6b45315b6563c2f527a303d97214ebc26b08bfe52915",
  },
  strategies: [
    {
      name: "No intervention",
      actions: 0,
      confirmedRecoveries: 0,
      incorrectActions: 0,
      recoveredRupees: 0,
      netRupees: 0,
    },
    {
      name: "Retry all",
      actions: 4002,
      confirmedRecoveries: 402,
      incorrectActions: 3545,
      recoveredRupees: 157280,
      netRupees: -197220,
    },
    {
      name: "Chakravyuh",
      actions: 457,
      confirmedRecoveries: 402,
      incorrectActions: 0,
      recoveredRupees: 157280,
      netRupees: 148140,
    },
  ],
  funnel: [
    { label: "Held-out payment journeys", value: 10005, note: "Oracle hidden from strategies" },
    { label: "Deterministic incidents", value: 4002, note: "Precision / recall / F1 = 1.0" },
    { label: "Bounded proposals", value: 667, note: "One incident family can propose capture" },
    { label: "Policy-eligible actions", value: 457, note: "210 denied before provider mutation" },
    {
      label: "Webhook-confirmed recoveries",
      value: 402,
      note: "No request-only recovery credit",
    },
  ],
  meshNodes: [
    { id: "signed", label: "Signed webhook", detail: "HMAC + event identity", lane: 0 },
    { id: "ledger", label: "Immutable ledger", detail: "100,000 durable events", lane: 1 },
    { id: "journey", label: "Temporal journey", detail: "Order-independent state", lane: 2 },
    { id: "invariant", label: "Invariant", detail: "Deterministic money rule", lane: 3 },
    { id: "subgraph", label: "Evidence subgraph", detail: "Bounded connected facts", lane: 4 },
    { id: "model", label: "AI proposal", detail: "Cannot execute actions", lane: 5 },
    { id: "guard", label: "Deterministic guard", detail: "Citations + allowlists", lane: 6 },
    { id: "policy", label: "Policy", detail: "Exact target + amount", lane: 7 },
    { id: "checker", label: "Independent checker", detail: "Dual control", lane: 8 },
    { id: "provider", label: "Provider mutation", detail: "Checkpoint before call", lane: 9 },
    {
      id: "confirmed",
      label: "Webhook confirmation",
      detail: "Only recovery credit",
      lane: 10,
    },
  ],
  chaosChecks: [
    ["Concurrent redelivery", "One immutable insert"],
    ["Out-of-order delivery", "Same canonical state hash"],
    ["Late event", "Full-history rebuild, no regression"],
    ["Oversized journey", "Dead-letter then audited replay"],
    ["Crash before checkpoint", "No provider mutation credited"],
    ["Crash after mutation", "Reconcile only; never POST twice"],
    ["Repeated graph commit", "Idempotent before checkpoint"],
    ["Projection outage", "Lag visible; audited rebuild"],
    ["All AI providers unavailable", "Fail closed"],
  ],
  exceptions: [
    {
      source: "synthetic" as EvidenceSource,
      count: 19,
      title: "Recoverable cases missed",
      disposition: "Provider faults prevented confirmation; no revenue was credited.",
    },
    {
      source: "live-ai" as EvidenceSource,
      count: 1,
      title: "Invalid structured response",
      disposition: "Rejected and charged at its full pre-call reservation.",
    },
    {
      source: "live-ai" as EvidenceSource,
      count: 1,
      title: "Guard intervention",
      disposition: "Invalid invariant citation converted into abstention.",
    },
    {
      source: "live-ai" as EvidenceSource,
      count: 2,
      title: "Effective abstentions",
      disposition: "No action path was made available.",
    },
    {
      source: "local-scale" as EvidenceSource,
      count: 1,
      title: "Lost HTTP response",
      disposition: "Same-ID retry proved durability; zero duplicate rows.",
    },
  ],
} as const;

export function createScaleEvidenceReport() {
  const deploymentRevision =
    process.env.VERCEL_GIT_COMMIT_SHA ?? process.env.RENDER_GIT_COMMIT ?? "local-development";
  const content = { ...evidence, deploymentRevision };
  return {
    ...content,
    reportSha256: createHash("sha256").update(JSON.stringify(content)).digest("hex"),
  };
}
