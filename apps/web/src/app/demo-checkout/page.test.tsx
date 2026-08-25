import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DemoCheckoutPage from "./page";

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
  delete window.Razorpay;
  document.querySelector('script[src="https://checkout.razorpay.com/v1/checkout.js"]')?.remove();
});

describe("Test Checkout", () => {
  it("explains the bounded Test Mode flow before authorization", () => {
    window.Razorpay = class {
      open() {}
    } as never;
    render(<DemoCheckoutPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Create the incident." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/fixed ₹10 Test Mode payment/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Scoped demo operator token")).toHaveAttribute("type", "password");
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
      if (String(input).endsWith("/v1/demo/checkout/orders")) return jsonResponse(prepared, 201);
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
    });
    render(<DemoCheckoutPage />);

    fireEvent.change(screen.getByLabelText("Scoped demo operator token"), {
      target: { value: "demo-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open Razorpay Test Checkout" }));
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

    expect(await screen.findByText("Ready for recovery")).toBeInTheDocument();
    expect(screen.getByText("authorized")).toBeInTheDocument();
    expect(screen.getByText("₹10.00")).toBeInTheDocument();
    expect(screen.getByText(/do not capture/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const verificationRequest = fetchMock.mock.calls[1]?.[1];
    expect(verificationRequest?.body).toContain("razorpay_signature");
    expect(verificationRequest?.headers).toMatchObject({
      Authorization: "Bearer demo-token",
    });
  });

  it("fails closed when the hosted script loads without its Checkout constructor", async () => {
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
    expect(screen.getByRole("button", { name: "Open Razorpay Test Checkout" })).toBeDisabled();
  });
});

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
