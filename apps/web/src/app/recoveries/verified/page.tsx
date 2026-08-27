import type { Metadata } from "next";

import { RecoveryStory } from "../../recovery-story/recovery-story";

export const metadata: Metadata = {
  title: "Verified Recovery · Chakravyuh",
  description: "Inspect a provider-confirmed Razorpay Test Mode recovery and its audit trail",
};

export default function VerifiedRecoveryPage() {
  return <RecoveryStory />;
}
