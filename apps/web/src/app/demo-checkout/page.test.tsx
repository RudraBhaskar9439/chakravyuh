import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DemoCheckoutPage from "./page";
import { TestCheckout } from "./test-checkout";

const prepared = {
  public_key_id: "rzp_test_contract",
  display_name: "Chakravyuh",
  description: "Test payment",
  order: {
    checkout_id: "11111111-1111-4111-8111-111111111111",
    order_id: "order_123",
    amount_subunits: 1000,
    currency: "INR",
    expires_at: "2026-08-25T08:00:00Z",
  },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
  delete window.Razorpay;
  document.querySelector('script[src="https://checkout.razorpay.com/v1/checkout.js"]')?.remove();
});

describe("Test Checkout", () => {
  it("explains the bounded Test Mode flow before authorization", async () => {
    window.Razorpay = class {
      open() {}
    } as never;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input).endsWith("/api/readiness")
        ? jsonResponse(systemReadiness)
        : jsonResponse(judgeSession),
    );
    render(<DemoCheckoutPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Recover an uncaptured payment." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/fixed ₹10 Razorpay Test Mode payment/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Operator access token")).not.toBeInTheDocument();
    expect(await screen.findByText(/Secure session/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Authorize ₹10 in Razorpay" })).toBeEnabled();
  });

  it("creates the server-side order and verifies the Checkout proof", async () => {
    let handler: ((proof: object) => void) | undefined;
    let checkoutOptions: { amount: number; currency: string; order_id: string } | undefined;
    let opened = false;
    window.Razorpay = class {
      constructor(options: {
        amount: number;
        currency: string;
        order_id: string;
        handler: (proof: object) => void;
      }) {
        handler = options.handler;
        checkoutOptions = options;
      }
      open() {
        opened = true;
      }
    } as never;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/demo/session")) return jsonResponse(judgeSession);
      if (url.endsWith("/api/readiness")) return jsonResponse(systemReadiness);
      if (url.endsWith("/v1/demo/checkout/orders")) return jsonResponse(prepared, 201);
      if (url.endsWith("/v1/demo/checkout/verifications")) {
        return jsonResponse({
          verification_id: "22222222-2222-4222-8222-222222222222",
          verification_hash: "a".repeat(64),
          payment: {
            payment_id: "pay_123",
            order_id: "order_123",
            status: "authorized",
            amount_subunits: 1000,
            currency: "INR",
            captured: false,
          },
        });
      }
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<DemoCheckoutPage />);

    await screen.findByText(/Secure session/i);
    fireEvent.click(screen.getByRole("button", { name: "Authorize ₹10 in Razorpay" }));
    await waitFor(() => expect(opened).toBe(true));
    expect(checkoutOptions).toMatchObject({
      amount: 1000,
      currency: "INR",
      order_id: "order_123",
    });
    handler?.({
      razorpay_order_id: "order_123",
      razorpay_payment_id: "pay_123",
      razorpay_signature: "b".repeat(64),
    });

    expect(await screen.findByText("Active transaction")).toBeInTheDocument();
    expect(screen.getAllByText("authorized")).toHaveLength(2);
    expect(screen.getAllByText("₹10.00")).toHaveLength(2);
    expect(screen.getByText(/do not capture/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Follow this payment." })).toBeInTheDocument();
    expect(screen.getByText(/Every stage below is read from the payment/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "See exactly where the money stopped." }),
    ).toBeInTheDocument();
    expect(screen.getByText("STOPPED HERE")).toBeInTheDocument();
    expect(screen.getByText("Watching the capture boundary")).toBeInTheDocument();
    expect(screen.getByText("Waiting for deterministic detection")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    const verificationCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/v1/demo/checkout/verifications"),
    );
    const verificationRequest = verificationCall?.[1];
    expect(verificationRequest?.body).toContain("razorpay_signature");
    expect(verificationRequest?.headers).not.toHaveProperty("Authorization");
  });

  it("verifies a failed Razorpay payment before tracking revenue recovery", async () => {
    let failedHandler:
      | ((failure: { error: { metadata: { order_id: string; payment_id: string } } }) => void)
      | undefined;
    window.Razorpay = class {
      open() {}
      on(
        _event: "payment.failed",
        handler: (failure: {
          error: { metadata: { order_id: string; payment_id: string } };
        }) => void,
      ) {
        failedHandler = handler;
      }
    } as never;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/demo/session")) return jsonResponse(judgeSession);
      if (url.endsWith("/api/readiness")) return jsonResponse(systemReadiness);
      if (url.endsWith("/v1/demo/checkout/orders")) return jsonResponse(prepared, 201);
      if (url.endsWith("/v1/demo/checkout/failures")) {
        return jsonResponse({
          evidence_id: "22222222-2222-4222-8222-222222222222",
          evidence_hash: "c".repeat(64),
          verified_at: "2026-08-25T08:00:00Z",
          payment: {
            payment_id: "pay_failed",
            order_id: "order_123",
            status: "failed",
            amount_subunits: 1000,
            currency: "INR",
            captured: false,
          },
        });
      }
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<TestCheckout scenario="failed" />);

    await screen.findByText(/Secure session/i);
    fireEvent.click(screen.getByRole("button", { name: "Open Razorpay and trigger failure" }));
    await waitFor(() => expect(failedHandler).toBeDefined());
    failedHandler?.({
      error: { metadata: { order_id: "order_123", payment_id: "pay_failed" } },
    });

    expect(await screen.findByRole("heading", { name: "Verified failure" })).toBeInTheDocument();
    expect(screen.getAllByText("failed")).toHaveLength(2);
    expect(screen.getByText(/checked against Razorpay/i)).toBeInTheDocument();
    expect(screen.getByText("Waiting for deterministic detection")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/v1/demo/checkout/failures")),
    ).toBe(true);
  });

  it("advances the exact payment into its live diagnosed incident", async () => {
    let handler: ((proof: object) => void) | undefined;
    window.Razorpay = class {
      constructor(options: { handler: (proof: object) => void }) {
        handler = options.handler;
      }
      open() {}
    } as never;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/demo/session")) return jsonResponse(judgeSession);
      if (url.endsWith("/api/readiness")) return jsonResponse(systemReadiness);
      if (url.endsWith("/v1/demo/checkout/orders")) return jsonResponse(prepared, 201);
      if (url.endsWith("/v1/demo/checkout/verifications")) {
        return jsonResponse({
          verification_id: "22222222-2222-4222-8222-222222222222",
          verification_hash: "a".repeat(64),
          payment: {
            payment_id: "pay_123",
            order_id: "order_123",
            status: "authorized",
            amount_subunits: 1000,
            currency: "INR",
            captured: false,
          },
        });
      }
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({
          items: [
            {
              incident_id: "33333333-3333-4333-8333-333333333333",
              affected_entity: { entity_type: "payment", entity_id: "pay_123" },
            },
          ],
          next_cursor: null,
        });
      }
      if (url.endsWith("/actions")) return jsonResponse([]);
      if (url.includes("/v1/operator/incidents/33333333-3333-4333-8333-333333333333")) {
        return jsonResponse({
          incident: {
            incident_id: "33333333-3333-4333-8333-333333333333",
            status: "diagnosed",
            incident_type: "authorized_not_captured",
          },
          revisions: [],
          latest_diagnosis: {
            diagnosis: {
              effective_decision: {
                summary: "Capture was not completed for the verified authorization.",
                confidence: 1,
              },
            },
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<DemoCheckoutPage />);

    await screen.findByText(/Secure session/i);
    fireEvent.click(screen.getByRole("button", { name: "Authorize ₹10 in Razorpay" }));
    await waitFor(() => expect(handler).toBeDefined());
    handler?.({
      razorpay_order_id: "order_123",
      razorpay_payment_id: "pay_123",
      razorpay_signature: "b".repeat(64),
    });

    expect(
      await screen.findAllByText("Capture was not completed for the verified authorization."),
    ).toHaveLength(2);
    expect(screen.getByText(/Confidence\s+100%/i)).toBeInTheDocument();
    expect(screen.getByText("Payment stopped before capture")).toBeInTheDocument();
    expect(screen.getByText("Break located")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare bounded recovery" })).toBeEnabled();
  });

  it("restores the active transaction after leaving and returning to Run Payment", async () => {
    window.sessionStorage.setItem(
      "chakravyuh:active-verification:v1",
      JSON.stringify({
        session_id: "judge-session-1234",
        verification: {
          verification_id: "22222222-2222-4222-8222-222222222222",
          verification_hash: "a".repeat(64),
          payment: {
            payment_id: "pay_persisted",
            order_id: "order_persisted",
            status: "authorized",
            amount_subunits: 1000,
            currency: "INR",
            captured: false,
          },
        },
      }),
    );
    window.Razorpay = class {
      open() {}
    } as never;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/demo/session")) return jsonResponse(judgeSession);
      if (url.endsWith("/api/readiness")) return jsonResponse(systemReadiness);
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<DemoCheckoutPage />);

    expect(await screen.findByText("Active transaction")).toBeInTheDocument();
    expect(await screen.findByText(/Secure session/i)).toBeInTheDocument();
    expect(screen.getAllByText("pay_persisted").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Start another transaction" })).toBeEnabled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it("waits for signed webhooks before claiming recovery", async () => {
    let handler: ((proof: object) => void) | undefined;
    window.Razorpay = class {
      constructor(options: { handler: (proof: object) => void }) {
        handler = options.handler;
      }
      open() {}
    } as never;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/demo/session")) return jsonResponse(judgeSession);
      if (url.endsWith("/api/readiness")) return jsonResponse(systemReadiness);
      if (url.endsWith("/v1/demo/checkout/orders")) return jsonResponse(prepared, 201);
      if (url.endsWith("/v1/demo/checkout/verifications")) {
        return jsonResponse({
          verification_id: "22222222-2222-4222-8222-222222222222",
          verification_hash: "a".repeat(64),
          payment: {
            payment_id: "pay_123",
            order_id: "order_123",
            status: "authorized",
            amount_subunits: 1000,
            currency: "INR",
            captured: false,
          },
        });
      }
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({
          items: [
            {
              incident_id: "33333333-3333-4333-8333-333333333333",
              affected_entity: { entity_type: "payment", entity_id: "pay_123" },
            },
          ],
          next_cursor: null,
        });
      }
      if (url.endsWith("/actions")) {
        return jsonResponse([
          {
            proposal: {
              proposal_id: "44444444-4444-4444-8444-444444444444",
              target: { entity_type: "payment", entity_id: "pay_123" },
              amount: { amount_subunits: 1000, currency: "INR" },
            },
            approvals: [{ decision: "approved" }],
            execution_status: "succeeded",
            latest_result: {
              outcome: "succeeded",
              provider_state: {
                amount: { amount_subunits: 1000, currency: "INR" },
              },
            },
          },
        ]);
      }
      if (url.includes("/v1/operator/incidents/33333333-3333-4333-8333-333333333333")) {
        return jsonResponse({
          incident: {
            incident_id: "33333333-3333-4333-8333-333333333333",
            status: "diagnosed",
            incident_type: "authorized_not_captured",
          },
          revisions: [],
          latest_diagnosis: {
            diagnosis: {
              effective_decision: { summary: "Capture not completed.", confidence: 1 },
            },
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<DemoCheckoutPage />);

    await screen.findByText(/Secure session/i);
    fireEvent.click(screen.getByRole("button", { name: "Authorize ₹10 in Razorpay" }));
    await waitFor(() => expect(handler).toBeDefined());
    handler?.({
      razorpay_order_id: "order_123",
      razorpay_payment_id: "pay_123",
      razorpay_signature: "b".repeat(64),
    });

    expect(
      await screen.findByText("Capture accepted. Awaiting provider confirmation."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Governed")).toHaveLength(2);
    expect(screen.queryByText("Provider-confirmed recovery")).not.toBeInTheDocument();

    const callsBeforeRefresh = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeRefresh));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/v1/demo/checkout/verifications/pay_123/reconcile"),
      ),
    ).toBe(false);
  });

  it("fails closed when the hosted script loads without its Checkout constructor", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input).endsWith("/api/readiness")
        ? jsonResponse(systemReadiness)
        : jsonResponse(judgeSession),
    );
    render(<DemoCheckoutPage />);
    const script = document.querySelector(
      'script[src="https://checkout.razorpay.com/v1/checkout.js"]',
    );
    expect(script).not.toBeNull();
    fireEvent.load(script as HTMLScriptElement);

    expect(
      await screen.findByText(
        "Razorpay Checkout loaded without initializing. Reload and try again.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Authorize ₹10 in Razorpay" })).toBeDisabled();
  });
});

const judgeSession = {
  session_id: "judge-session-1234",
  expires_at: "2026-08-25T09:00:00Z",
  remaining_mutations: 24,
};

const systemReadiness = {
  status: "ready",
  checked_at: "2026-08-25T08:30:00Z",
  checks: [{ id: "api", label: "Recovery API", status: "ready", detail: "Serving requests" }],
};

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
