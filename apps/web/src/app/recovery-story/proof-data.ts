export type RecoveryStage = {
  label: string;
  time: string;
  title: string;
  copy: string;
  evidence: string;
};

export const recoveryStages: readonly RecoveryStage[] = [
  {
    label: "Stuck",
    time: "4:28:22 PM",
    title: "Payment authorized. Capture missing.",
    copy: "Razorpay accepted the ₹10 Test Mode authorization, but the money journey stopped before capture.",
    evidence: "Provider state · authorized",
  },
  {
    label: "Detect",
    time: "4:29:21 PM",
    title: "The invariant broke. Chakravyuh noticed.",
    copy: "The deterministic detector compared the payment journey with the capture-window rule and opened one incident.",
    evidence: "Detected in 59 seconds",
  },
  {
    label: "Explain",
    time: "4:34:26 PM",
    title: "AI explained the graph. It could not touch money.",
    copy: "A bounded evidence subgraph was sent for diagnosis. The model cited the authorization and recommended one exact action.",
    evidence: "2,119 tokens · $0.000940",
  },
  {
    label: "Govern",
    time: "4:55:06 PM",
    title: "Policy fixed the target. Two humans fixed the authority.",
    copy: "The server derived the payment and amount from immutable evidence. A maker proposed; an independent checker approved.",
    evidence: "Self-approval was rejected",
  },
  {
    label: "Recover",
    time: "4:57:13 PM",
    title: "One mutation. Zero duplicates. ₹10 recovered.",
    copy: "The executor captured exactly ₹10 once. Razorpay then confirmed both payment.captured and order.paid before resolution.",
    evidence: "Provider-confirmed recovery",
  },
] as const;

export const proofLedger = [
  {
    label: "Checkout verification",
    hash: "f8943271c7b74680fb3780050ec4d11d950c77e36818d2c7fa579329ace5b1f8",
  },
  {
    label: "Incident finding",
    hash: "58515f77203f874ac252c26b60171ff61d98ee545bb75574c41e21338696ab93",
  },
  {
    label: "Evidence subgraph",
    hash: "50f2c20752ca4f27728c4961125ef37d51527ee3513cc67144868fcc28125b29",
  },
  {
    label: "Diagnosis prompt",
    hash: "4f0bbacff164d5c70a701b1dc778034ad8f44d81ba726ae85f22976d027490fa",
  },
  {
    label: "Action proposal",
    hash: "8835b9889787c3d470ae59920ef316b55c7a4b7be9d5395e2b36f6f6b5ee5220",
  },
  {
    label: "Execution result",
    hash: "9d382772478eeaaeb3e69f4dd6d52ee66105f89beebb66cc861b82ff90e2a034",
  },
  {
    label: "Provider confirmation",
    hash: "1ad8e849b68eee47d4aec1ec9b33e36ed40bacabe767caf29a855aa824d180f3",
  },
] as const;

export const meshNodes = [
  { label: "Order", x: 72, y: 210, stage: 0, tone: "entity" },
  { label: "Authorized", x: 240, y: 210, stage: 0, tone: "event" },
  { label: "Invariant", x: 400, y: 92, stage: 1, tone: "rule" },
  { label: "Evidence mesh", x: 400, y: 330, stage: 2, tone: "graph" },
  { label: "AI diagnosis", x: 585, y: 330, stage: 2, tone: "ai" },
  { label: "Policy", x: 585, y: 92, stage: 3, tone: "rule" },
  { label: "Dual control", x: 760, y: 210, stage: 3, tone: "control" },
  { label: "Captured", x: 930, y: 210, stage: 4, tone: "success" },
] as const;

export const meshEdges = [
  [0, 1, 0],
  [1, 2, 1],
  [1, 3, 2],
  [2, 3, 2],
  [3, 4, 2],
  [4, 5, 3],
  [5, 6, 3],
  [6, 7, 4],
] as const;
