import type { Metadata } from "next";

import { TestCheckout } from "../../demo-checkout/test-checkout";

export const metadata: Metadata = {
  title: "Recover Failed Payment · Chakravyuh",
  description: "Recover a real Razorpay Test Mode failure with a bounded Payment Link",
};

export default function FailedPaymentRecoveryPage() {
  return <TestCheckout scenario="failed" />;
}
