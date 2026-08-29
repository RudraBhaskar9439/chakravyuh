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

export async function GET() {
  const apiBase = process.env.CHAKRAVYUH_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!apiBase) return readinessResponse(unconfiguredChecks(), 503);

  const [live, ready, graph, demo] = await Promise.all([
    probe(new URL("/health/live", apiBase)),
    probe(new URL("/health/ready", apiBase)),
    probe(new URL("/health/graph", apiBase)),
    probe(new URL("/health/demo", apiBase)),
  ]);
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
      "Razorpay Test Mode",
      capability("test_checkout") && capability("test_mode_provider"),
      capability("test_checkout") && capability("test_mode_provider")
        ? "Checkout and provider configured"
        : "Provider capability unavailable",
    ),
    check(
      "ai",
      "Grounded AI diagnosis",
      capability("diagnosis_provider"),
      capability("diagnosis_provider")
        ? "Bounded provider ready"
        : "Diagnosis provider unavailable",
    ),
    check(
      "webhook",
      "Signed webhook ingress",
      capability("signed_webhook"),
      capability("signed_webhook") ? "Verification secret configured" : "Ingress unavailable",
    ),
    check(
      "session",
      "Isolated judge authority",
      authorityConfigured,
      authorityConfigured ? "Maker, checker and executor scoped" : "Judge authority unavailable",
    ),
  ];
  return readinessResponse(checks, checks.every((item) => item.status === "ready") ? 200 : 503);
}

async function probe(url: URL): Promise<{ ok: boolean; payload: unknown }> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
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
    check("provider", "Razorpay Test Mode", false, "Readiness unavailable"),
    check("ai", "Grounded AI diagnosis", false, "Readiness unavailable"),
    check("webhook", "Signed webhook ingress", false, "Readiness unavailable"),
    check("session", "Isolated judge authority", false, "Readiness unavailable"),
  ];
}
