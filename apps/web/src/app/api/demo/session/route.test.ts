import { afterEach, describe, expect, it, vi } from "vitest";

import { createDemoSession, evolveDemoSession, writeDemoSession } from "../session-state";
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

  it("renews an active session without losing its owned payment identities", async () => {
    vi.stubEnv("CHAKRAVYUH_DEMO_SESSION_SECRET", "session-secret");
    const original = evolveDemoSession(createDemoSession(Date.now() - 60_000), {
      orderIds: ["order_owned"],
      paymentIds: ["pay_owned"],
    });
    const cookieHeaders = new Headers();
    writeDemoSession(cookieHeaders, original, "session-secret");
    const cookie = cookieHeaders.get("Set-Cookie")?.split(";", 1)[0] ?? "";

    const response = await POST(
      new Request("https://demo.example.test/api/demo/session", {
        method: "POST",
        headers: { Origin: "https://demo.example.test", Cookie: cookie },
      }),
    );
    const payload = (await response.json()) as Record<string, unknown>;

    expect(response.status).toBe(200);
    expect(payload.session_id).toBe(original.sessionId);
    expect(Date.parse(String(payload.expires_at))).toBeGreaterThan(original.expiresAt);
    expect(payload.remaining_mutations).toBe(23);
  });

  it("rotates an exhausted session so another recovery can start", async () => {
    vi.stubEnv("CHAKRAVYUH_DEMO_SESSION_SECRET", "session-secret");
    let exhausted = createDemoSession();
    for (let index = 0; index < 24; index += 1) {
      exhausted = evolveDemoSession(exhausted);
    }
    const cookieHeaders = new Headers();
    writeDemoSession(cookieHeaders, exhausted, "session-secret");
    const cookie = cookieHeaders.get("Set-Cookie")?.split(";", 1)[0] ?? "";

    const response = await POST(
      new Request("https://demo.example.test/api/demo/session", {
        method: "POST",
        headers: { Origin: "https://demo.example.test", Cookie: cookie },
      }),
    );
    const payload = (await response.json()) as Record<string, unknown>;

    expect(response.status).toBe(200);
    expect(payload.session_id).not.toBe(exhausted.sessionId);
    expect(payload.remaining_mutations).toBe(24);
  });
});
