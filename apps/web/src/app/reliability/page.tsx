import type { Metadata } from "next";

import { JudgeDashboard } from "../judge/judge-dashboard";
import { createScaleEvidenceReport } from "../judge/scale-evidence-report";

export const metadata: Metadata = {
  title: "Reliability · Chakravyuh",
  description: "Review bounded recovery safety, scale, and failure measurements",
};

export default function ReliabilityPage() {
  return <JudgeDashboard report={createScaleEvidenceReport()} />;
}
