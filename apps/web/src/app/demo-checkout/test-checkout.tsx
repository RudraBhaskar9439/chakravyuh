"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const checkoutScript = "https://checkout.razorpay.com/v1/checkout.js";

type PreparedCheckout = {
  public_key_id: string;
  display_name: string;
  description: string;
  order: {
    checkout_id: string;
    order_id: string;
    amount_subunits: number;
    currency: string;
    expires_at: string;
  };
};

type CheckoutProof = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

type Verification = {
  verification_id: string;
  verification_hash: string;
  payment: {
    payment_id: string;
    order_id: string;
    status: string;
    amount_subunits: number;
    currency: string;
    captured: boolean;
  };
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: (proof: CheckoutProof) => void;
  modal: { ondismiss: () => void };
  theme: { color: string };
};

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => { open: () => void };
  }
}

export function TestCheckout() {
  const [token, setToken] = useState("");
  const [scriptReady, setScriptReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [prepared, setPrepared] = useState<PreparedCheckout | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (window.Razorpay) {
      setScriptReady(true);
      return;
    }
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${checkoutScript}"]`);
    const script = existing ?? document.createElement("script");
    const onLoad = () => {
      if (window.Razorpay) {
        setScriptReady(true);
      } else {
        setError("Razorpay Checkout loaded without initializing. Reload and try again.");
      }
    };
    const onError = () => setError("Razorpay Checkout could not be loaded.");
    script.addEventListener("load", onLoad);
    script.addEventListener("error", onError);
    if (!existing) {
      script.src = checkoutScript;
      script.async = true;
      document.head.appendChild(script);
    }
    return () => {
      script.removeEventListener("load", onLoad);
      script.removeEventListener("error", onError);
    };
  }, []);

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim() || busy) return;
    if (!scriptReady || !window.Razorpay) {
      setError("Razorpay Checkout is still loading. Try again in a moment.");
      return;
    }
    setBusy(true);
    setError(null);
    setVerification(null);
    try {
      const next = await fetchJson<PreparedCheckout>("/v1/demo/checkout/orders", token, {
        method: "POST",
      });
      setPrepared(next);
      const checkout = new window.Razorpay({
        key: next.public_key_id,
        amount: next.order.amount_subunits,
        currency: next.order.currency,
        name: next.display_name,
        description: next.description,
        order_id: next.order.order_id,
        handler: (proof) => void verify(proof),
        modal: {
          ondismiss: () => setBusy(false),
        },
        theme: { color: "#e6aa4c" },
      });
      checkout.open();
    } catch (failure) {
      setError(message(failure));
      setBusy(false);
    }
  }

  async function verify(proof: CheckoutProof) {
    try {
      const verified = await fetchJson<Verification>("/v1/demo/checkout/verifications", token, {
        method: "POST",
        body: proof,
      });
      setVerification(verified);
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="checkoutShell">
      <header className="checkoutTopbar">
        <Link href="/">← Operator console</Link>
        <span>Razorpay Test Mode only</span>
      </header>
      <section className="checkoutHero">
        <p className="eyebrow">Phase 11 · Real provider proof</p>
        <h1>Create the incident.</h1>
        <p>
          Authorize one fixed ₹10 Test Mode payment. Chakravyuh leaves it uncaptured, detects the
          lifecycle violation, and recovers it through dual control.
        </p>
      </section>

      <section className="checkoutGrid">
        <article className="checkoutCard">
          <span className="stepNumber">01</span>
          <h2>Authorize ₹10</h2>
          <p>The order is created server-side with manual capture. No real money moves.</p>
          <form onSubmit={begin}>
            <label htmlFor="checkout-token">Scoped demo operator token</label>
            <input
              autoComplete="off"
              id="checkout-token"
              onChange={(event) => setToken(event.target.value)}
              placeholder="Token remains only in memory"
              type="password"
              value={token}
            />
            <button disabled={busy || !scriptReady || !token.trim()} type="submit">
              {busy ? "Waiting for authorization…" : "Open Razorpay Test Checkout"}
            </button>
          </form>
          <small>{scriptReady ? "Checkout securely loaded." : "Loading Razorpay Checkout…"}</small>
        </article>

        <article className="checkoutCard proofCard">
          <span className="stepNumber">02</span>
          <h2>Verified authorization</h2>
          {verification ? (
            <div className="proofResult" role="status">
              <strong>Ready for recovery</strong>
              <dl>
                <div>
                  <dt>Payment</dt>
                  <dd>{verification.payment.payment_id}</dd>
                </div>
                <div>
                  <dt>Provider state</dt>
                  <dd>{verification.payment.status}</dd>
                </div>
                <div>
                  <dt>Amount</dt>
                  <dd>{formatInr(verification.payment.amount_subunits)}</dd>
                </div>
                <div>
                  <dt>Captured</dt>
                  <dd>{String(verification.payment.captured)}</dd>
                </div>
                <div>
                  <dt>Proof hash</dt>
                  <dd>{shortHash(verification.verification_hash)}</dd>
                </div>
              </dl>
              <p>Do not capture this payment in Razorpay. Continue in the operator console.</p>
            </div>
          ) : (
            <p className="proofPlaceholder">
              The exact payment ID, authorized state, amount, order link and tamper-evident proof
              will appear here after Checkout succeeds.
            </p>
          )}
          {prepared && !verification ? (
            <p className="orderHint">Order prepared: {prepared.order.order_id}</p>
          ) : null}
        </article>
      </section>

      {error ? (
        <div className="errorBanner checkoutError" role="alert">
          {error}
        </div>
      ) : null}
    </main>
  );
}

async function fetchJson<T>(
  path: string,
  token: string,
  options: { method: "POST"; body?: object },
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "X-Request-ID": crypto.randomUUID(),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { code?: string } | string;
    } | null;
    const code = typeof payload?.detail === "object" ? payload.detail.code : null;
    throw new Error(code ? humanizeCode(code) : `Request failed with status ${response.status}.`);
  }
  return (await response.json()) as T;
}

function humanizeCode(code: string): string {
  return code.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "The Test Checkout could not complete.";
}

function shortHash(hash: string): string {
  return `${hash.slice(0, 12)}…${hash.slice(-8)}`;
}

function formatInr(amountSubunits: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  }).format(amountSubunits / 100);
}
