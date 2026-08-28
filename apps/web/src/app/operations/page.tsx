import type { Metadata } from "next";

import { OperatorDashboard } from "../operator-dashboard";

export const metadata: Metadata = {
  title: "Secure Operations · Chakravyuh",
  description: "Authenticated payment incident and recovery operations",
};

export default function OperationsPage() {
  return <OperatorDashboard />;
}
