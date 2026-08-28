type DemoRole = "maker" | "checker" | "executor";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

type RoutePolicy = {
  method: "GET" | "POST";
  pattern: RegExp;
  role: DemoRole;
};

const routePolicies: RoutePolicy[] = [
  { method: "POST", pattern: /^v1\/demo\/checkout\/orders$/, role: "maker" },
  { method: "POST", pattern: /^v1\/demo\/checkout\/verifications$/, role: "maker" },
  {
    method: "POST",
    pattern: /^v1\/demo\/checkout\/verifications\/pay_[A-Za-z0-9]+\/reconcile$/,
    role: "maker",
  },
  {
    method: "GET",
    pattern: /^v1\/demo\/checkout\/verifications\/pay_[A-Za-z0-9]+\/proof$/,
    role: "maker",
  },
  { method: "GET", pattern: /^v1\/operator\/incidents$/, role: "maker" },
  {
    method: "GET",
    pattern: /^v1\/operator\/incidents\/[0-9a-f-]{36}$/i,
    role: "maker",
  },
  {
    method: "GET",
    pattern: /^v1\/operator\/incidents\/[0-9a-f-]{36}\/actions$/i,
    role: "maker",
  },
  {
    method: "POST",
    pattern: /^v1\/operator\/incidents\/[0-9a-f-]{36}\/actions\/proposals$/i,
    role: "maker",
  },
  {
    method: "POST",
    pattern: /^v1\/operator\/actions\/[0-9a-f-]{36}\/decisions$/i,
    role: "checker",
  },
  {
    method: "POST",
    pattern: /^v1\/operator\/actions\/[0-9a-f-]{36}\/execute$/i,
    role: "executor",
  },
];

const tokenVariables: Record<DemoRole, string> = {
  maker: "CHAKRAVYUH_DEMO_MAKER_TOKEN",
  checker: "CHAKRAVYUH_DEMO_CHECKER_TOKEN",
  executor: "CHAKRAVYUH_DEMO_EXECUTOR_TOKEN",
};

export async function GET(request: Request, context: RouteContext) {
  return forward(request, context, "GET");
}

export async function POST(request: Request, context: RouteContext) {
  return forward(request, context, "POST");
}

async function forward(request: Request, context: RouteContext, method: "GET" | "POST") {
  const { path: segments } = await context.params;
  const path = segments.join("/");
  const policy = routePolicies.find(
    (candidate) => candidate.method === method && candidate.pattern.test(path),
  );
  if (!policy) return errorResponse(404, "demo_route_not_allowed");
  if (method === "POST" && !isSameOrigin(request)) {
    return errorResponse(403, "cross_origin_demo_mutation_rejected");
  }

  const apiBase = process.env.CHAKRAVYUH_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  const token = process.env[tokenVariables[policy.role]];
  if (!apiBase || !token) return errorResponse(503, "demo_gateway_not_configured");

  const sourceUrl = new URL(request.url);
  const upstreamUrl = new URL(`/${path}`, ensureTrailingSlash(apiBase));
  upstreamUrl.search = sourceUrl.search;
  const requestId = request.headers.get("X-Request-ID") ?? crypto.randomUUID();

  try {
    const upstream = await fetch(upstreamUrl, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
    const headers = new Headers({
      "Cache-Control": "no-store",
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "X-Request-ID": requestId,
    });
    const retryAfter = upstream.headers.get("Retry-After");
    if (retryAfter) headers.set("Retry-After", retryAfter);
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return errorResponse(502, "demo_gateway_upstream_unavailable");
  }
}

function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  try {
    return new URL(origin).host === new URL(request.url).host;
  } catch {
    return false;
  }
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function errorResponse(status: number, code: string): Response {
  return Response.json({ detail: { code } }, { status, headers: { "Cache-Control": "no-store" } });
}
