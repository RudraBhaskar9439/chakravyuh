import { createScaleEvidenceReport } from "../../../judge/scale-evidence-report";

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(createScaleEvidenceReport(), {
    headers: {
      "Cache-Control": "public, max-age=0, must-revalidate",
      "Content-Disposition": 'inline; filename="chakravyuh-scale-evidence.json"',
      "X-Content-Type-Options": "nosniff",
    },
  });
}
