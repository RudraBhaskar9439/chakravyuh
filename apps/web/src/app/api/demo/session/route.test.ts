import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("judge session", () => {
  it("issues an expiring HttpOnly same-site session without exposing authority", async () => {
    vi.stubEnv("CHAKRAVYUH_DEMO_SESSION_SECRET", "session-secret");
    const response = await POST(
      new Request("https://demo.example.test/api/demo/session", {
        method: "POST",
        headers: { Origin: "https://demo.example.test" },
      }),
    );

    expect(response.status).toBe(200);
    const payload = (await response.json()) as Record<string, unknown>;
    expect(payload.session_id).toMatch(/[0-9a-f-]{36}/);
    expect(payload.remaining_mutations).toBe(24);
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
    expect(response.headers.get("Set-Cookie")).toContain("SameSite=Strict");
    expect(JSON.stringify(payload)).not.toContain("session-secret");
  });

  it("rejects missing sessions and cross-origin creation", async () => {
    vi.stubEnv("CHAKRAVYUH_DEMO_SESSION_SECRET", "session-secret");
    const missing = await GET(new Request("https://demo.example.test/api/demo/session"));
    const crossOrigin = await POST(
      new Request("https://demo.example.test/api/demo/session", {
        method: "POST",
        headers: { Origin: "https://attacker.example" },
      }),
    );

    expect(missing.status).toBe(401);
    expect(crossOrigin.status).toBe(403);
  });
});
