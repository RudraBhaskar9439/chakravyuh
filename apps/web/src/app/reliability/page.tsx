import type { Metadata } from "next";

import { JudgeDashboard } from "../judge/judge-dashboard";

export const metadata: Metadata = {
  title: "Reliability · Chakravyuh",
  description: "Review bounded recovery safety, scale, and failure measurements",
};

export default function ReliabilityPage() {
  return <JudgeDashboard />;
}
