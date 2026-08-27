import type { Metadata } from "next";

import { TestCheckout } from "../../demo-checkout/test-checkout";

export const metadata: Metadata = {
  title: "Live Authorization · Chakravyuh",
  description: "Authorize and follow a controlled Razorpay Test Mode recovery",
};

export default function LiveAuthorizationPage() {
  return <TestCheckout />;
}
