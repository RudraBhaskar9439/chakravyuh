import type { Metadata } from "next";

import { TestCheckout } from "./test-checkout";

export const metadata: Metadata = {
  title: "Create Test Incident · Chakravyuh",
  description: "Create one fixed-value Razorpay Test Mode authorization for recovery proof",
};

export default function DemoCheckoutPage() {
  return <TestCheckout />;
}
