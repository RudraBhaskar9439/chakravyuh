import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("judge readiness", () => {
  it("keeps infrastructure and configured capabilities visibly separate", async () => {
    configure();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health/demo")) {
        return Response.json({
          status: "ok",
          checks: {
            test_checkout: "ok",
            test_mode_provider: "ok",
            bounded_actions: "ok",
            diagnosis_provider: "ok",
            signed_webhook: "ok",
          },
        });
      }
      return Response.json({ status: "ok" });
    });

    const response = await GET();
    const payload = (await response.json()) as {
      status: string;
      checks: Array<{ status: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.status).toBe("ready");
    expect(payload.checks).toHaveLength(7);
    expect(payload.checks.every((item) => item.status === "ready")).toBe(true);
  });

  it("fails visibly when one dependency is unavailable", async () => {
    configure();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health/graph")) return Response.json({}, { status: 503 });
      if (url.endsWith("/health/demo")) {
        return Response.json({
          checks: {
            test_checkout: "ok",
            test_mode_provider: "ok",
            diagnosis_provider: "ok",
            signed_webhook: "ok",
          },
        });
      }
      return Response.json({ status: "ok" });
    });

    const response = await GET();
    const payload = (await response.json()) as {
      status: string;
      checks: Array<{ id: string; status: string }>;
    };

    expect(response.status).toBe(503);
    expect(payload.status).toBe("degraded");
    expect(payload.checks.find((item) => item.id === "graph")?.status).toBe("unavailable");
  });
});

function configure() {
  vi.stubEnv("CHAKRAVYUH_API_BASE_URL", "https://api.example.test");
  vi.stubEnv("CHAKRAVYUH_DEMO_MAKER_TOKEN", "maker");
  vi.stubEnv("CHAKRAVYUH_DEMO_CHECKER_TOKEN", "checker");
  vi.stubEnv("CHAKRAVYUH_DEMO_EXECUTOR_TOKEN", "executor");
}
