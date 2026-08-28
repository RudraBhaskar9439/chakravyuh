import type { Metadata } from "next";

import { MoneyTrace } from "./money-trace";

export const metadata: Metadata = {
  title: "Money Trace · Chakravyuh",
  description: "Resolve a payment, order, recovery incident or evidence commitment",
};

export default function MoneyTracePage() {
  return <MoneyTrace />;
}
