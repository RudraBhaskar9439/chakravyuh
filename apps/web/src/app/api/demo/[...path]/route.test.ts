import { afterEach, describe, expect, it, vi } from "vitest";

import { createDemoSession, evolveDemoSession, writeDemoSession } from "../session-state";
import { GET, POST } from "./route";

const apiBase = "https://api.example.test";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("demo gateway", () => {
  it("uses the checker credential only for an allowed approval", async () => {
    configureGateway();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ execution_status: "ready" }, { status: 200 }));
    const proposalId = "44444444-4444-4444-8444-444444444444";
    const response = await POST(
      new Request(
        `https://demo.example.test/api/demo/v1/operator/actions/${proposalId}/decisions`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Cookie: sessionCookie({ proposalIds: [proposalId] }),
            Origin: "https://demo.example.test",
          },
          body: JSON.stringify({ decision: "approved" }),
        },
      ),
      context("v1", "operator", "actions", proposalId, "decisions"),
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe(`${apiBase}/v1/operator/actions/${proposalId}/decisions`);
    expect(init?.headers).toMatchObject({ Authorization: "Bearer checker-secret" });
  });

  it("uses the maker credential for bounded reads and preserves the query", async () => {
    configureGateway();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ items: [] }, { status: 200 }));
    const response = await GET(
      new Request("https://demo.example.test/api/demo/v1/operator/incidents?limit=100"),
      context("v1", "operator", "incidents"),
    );

    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe(`${apiBase}/v1/operator/incidents?limit=100`);
    expect(init?.headers).toMatchObject({ Authorization: "Bearer maker-secret" });
  });

  it("rejects unknown routes and cross-origin mutations", async () => {
    configureGateway();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const unknown = await GET(
      new Request("https://demo.example.test/api/demo/v1/operator/operators"),
      context("v1", "operator", "operators"),
    );
    const crossOrigin = await POST(
      new Request("https://demo.example.test/api/demo/v1/demo/checkout/orders", {
        method: "POST",
        headers: { Origin: "https://attacker.example" },
      }),
      context("v1", "demo", "checkout", "orders"),
    );

    expect(unknown.status).toBe(404);
    expect(crossOrigin.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires an isolated session for every public mutation", async () => {
    configureGateway();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const response = await POST(
      new Request("https://demo.example.test/api/demo/v1/demo/checkout/orders", {
        method: "POST",
        headers: { Origin: "https://demo.example.test" },
      }),
      context("v1", "demo", "checkout", "orders"),
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "demo_session_required" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("binds a created order and verified payment to the signed session", async () => {
    configureGateway();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json(
          { order: { order_id: "order_owned" }, public_key_id: "rzp_test" },
          { status: 201 },
        ),
      );
    const response = await POST(
      new Request("https://demo.example.test/api/demo/v1/demo/checkout/orders", {
        method: "POST",
        headers: {
          Cookie: sessionCookie(),
          Origin: "https://demo.example.test",
        },
      }),
      context("v1", "demo", "checkout", "orders"),
    );

    expect(response.status).toBe(201);
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
    expect(response.headers.get("Set-Cookie")).toContain("SameSite=Strict");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("fails closed when a scoped credential is missing", async () => {
    vi.stubEnv("CHAKRAVYUH_API_BASE_URL", apiBase);
    const proposalId = "44444444-4444-4444-8444-444444444444";
    const response = await POST(
      new Request(`https://demo.example.test/api/demo/v1/operator/actions/${proposalId}/execute`, {
        method: "POST",
      }),
      context("v1", "operator", "actions", proposalId, "execute"),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "demo_gateway_not_configured" },
    });
  });
});

function configureGateway() {
  vi.stubEnv("CHAKRAVYUH_API_BASE_URL", apiBase);
  vi.stubEnv("CHAKRAVYUH_DEMO_MAKER_TOKEN", "maker-secret");
  vi.stubEnv("CHAKRAVYUH_DEMO_CHECKER_TOKEN", "checker-secret");
  vi.stubEnv("CHAKRAVYUH_DEMO_EXECUTOR_TOKEN", "executor-secret");
}

function sessionCookie(
  additions: Partial<{
    orderIds: string[];
    paymentIds: string[];
    incidentIds: string[];
    proposalIds: string[];
  }> = {},
) {
  const session = Object.keys(additions).length
    ? evolveDemoSession(createDemoSession(), additions)
    : createDemoSession();
  const headers = new Headers();
  writeDemoSession(headers, session, "maker-secret");
  return headers.get("Set-Cookie")?.split(";")[0] ?? "";
}

function context(...path: string[]) {
  return { params: Promise.resolve({ path }) };
}
