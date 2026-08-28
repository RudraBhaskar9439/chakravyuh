"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import type { ActionView, IncidentDetail, IncidentPage } from "../operator-types";
import { LiveMoneyMesh } from "./live-money-mesh";

const apiBase = "/api/demo";
const checkoutScript = "https://checkout.razorpay.com/v1/checkout.js";
const livePollIntervalMs = 10_000;
const hiddenPollIntervalMs = 30_000;

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

const liveStages = [
  { label: "Authorized", detail: "Razorpay accepted the Test Mode payment." },
  { label: "Detected", detail: "The deterministic invariant opened an incident." },
  { label: "Diagnosed", detail: "AI explained the bounded evidence graph." },
  { label: "Governed", detail: "Policy and independent authority bounded the action." },
  { label: "Recovered", detail: "Razorpay confirmed capture and order payment." },
] as const;

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
  const [scriptReady, setScriptReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [prepared, setPrepared] = useState<PreparedCheckout | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveIncident, setLiveIncident] = useState<IncidentDetail | null>(null);
  const [liveActions, setLiveActions] = useState<ActionView[]>([]);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [checkingLiveState, setCheckingLiveState] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

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

  const loadLiveState = useCallback(async (paymentId: string): Promise<number> => {
    setCheckingLiveState(true);
    try {
      const page = await fetchJson<IncidentPage>("/v1/operator/incidents?limit=100");
      const matching = page.items.find(
        (incident) => incident.affected_entity.entity_id === paymentId,
      );
      if (!matching) {
        setTrackingError(null);
        return livePollIntervalMs;
      }
      const [detail, actions] = await Promise.all([
        fetchJson<IncidentDetail>(`/v1/operator/incidents/${matching.incident_id}`),
        fetchJson<ActionView[]>(`/v1/operator/incidents/${matching.incident_id}/actions`),
      ]);
      setLiveIncident(detail);
      setLiveActions(actions);
      setTrackingError(null);
      return livePollIntervalMs;
    } catch (failure) {
      if (failure instanceof ApiRequestError && failure.status === 429) {
        setTrackingError(
          "Live updates paused briefly to respect the API limit. Retrying automatically.",
        );
        return Math.max(failure.retryAfterMs, hiddenPollIntervalMs);
      }
      setTrackingError(message(failure));
      return livePollIntervalMs;
    } finally {
      setCheckingLiveState(false);
    }
  }, []);

  const reconcileLiveState = useCallback(async (paymentId: string) => {
    setCheckingLiveState(true);
    try {
      await fetchJson<Verification>(`/v1/demo/checkout/verifications/${paymentId}/reconcile`, {
        method: "POST",
      });
      setTrackingError(null);
    } catch (failure) {
      setTrackingError(message(failure));
    } finally {
      setCheckingLiveState(false);
    }
  }, []);

  useEffect(() => {
    if (!verification) return;
    let cancelled = false;
    let timer: number | undefined;
    const paymentId = verification.payment.payment_id;

    const schedule = (delay: number) => {
      if (cancelled) return;
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      if (document.visibilityState !== "visible") {
        schedule(hiddenPollIntervalMs);
        return;
      }
      schedule(await loadLiveState(paymentId));
    };
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      if (timer !== undefined) window.clearTimeout(timer);
      void poll();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [loadLiveState, verification]);

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!scriptReady || !window.Razorpay) {
      setError("Razorpay Checkout is still loading. Try again in a moment.");
      return;
    }
    setBusy(true);
    setError(null);
    setVerification(null);
    setLiveIncident(null);
    setLiveActions([]);
    setTrackingError(null);
    try {
      const next = await fetchJson<PreparedCheckout>("/v1/demo/checkout/orders", {
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
      const verified = await fetchJson<Verification>("/v1/demo/checkout/verifications", {
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

  async function runLiveAction(label: string, path: string, body?: object) {
    if (!verification || actionBusy) return;
    setActionBusy(label);
    setTrackingError(null);
    try {
      const next = await fetchJson<ActionView>(path, {
        method: "POST",
        body,
      });
      setLiveActions((current) => [
        next,
        ...current.filter((item) => item.proposal.proposal_id !== next.proposal.proposal_id),
      ]);
      await loadLiveState(verification.payment.payment_id);
    } catch (failure) {
      setTrackingError(message(failure));
    } finally {
      setActionBusy(null);
    }
  }

  return (
    <main className="checkoutShell">
      <header className="checkoutTopbar">
        <a href="/">← Operator console</a>
        <div>
          <a href="/recoveries/verified">Verified recovery</a>
          <span>Razorpay Test Mode only</span>
        </div>
      </header>
      <section className="checkoutHero">
        <p className="eyebrow">Live transaction · controlled recovery</p>
        <h1>Follow a payment end to end.</h1>
        <p>
          Authorize one fixed ₹10 Razorpay Test Mode payment, then watch that exact payment travel
          through detection, AI diagnosis, independent approval and provider-confirmed recovery.
        </p>
      </section>

      <section className="checkoutGrid">
        <article className="checkoutCard">
          <span className="stepNumber">01</span>
          <h2>Authorize ₹10</h2>
          <p>The order is created server-side with manual capture. No real money moves.</p>
          <form onSubmit={begin}>
            <button disabled={busy || !scriptReady} type="submit">
              {busy ? "Waiting for authorization…" : "Open Razorpay Checkout"}
            </button>
          </form>
          <small>
            {scriptReady
              ? "Checkout securely loaded. Demo authority is scoped server-side."
              : "Loading Razorpay Checkout…"}
          </small>
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
              <p>Do not capture this payment in Razorpay. Its live recovery continues below.</p>
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

      {verification ? (
        <LiveRecovery
          actionBusy={actionBusy}
          actions={liveActions}
          checking={checkingLiveState}
          incident={liveIncident}
          onApprove={(proposalId) =>
            void runLiveAction("approve", `/v1/operator/actions/${proposalId}/decisions`, {
              decision: "approved",
              rationale: "Independently verified live Test Mode recovery evidence.",
            })
          }
          onExecute={(proposalId) =>
            void runLiveAction("execute", `/v1/operator/actions/${proposalId}/execute`)
          }
          onPropose={(incidentId) =>
            void runLiveAction("propose", `/v1/operator/incidents/${incidentId}/actions/proposals`)
          }
          onRefresh={() => {
            const captureAccepted = liveActions[0]?.latest_result?.outcome === "succeeded";
            void (captureAccepted
              ? loadLiveState(verification.payment.payment_id)
              : reconcileLiveState(verification.payment.payment_id));
          }}
          trackingError={trackingError}
          verification={verification}
        />
      ) : null}
    </main>
  );
}

function LiveRecovery({
  verification,
  incident,
  actions,
  checking,
  trackingError,
  actionBusy,
  onRefresh,
  onPropose,
  onApprove,
  onExecute,
}: {
  verification: Verification;
  incident: IncidentDetail | null;
  actions: ActionView[];
  checking: boolean;
  trackingError: string | null;
  actionBusy: string | null;
  onRefresh: () => void;
  onPropose: (incidentId: string) => void;
  onApprove: (proposalId: string) => void;
  onExecute: (proposalId: string) => void;
}) {
  const action = actions[0] ?? null;
  const approved = action?.approvals.some((approval) => approval.decision === "approved") ?? false;
  const rejected = action?.approvals.some((approval) => approval.decision === "rejected") ?? false;
  const succeeded = action?.latest_result?.outcome === "succeeded";
  const recovered = incident?.incident.status === "resolved";
  const renewalRequired = action?.expired || action?.stale;
  const activeStage = recovered
    ? 4
    : action
      ? 3
      : incident?.latest_diagnosis
        ? 2
        : incident
          ? 1
          : 0;

  return (
    <section className="liveRecovery" aria-labelledby="live-recovery-title">
      <header className="liveRecoveryHeader">
        <div>
          <p className="eyebrow">Live provider journey</p>
          <h2 id="live-recovery-title">Follow this payment.</h2>
          <p>
            Every stage below is read from the payment’s live PostgreSQL ledger, evidence graph, and
            Razorpay Test Mode result.
          </p>
        </div>
        <div className={recovered ? "liveStatus recovered" : "liveStatus"}>
          <span /> {recovered ? "Provider-confirmed recovery" : "Watching live"}
        </div>
      </header>

      <div className="livePaymentStrip">
        <div>
          <span>Payment</span>
          <strong>{verification.payment.payment_id}</strong>
        </div>
        <div>
          <span>Amount</span>
          <strong>{formatInr(verification.payment.amount_subunits)}</strong>
        </div>
        <div>
          <span>Current state</span>
          <strong>{liveStages[activeStage]?.label}</strong>
        </div>
        <button disabled={checking} onClick={onRefresh} type="button">
          {checking ? "Checking…" : "Refresh now"}
        </button>
      </div>

      <ol className="liveStageRail" aria-label="Live recovery stages">
        {liveStages.map((stage, index) => (
          <li
            aria-current={index === activeStage ? "step" : undefined}
            className={index === activeStage ? "active" : index < activeStage ? "complete" : ""}
            key={stage.label}
          >
            <span>0{index + 1}</span>
            <div>
              <strong>{stage.label}</strong>
              <p>{stage.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      <LiveMoneyMesh
        action={action}
        activeStage={activeStage}
        incident={incident}
        payment={verification.payment}
        recovered={recovered}
      />

      <article className="liveDecisionCard" aria-live="polite">
        <span className="stepNumber">CURRENT</span>
        {activeStage === 0 ? (
          <>
            <h3>Waiting for deterministic detection</h3>
            <p>
              The payment is authorized and deliberately uncaptured. Chakravyuh is evaluating its
              capture-window invariant now.
            </p>
          </>
        ) : null}
        {activeStage === 1 ? (
          <>
            <h3>Incident detected</h3>
            <p>
              {humanizeCode(incident?.incident.incident_type ?? "authorized_not_captured")} ·
              waiting for the bounded AI diagnosis.
            </p>
          </>
        ) : null}
        {activeStage === 2 && incident ? (
          <>
            <h3>{incident.latest_diagnosis?.diagnosis.effective_decision.summary}</h3>
            <p>
              Confidence{" "}
              {formatConfidence(incident.latest_diagnosis?.diagnosis.effective_decision.confidence)}
              . The model cited immutable evidence but cannot execute the recovery.
            </p>
            <button
              className="livePrimaryAction"
              disabled={actionBusy !== null}
              onClick={() => onPropose(incident.incident.incident_id)}
              type="button"
            >
              {actionBusy === "propose" ? "Preparing…" : "Prepare bounded recovery"}
            </button>
          </>
        ) : null}
        {activeStage === 3 && action && renewalRequired && incident ? (
          <>
            <h3>Recovery proposal expired safely</h3>
            <p>
              The approval window closed without moving money. Generate a fresh proposal from the
              current diagnosis before asking the independent checker again.
            </p>
            <button
              className="livePrimaryAction"
              disabled={actionBusy !== null}
              onClick={() => onPropose(incident.incident.incident_id)}
              type="button"
            >
              {actionBusy === "propose" ? "Refreshing…" : "Generate fresh recovery proposal"}
            </button>
          </>
        ) : null}
        {activeStage === 3 && action && !renewalRequired && !approved && !rejected ? (
          <>
            <h3>Independent check required</h3>
            <p>
              Capture exactly{" "}
              {action.proposal.amount
                ? formatInr(action.proposal.amount.amount_subunits)
                : "the verified amount"}
              {" · "}
              {action.proposal.target.entity_id}. The maker cannot approve this action.
            </p>
            <button
              className="livePrimaryAction"
              disabled={actionBusy !== null}
              onClick={() => onApprove(action.proposal.proposal_id)}
              type="button"
            >
              {actionBusy === "approve"
                ? "Requesting independent approval…"
                : "Approve verified recovery"}
            </button>
          </>
        ) : null}
        {activeStage === 3 && action && !renewalRequired && approved && !succeeded ? (
          <>
            <h3>Approved and ready for exact execution</h3>
            <p>
              The executor can invoke only the policy-bound Test Mode capture. Duplicate execution
              is prevented by the stored idempotency key and pre-mutation checkpoint.
            </p>
            <button
              className="livePrimaryAction"
              disabled={actionBusy !== null}
              onClick={() => onExecute(action.proposal.proposal_id)}
              type="button"
            >
              {actionBusy === "execute" ? "Executing…" : "Execute exact Test Mode capture"}
            </button>
          </>
        ) : null}
        {activeStage === 3 && action && !renewalRequired && succeeded && !recovered ? (
          <>
            <h3>Capture accepted. Awaiting provider confirmation.</h3>
            <p>
              Razorpay accepted the exact Test Mode capture. Chakravyuh will credit the recovery
              only after the signed payment.captured and order.paid webhooks resolve this incident.
            </p>
          </>
        ) : null}
        {activeStage === 3 && !renewalRequired && rejected ? (
          <>
            <h3>Recovery rejected safely</h3>
            <p>
              The independent checker rejected this proposal. No provider mutation was attempted.
            </p>
          </>
        ) : null}
        {activeStage === 4 && action ? (
          <div className="liveSuccess">
            <span>✓</span>
            <div>
              <h3>Payment recovered</h3>
              <p>
                Razorpay captured{" "}
                {action.latest_result?.provider_state?.amount
                  ? formatInr(action.latest_result.provider_state.amount.amount_subunits)
                  : "the exact verified amount"}
                . One mutation was recorded and the provider confirmation closed the incident.
              </p>
              {action.latest_result ? <code>{action.latest_result.result_hash}</code> : null}
              <a
                className="liveProofLink"
                href={`/recoveries/verified?payment_id=${verification.payment.payment_id}`}
              >
                Open the judge-verifiable proof room →
              </a>
            </div>
          </div>
        ) : null}
      </article>

      {trackingError ? (
        <div className="errorBanner liveTrackingError" role="alert">
          {trackingError}
        </div>
      ) : null}
      <p className="liveSafetyNote">
        Test Mode only · no live customer funds · scoped credentials remain server-side
      </p>
    </section>
  );
}

async function fetchJson<T>(
  path: string,
  options: { method?: "GET" | "POST"; body?: object } = {},
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method ?? "GET",
    headers: {
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
    const retryAfterMs = parseRetryAfter(response.headers.get("Retry-After"));
    throw new ApiRequestError(
      code ? humanizeCode(code) : `Request failed with status ${response.status}.`,
      response.status,
      retryAfterMs,
    );
  }
  return (await response.json()) as T;
}

class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfterMs: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

function parseRetryAfter(value: string | null): number {
  if (!value) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(value);
  return Number.isNaN(date) ? 0 : Math.max(0, date - Date.now());
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

function formatConfidence(value: number | undefined): string {
  return value === undefined ? "pending" : `${Math.round(value * 100)}%`;
}
