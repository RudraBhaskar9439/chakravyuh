type Check = {
  id: string;
  label: string;
  status: "ready" | "unavailable";
  detail: string;
};

type BackendDemoReadiness = {
  status?: "ok" | "unavailable";
  checks?: Record<string, "ok" | "error">;
};

export const maxDuration = 45;

export async function GET() {
  const apiBase = process.env.CHAKRAVYUH_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!apiBase) return readinessResponse(unconfiguredChecks(), 503);

  // Wake the API before probing dependencies. Free-tier hosts may need several seconds to resume;
  // hitting every dependency concurrently during that window creates a misleading hard failure.
  const live = await probe(new URL("/health/live", apiBase), 25_000);
  const [ready, graph, demo] = live.ok
    ? await Promise.all([
        probe(new URL("/health/ready", apiBase), 12_000),
        probe(new URL("/health/graph", apiBase), 12_000),
        probe(new URL("/health/demo", apiBase), 12_000),
      ])
    : [unavailableProbe, unavailableProbe, unavailableProbe];
  const demoPayload = demo.payload as BackendDemoReadiness | null;
  const capability = (name: string) => demoPayload?.checks?.[name] === "ok";
  const authorityConfigured = Boolean(
    process.env.CHAKRAVYUH_DEMO_MAKER_TOKEN &&
      process.env.CHAKRAVYUH_DEMO_CHECKER_TOKEN &&
      process.env.CHAKRAVYUH_DEMO_EXECUTOR_TOKEN,
  );
  const checks: Check[] = [
    check("api", "Recovery API", live.ok, live.ok ? "Serving requests" : "API unavailable"),
    check(
      "ledger",
      "PostgreSQL ledger",
      ready.ok,
      ready.ok ? "Authoritative store reachable" : "Ledger unavailable",
    ),
    check(
      "graph",
      "Evidence graph",
      graph.ok,
      graph.ok ? "Projection current" : "Graph unavailable or lagging",
    ),
    check(
      "provider",
      "Razorpay credentials",
      capability("test_checkout") && capability("test_mode_provider"),
      capability("test_checkout") && capability("test_mode_provider")
        ? "Test checkout credentials configured"
        : "Test credentials are not configured",
    ),
    check(
      "ai",
      "AI diagnosis route",
      capability("diagnosis_provider"),
      capability("diagnosis_provider")
        ? "Bounded provider configured"
        : "Diagnosis provider is not configured",
    ),
    check(
      "webhook",
      "Webhook verifier",
      capability("signed_webhook"),
      capability("signed_webhook")
        ? "Signature-verification secret configured"
        : "Verification secret is not configured",
    ),
    check(
      "session",
      "Recovery authority",
      authorityConfigured,
      authorityConfigured ? "Maker, checker and executor scoped" : "Recovery authority unavailable",
    ),
  ];
  return readinessResponse(checks, checks.every((item) => item.status === "ready") ? 200 : 503);
}

const unavailableProbe = { ok: false, payload: null };

async function probe(url: URL, timeoutMs: number): Promise<{ ok: boolean; payload: unknown }> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { ok: response.ok, payload: await response.json().catch(() => null) };
  } catch {
    return { ok: false, payload: null };
  }
}

function check(id: string, label: string, ready: boolean, detail: string): Check {
  return { id, label, status: ready ? "ready" : "unavailable", detail };
}

function readinessResponse(checks: Check[], status: number): Response {
  return Response.json(
    {
      status: status === 200 ? "ready" : "degraded",
      checked_at: new Date().toISOString(),
      checks,
    },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function unconfiguredChecks(): Check[] {
  return [
    check("api", "Recovery API", false, "API gateway is not configured"),
    check("ledger", "PostgreSQL ledger", false, "Readiness unavailable"),
    check("graph", "Evidence graph", false, "Readiness unavailable"),
    check("provider", "Razorpay credentials", false, "Configuration unavailable"),
    check("ai", "AI diagnosis route", false, "Configuration unavailable"),
    check("webhook", "Webhook verifier", false, "Configuration unavailable"),
    check("session", "Recovery authority", false, "Readiness unavailable"),
  ];
}
