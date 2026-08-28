import { JudgeDashboard } from "./judge-dashboard";
import { createScaleEvidenceReport } from "./scale-evidence-report";

export default function JudgePage() {
  return <JudgeDashboard report={createScaleEvidenceReport()} />;
}
