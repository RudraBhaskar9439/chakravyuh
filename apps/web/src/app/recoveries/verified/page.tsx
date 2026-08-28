import type { Metadata } from "next";

import { LiveProofRoom } from "./live-proof-room";

export const metadata: Metadata = {
  title: "Verified Recovery · Chakravyuh",
  description: "Inspect a provider-confirmed Razorpay Test Mode recovery and its audit trail",
};

export default async function VerifiedRecoveryPage({
  searchParams,
}: {
  searchParams: Promise<{ payment_id?: string | string[] }>;
}) {
  const parameters = await searchParams;
  const paymentId = Array.isArray(parameters.payment_id)
    ? parameters.payment_id[0]
    : parameters.payment_id;
  return <LiveProofRoom paymentId={paymentId} />;
}
