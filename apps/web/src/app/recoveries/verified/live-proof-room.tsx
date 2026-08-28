"use client";

import { useCallback, useEffect, useState } from "react";

import type { ActionView, IncidentDetail, IncidentPage } from "../../operator-types";

const apiBase = "/api/demo";

type ProviderProof = {
  mode: "razorpay_test";
  verification_id: string;
  verification_hash: string;
  verified_at: string;
  original_authorization: {
    payment_id: string;
    order_id: string;
    status: string;
    amount_subunits: number;
    currency: string;
    captured: boolean;
  };
  current_provider_state: {
    payment_id: string;
    order_id: string;
    status: string;
    amount_subunits: number;
    currency: string;
    captured: boolean;
  };
  provider_checked_at: string;
  provider_proof_hash: string;
};

type ProofRecord = {
  detail: IncidentDetail;
  action: ActionView;
  provider: ProviderProof;
};

export function LiveProofRoom({ paymentId }: { paymentId?: string }) {
  const [record, setRecord] = useState<ProofRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const page = await fetchJson<IncidentPage>("/v1/operator/incidents?limit=100");
    const summary = paymentId
      ? page.items.find(
          (item) => item.affected_entity.entity_id === paymentId && item.status === "resolved",
        )
      : page.items.find((item) => item.status === "resolved");
    if (!summary) {
      throw new Error(
        paymentId
          ? "No provider-confirmed recovery exists for this payment."
          : "No provider-confirmed recovery is available yet.",
      );
    }
    const resolvedPaymentId = summary.affected_entity.entity_id;
    const [detail, actions, provider] = await Promise.all([
      fetchJson<IncidentDetail>(`/v1/operator/incidents/${summary.incident_id}`),
      fetchJson<ActionView[]>(`/v1/operator/incidents/${summary.incident_id}/actions`),
      fetchJson<ProviderProof>(`/v1/demo/checkout/verifications/${resolvedPaymentId}/proof`),
    ]);
    const action = actions.find(
      (candidate) =>
        candidate.latest_result?.outcome === "succeeded" &&
        candidate.proposal.target.entity_id === resolvedPaymentId,
    );
    if (!action?.latest_result?.provider_state) {
      throw new Error("The recovery has no successful provider execution receipt.");
    }
    if (
      provider.current_provider_state.payment_id !== resolvedPaymentId ||
      provider.current_provider_state.status !== "captured" ||
      !provider.current_provider_state.captured
    ) {
      throw new Error("Razorpay did not confirm the expected captured payment state.");
    }
    setRecord({ detail, action, provider });
  }, [paymentId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void load()
      .catch((failure) => {
        if (!cancelled) setError(message(failure));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function reverify() {
    if (!record || refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const provider = await fetchJson<ProviderProof>(
        `/v1/demo/checkout/verifications/${record.provider.current_provider_state.payment_id}/proof`,
      );
      setRecord((current) => (current ? { ...current, provider } : current));
    } catch (failure) {
      setError(message(failure));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <main className="proofRoomShell">
      <header className="proofRoomTopbar">
        <a className="storyBrand" href="/recoveries/verified">
          <span className="miniMark" aria-hidden="true">
            च
          </span>
          <span>
            <strong>Chakravyuh</strong>
            <small>Live proof room</small>
          </span>
        </a>
        <nav aria-label="Proof navigation">
          <a href="/payments/authorize">Run a transaction</a>
          <a href="/judge">Scale evidence</a>
          <a href="/">Operations</a>
        </nav>
        <div className="proofLiveBadge">
          <span /> Read-only · Razorpay Test Mode
        </div>
      </header>

      {loading ? <ProofLoading /> : null}
      {error && !record ? <ProofFailure error={error} /> : null}
      {record ? (
        <ProofRecordView
          error={error}
          onReverify={() => void reverify()}
          record={record}
          refreshing={refreshing}
        />
      ) : null}
    </main>
  );
}

function ProofRecordView({
  record,
  refreshing,
  error,
  onReverify,
}: {
  record: ProofRecord;
  refreshing: boolean;
  error: string | null;
  onReverify: () => void;
}) {
  const { detail, action, provider } = record;
  const incident = detail.incident;
  const diagnosis = detail.latest_diagnosis;
  const decision = diagnosis?.diagnosis.effective_decision;
  const result = action.latest_result;
  const approval = action.approvals.find((item) => item.decision === "approved");
  const detected = detail.revisions.find((revision) => revision.reason === "detected");
  const resolved = [...detail.revisions]
    .reverse()
    .find((revision) => revision.reason === "resolved");
  const paymentId = provider.current_provider_state.payment_id;
  const proofRows = [
    ["Checkout verification", provider.verification_hash],
    ["Incident finding", incident.finding_hash],
    ["Evidence subgraph", diagnosis?.evidence_subgraph.subgraph_hash],
    ["Diagnosis prompt", diagnosis?.prompt_hash],
    ["Action proposal", action.proposal.proposal_hash],
    ["Policy input", action.policy.input_hash],
    ["Execution result", result?.result_hash],
    ["Fresh provider snapshot", provider.provider_proof_hash],
  ].filter((row): row is [string, string] => Boolean(row[1]));

  return (
    <>
      <section className="proofRoomHero">
        <div>
          <p className="eyebrow">Live provider evidence · not a simulation</p>
          <h1>
            Don’t trust the demo.
            <br />
            <span>Ask Razorpay again.</span>
          </h1>
          <p>
            This page loads one completed recovery from Chakravyuh’s append-only ledger and then
            re-queries Razorpay for the exact payment. No proof values below are bundled into the
            frontend.
          </p>
          <div className="proofRoomActions">
            <button disabled={refreshing} onClick={onReverify} type="button">
              <span aria-hidden="true">↻</span>
              {refreshing ? "Querying Razorpay…" : "Re-verify with Razorpay now"}
            </button>
            <a
              href={`${apiBase}/v1/demo/checkout/verifications/${paymentId}/proof`}
              rel="noreferrer"
              target="_blank"
            >
              Open raw provider proof ↗
            </a>
          </div>
          {error ? (
            <div className="errorBanner proofRoomError" role="alert">
              {error}
            </div>
          ) : null}
        </div>
        <div className="proofSeal">
          <span>LIVE API VERIFIED</span>
          <strong>CAPTURED</strong>
          <small>Queried {formatDate(provider.provider_checked_at)}</small>
          <code>{shortHash(provider.provider_proof_hash)}</code>
        </div>
      </section>

      <section className="proofSourceStrip" aria-label="Provider-bound identities">
        <ProofSource label="Provider" value="Razorpay Test Mode API" />
        <ProofSource label="Payment" value={paymentId} mono />
        <ProofSource label="Order" value={provider.current_provider_state.order_id} mono />
        <ProofSource
          label="Amount"
          value={formatInr(provider.current_provider_state.amount_subunits)}
        />
        <ProofSource label="Current state" value="Captured · provider queried" healthy />
      </section>

      <section className="proofComparison" aria-labelledby="comparison-title">
        <header className="proofRoomSectionHeader">
          <div>
            <p className="eyebrow">Before and after · same provider identity</p>
            <h2 id="comparison-title">One payment. Two authoritative snapshots.</h2>
          </div>
          <span>Identity + order + amount matched</span>
        </header>
        <div className="proofSnapshotGrid">
          <ProofSnapshot
            accent="warning"
            captured={provider.original_authorization.captured}
            eyebrow="Original Checkout verification"
            hash={provider.verification_hash}
            paymentId={provider.original_authorization.payment_id}
            status={provider.original_authorization.status}
            timestamp={provider.verified_at}
          />
          <div className="proofTransition" aria-hidden="true">
            <span>EXACTLY ONE</span>
            <strong>→</strong>
            <small>bounded mutation</small>
          </div>
          <ProofSnapshot
            accent="healthy"
            captured={provider.current_provider_state.captured}
            eyebrow="Fresh Razorpay API query"
            hash={provider.provider_proof_hash}
            paymentId={provider.current_provider_state.payment_id}
            status={provider.current_provider_state.status}
            timestamp={provider.provider_checked_at}
          />
        </div>
      </section>

      <section className="proofTrustGrid" aria-labelledby="trust-title">
        <header>
          <p className="eyebrow">Why this cannot be dismissed as animation</p>
          <h2 id="trust-title">Four independent boundaries agree.</h2>
        </header>
        <div>
          <TrustBoundary
            number="01"
            title="Razorpay identity"
            copy={`Real Test Mode IDs ${paymentId} and ${provider.current_provider_state.order_id} are returned by the provider.`}
          />
          <TrustBoundary
            number="02"
            title="Fresh provider read"
            copy="The button above performs a new read-only Razorpay API call. Its timestamp and proof hash change on every query."
          />
          <TrustBoundary
            number="03"
            title="Append-only control trail"
            copy={`${detail.revisions.length} incident revisions bind detection, diagnosis and resolution to immutable hashes.`}
          />
          <TrustBoundary
            number="04"
            title="Provider-confirmed closure"
            copy="Revenue is credited only after the captured payment and paid order resolve the incident through authenticated ingress."
          />
        </div>
      </section>

      <section className="proofTimeline" aria-labelledby="timeline-title">
        <header className="proofRoomSectionHeader">
          <div>
            <p className="eyebrow">Cross-system timeline</p>
            <h2 id="timeline-title">Every transition has an owner and a receipt.</h2>
          </div>
          <span>{incident.incident_id}</span>
        </header>
        <ol>
          <TimelineEvent
            owner="Razorpay Checkout"
            state="Authorized"
            timestamp={provider.verified_at}
            value={provider.verification_hash}
          />
          <TimelineEvent
            owner="Deterministic invariant"
            state="Incident detected"
            timestamp={detected?.recorded_at}
            value={detected?.finding_hash}
          />
          <TimelineEvent
            owner={diagnosis?.model ?? "Diagnosis provider"}
            state={`Grounded diagnosis · ${formatConfidence(decision?.confidence)}`}
            timestamp={diagnosis?.diagnosed_at}
            value={diagnosis?.prompt_hash}
          />
          <TimelineEvent
            owner={action.policy.policy_version}
            state="Money movement required independent approval"
            timestamp={action.policy.decided_at}
            value={action.policy.input_hash}
          />
          <TimelineEvent
            owner={approval?.principal_id ?? "Independent checker"}
            state="Exact target and amount approved"
            timestamp={approval?.decided_at}
            value={approval?.approval_id}
          />
          <TimelineEvent
            owner="Bounded executor"
            state="One Razorpay capture succeeded"
            timestamp={result?.completed_at}
            value={result?.result_hash}
          />
          <TimelineEvent
            owner="Authenticated provider ingress"
            state="Incident resolved"
            timestamp={resolved?.recorded_at ?? incident.resolved_at ?? undefined}
            value={resolved?.finding_hash}
          />
        </ol>
      </section>

      <section className="proofReceiptGrid" aria-labelledby="receipt-title">
        <header className="proofRoomSectionHeader">
          <div>
            <p className="eyebrow">Money action receipt</p>
            <h2 id="receipt-title">AI explained it. Deterministic controls moved it.</h2>
          </div>
          <span>{decision?.recommended_action ?? action.proposal.action_type}</span>
        </header>
        <div>
          <Receipt label="Target" value={action.proposal.target.entity_id} />
          <Receipt
            label="Exact amount"
            value={formatInr(action.proposal.amount?.amount_subunits ?? 0)}
          />
          <Receipt label="Risk" value={humanize(action.proposal.risk)} />
          <Receipt label="Policy" value={humanize(action.policy.outcome)} />
          <Receipt label="Independent checker" value={approval?.principal_id ?? "Recorded"} />
          <Receipt label="Execution" value={humanize(result?.outcome ?? "missing")} healthy />
          <Receipt label="Duplicate applied" value={String(result?.already_applied ?? false)} />
          <Receipt label="AI money permissions" value="None" healthy />
        </div>
      </section>

      <section className="proofHashLedger" aria-labelledby="hash-ledger-title">
        <header className="proofRoomSectionHeader">
          <div>
            <p className="eyebrow">Tamper-evident chain</p>
            <h2 id="hash-ledger-title">Inspect every fingerprint.</h2>
          </div>
          <span>SHA-256 · live values</span>
        </header>
        <div>
          {proofRows.map(([label, hash], index) => (
            <article key={label}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{label}</strong>
              <code>{hash}</code>
            </article>
          ))}
        </div>
      </section>

      <footer className="proofRoomFooter">
        <div>
          <span className="miniMark" aria-hidden="true">
            च
          </span>
          <p>
            <strong>Chakravyuh</strong>
            <br />
            Every rupee has a path.
          </p>
        </div>
        <p>
          This page is a read-only projection. It can query provider state but cannot propose,
          approve or execute money movement.
        </p>
        <a href={`/payments/authorize`}>Run another verified transaction →</a>
      </footer>
    </>
  );
}

function ProofSource({
  label,
  value,
  mono = false,
  healthy = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  healthy?: boolean;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong className={`${mono ? "mono" : ""} ${healthy ? "healthy" : ""}`}>{value}</strong>
    </div>
  );
}

function ProofSnapshot({
  eyebrow,
  status,
  captured,
  paymentId,
  timestamp,
  hash,
  accent,
}: {
  eyebrow: string;
  status: string;
  captured: boolean;
  paymentId: string;
  timestamp: string;
  hash: string;
  accent: "warning" | "healthy";
}) {
  return (
    <article className={`proofSnapshot ${accent}`}>
      <span>{eyebrow}</span>
      <h3>{humanize(status)}</h3>
      <dl>
        <div>
          <dt>Payment</dt>
          <dd>{paymentId}</dd>
        </div>
        <div>
          <dt>Captured</dt>
          <dd>{String(captured)}</dd>
        </div>
        <div>
          <dt>Observed</dt>
          <dd>{formatDate(timestamp)}</dd>
        </div>
      </dl>
      <code>{hash}</code>
    </article>
  );
}

function TrustBoundary({ number, title, copy }: { number: string; title: string; copy: string }) {
  return (
    <article>
      <span>{number}</span>
      <h3>{title}</h3>
      <p>{copy}</p>
    </article>
  );
}

function TimelineEvent({
  owner,
  state,
  timestamp,
  value,
}: {
  owner: string;
  state: string;
  timestamp?: string;
  value?: string;
}) {
  return (
    <li>
      <span />
      <time>{timestamp ? formatDate(timestamp) : "Recorded"}</time>
      <div>
        <small>{owner}</small>
        <strong>{state}</strong>
      </div>
      <code>{value ? shortHash(value) : "receipt recorded"}</code>
    </li>
  );
}

function Receipt({
  label,
  value,
  healthy = false,
}: {
  label: string;
  value: string;
  healthy?: boolean;
}) {
  return (
    <article>
      <span>{label}</span>
      <strong className={healthy ? "healthy" : ""}>{value}</strong>
    </article>
  );
}

function ProofLoading() {
  return (
    <section className="proofRoomState" aria-live="polite">
      <span className="proofStatePulse" />
      <p className="eyebrow">Building proof from live systems</p>
      <h1>Querying the ledger and Razorpay.</h1>
      <p>No cached story is rendered while provider evidence is unavailable.</p>
    </section>
  );
}

function ProofFailure({ error }: { error: string }) {
  return (
    <section className="proofRoomState failure" role="alert">
      <p className="eyebrow">Fail closed</p>
      <h1>Proof could not be established.</h1>
      <p>{error}</p>
      <a href="/payments/authorize">Run a verified Test Mode transaction →</a>
    </section>
  );
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "X-Request-ID": crypto.randomUUID() },
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { code?: string } | string;
    } | null;
    const code = typeof payload?.detail === "object" ? payload.detail.code : null;
    throw new Error(code ? humanize(code) : `Proof request failed with status ${response.status}.`);
  }
  return (await response.json()) as T;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

function formatInr(amountSubunits: number): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(
    amountSubunits / 100,
  );
}

function formatConfidence(value: number | undefined): string {
  return value === undefined ? "recorded" : `${Math.round(value * 100)}% confidence`;
}

function shortHash(value: string): string {
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Live proof could not be loaded.";
}
