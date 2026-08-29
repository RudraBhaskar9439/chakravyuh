import {
  createDemoSession,
  demoSessionMutationLimit,
  getDemoSessionSecret,
  readDemoSession,
  writeDemoSession,
} from "../session-state";

export async function GET(request: Request) {
  const secret = getDemoSessionSecret();
  if (!secret) return errorResponse(503, "demo_session_not_configured");
  const session = readDemoSession(request, secret);
  if (!session) return errorResponse(401, "demo_session_required");
  return sessionResponse(session);
}

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return errorResponse(403, "cross_origin_demo_session_rejected");
  const secret = getDemoSessionSecret();
  if (!secret) return errorResponse(503, "demo_session_not_configured");
  const session = readDemoSession(request, secret) ?? createDemoSession();
  const response = sessionResponse(session);
  writeDemoSession(response.headers, session, secret);
  return response;
}

function sessionResponse(session: ReturnType<typeof createDemoSession>): Response {
  return Response.json(
    {
      session_id: session.sessionId,
      expires_at: new Date(session.expiresAt).toISOString(),
      remaining_mutations: demoSessionMutationLimit - session.mutationCount,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  if (!origin) return process.env.NODE_ENV !== "production";
  try {
    return new URL(origin).host === new URL(request.url).host;
  } catch {
    return false;
  }
}

function errorResponse(status: number, code: string): Response {
  return Response.json({ detail: { code } }, { status, headers: { "Cache-Control": "no-store" } });
}
