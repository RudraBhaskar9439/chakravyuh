import {
  type DemoSession,
  demoSessionMutationLimit,
  evolveDemoSession,
  getDemoSessionSecret,
  readDemoSession,
  writeDemoSession,
} from "../session-state";

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
  { method: "POST", pattern: /^v1\/demo\/checkout\/failures$/, role: "maker" },
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
  const secret = getDemoSessionSecret();
  const session = secret ? readDemoSession(request, secret) : null;
  if (method === "POST" && (!secret || !session)) {
    return errorResponse(401, "demo_session_required");
  }
  if (session && session.mutationCount >= demoSessionMutationLimit) {
    return errorResponse(429, "demo_session_mutation_limit_reached", {
      "Retry-After": String(Math.max(1, Math.ceil((session.expiresAt - Date.now()) / 1000))),
    });
  }

  const sourceUrl = new URL(request.url);
  const upstreamUrl = new URL(`/${path}`, ensureTrailingSlash(apiBase));
  upstreamUrl.search = sourceUrl.search;
  const requestId = request.headers.get("X-Request-ID") ?? crypto.randomUUID();

  try {
    const requestBody = method === "POST" ? await request.text() : undefined;
    const ownershipFailure =
      method === "POST" && session
        ? await validateOwnership(path, requestBody ?? "", session, apiBase, tokenVariables)
        : null;
    if (ownershipFailure) return errorResponse(403, ownershipFailure);
    const upstream = await fetch(upstreamUrl, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: requestBody,
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
    const body = await upstream.text();
    if (method === "POST" && upstream.ok && session && secret) {
      writeDemoSession(headers, evolveDemoSession(session, extractOwnedIds(path, body)), secret);
    }
    return new Response(body, { status: upstream.status, headers });
  } catch {
    return errorResponse(502, "demo_gateway_upstream_unavailable");
  }
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

function ensureTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function errorResponse(status: number, code: string, extraHeaders: HeadersInit = {}): Response {
  return Response.json(
    { detail: { code } },
    {
      status,
      headers: { "Cache-Control": "no-store", ...Object.fromEntries(new Headers(extraHeaders)) },
    },
  );
}

async function validateOwnership(
  path: string,
  body: string,
  session: DemoSession,
  apiBase: string,
  variables: Record<DemoRole, string>,
): Promise<string | null> {
  if (path === "v1/demo/checkout/orders") return null;
  if (path === "v1/demo/checkout/verifications") {
    const orderId = parseJsonString(body, "razorpay_order_id");
    return orderId && session.orderIds.includes(orderId) ? null : "demo_order_not_owned";
  }
  if (path === "v1/demo/checkout/failures") {
    const orderId = parseJsonString(body, "razorpay_order_id");
    return orderId && session.orderIds.includes(orderId) ? null : "demo_order_not_owned";
  }
  const payment = path.match(/verifications\/(pay_[A-Za-z0-9]+)\/reconcile$/)?.[1];
  if (payment) return session.paymentIds.includes(payment) ? null : "demo_payment_not_owned";
  const incident = path.match(/incidents\/([0-9a-f-]{36})\/actions\/proposals$/i)?.[1];
  if (incident) {
    if (session.incidentIds.includes(incident)) return null;
    const makerToken = process.env[variables.maker];
    if (!makerToken) return "demo_gateway_not_configured";
    try {
      const response = await fetch(new URL(`/v1/operator/incidents/${incident}`, apiBase), {
        headers: { Authorization: `Bearer ${makerToken}` },
        cache: "no-store",
      });
      if (!response.ok) return "demo_incident_ownership_unverified";
      const detail = (await response.json()) as {
        incident?: { affected_entity?: { entity_id?: string } };
      };
      return detail.incident?.affected_entity?.entity_id &&
        session.paymentIds.includes(detail.incident.affected_entity.entity_id)
        ? null
        : "demo_incident_not_owned";
    } catch {
      return "demo_incident_ownership_unverified";
    }
  }
  const proposal = path.match(/actions\/([0-9a-f-]{36})\/(?:decisions|execute)$/i)?.[1];
  if (proposal) return session.proposalIds.includes(proposal) ? null : "demo_proposal_not_owned";
  return "demo_mutation_not_owned";
}

function extractOwnedIds(
  path: string,
  body: string,
): Partial<Pick<DemoSession, "orderIds" | "paymentIds" | "incidentIds" | "proposalIds">> {
  try {
    const payload = JSON.parse(body) as {
      order?: { order_id?: string };
      payment?: { payment_id?: string };
      proposal?: { proposal_id?: string; incident_id?: string };
    };
    if (path === "v1/demo/checkout/orders" && payload.order?.order_id) {
      return { orderIds: [payload.order.order_id] };
    }
    if (path === "v1/demo/checkout/verifications" && payload.payment?.payment_id) {
      return { paymentIds: [payload.payment.payment_id] };
    }
    if (path === "v1/demo/checkout/failures" && payload.payment?.payment_id) {
      return { paymentIds: [payload.payment.payment_id] };
    }
    if (payload.proposal?.proposal_id) {
      return {
        proposalIds: [payload.proposal.proposal_id],
        incidentIds: payload.proposal.incident_id ? [payload.proposal.incident_id] : [],
      };
    }
  } catch {
    return {};
  }
  return {};
}

function parseJsonString(body: string, key: string): string | null {
  try {
    const value = (JSON.parse(body) as Record<string, unknown>)[key];
    return typeof value === "string" ? value : null;
  } catch {
    return null;
  }
}
