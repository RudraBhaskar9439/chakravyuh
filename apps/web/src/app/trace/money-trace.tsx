"use client";

import { type FormEvent, useState } from "react";

import type { IncidentPage, IncidentSummary } from "../operator-types";

type ScaleReport = {
  reportSha256: string;
  proofRoots: Record<string, string>;
};

type TraceResult =
  | { kind: "incident"; incident: IncidentSummary }
  | { kind: "scale"; label: string; hash: string };

export function MoneyTrace() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<TraceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (!supported(value)) {
      setError("Enter a pay_, order_, incident UUID, or 64-character SHA-256 value.");
      setResult(null);
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (sha256(value)) {
        const report = await fetchJson<ScaleReport>("/api/evidence/scale", false);
        if (report.reportSha256 === value) {
          setResult({ kind: "scale", label: "Scale evidence report", hash: value });
          return;
        }
        const proof = Object.entries(report.proofRoots).find(([, hash]) => hash === value);
        if (proof) {
          setResult({ kind: "scale", label: humanize(proof[0]), hash: value });
          return;
        }
        throw new Error("No sealed scale report matches this SHA-256 value.");
      }

      const page = await fetchJson<IncidentPage>("/v1/operator/incidents?limit=100");
      const incident = page.items.find((item) => matches(item, value));
      if (!incident && value.startsWith("pay_")) {
        await fetchJson(`/v1/demo/checkout/verifications/${value}/proof`);
        window.location.assign(`/recoveries/verified?payment_id=${encodeURIComponent(value)}`);
        return;
      }
      if (!incident) throw new Error("No indexed money journey matches this identifier.");
      if (incident.status === "resolved" && incident.affected_entity.entity_id.startsWith("pay_")) {
        window.location.assign(
          `/recoveries/verified?payment_id=${encodeURIComponent(incident.affected_entity.entity_id)}`,
        );
        return;
      }
      setResult({ kind: "incident", incident });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Money Trace lookup failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="traceShell">
      <section className="traceHero">
        <p className="eyebrow">Universal Money Trace</p>
        <h1>One identifier. The complete money path.</h1>
        <p>
          Resolve provider payments, merchant orders, recovery incidents and sealed evidence without
          handling an operator credential.
        </p>
        <form onSubmit={search}>
          <label htmlFor="money-trace-query">Payment, order, incident or SHA-256</label>
          <div>
            <input
              autoComplete="off"
              id="money-trace-query"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="pay_…  order_…  UUID  or evidence hash"
              spellCheck={false}
              value={query}
            />
            <button disabled={busy || !query.trim()} type="submit">
              {busy ? "Tracing…" : "Trace money"}
            </button>
          </div>
        </form>
        {error ? (
          <p className="traceError" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      <section className="traceGuidance" aria-label="Supported identifiers">
        <article>
          <span>pay_</span>
          <strong>Provider payment</strong>
          <p>Opens the exact live recovery proof.</p>
        </article>
        <article>
          <span>order_</span>
          <strong>Merchant order</strong>
          <p>Resolves its connected payment incident.</p>
        </article>
        <article>
          <span>UUID</span>
          <strong>Recovery incident</strong>
          <p>Shows current state, risk and diagnosis.</p>
        </article>
        <article>
          <span>SHA-256</span>
          <strong>Evidence commitment</strong>
          <p>Finds the sealed measurement report.</p>
        </article>
      </section>

      {result?.kind === "incident" ? <IncidentResult incident={result.incident} /> : null}
      {result?.kind === "scale" ? <ScaleResult result={result} /> : null}
    </main>
  );
}

function IncidentResult({ incident }: { incident: IncidentSummary }) {
  return (
    <section className="traceResult" aria-live="polite">
      <p className="eyebrow">Money journey found</p>
      <h2>{humanize(incident.incident_type)}</h2>
      <dl>
        <div>
          <dt>Payment</dt>
          <dd>{incident.affected_entity.entity_id}</dd>
        </div>
        <div>
          <dt>Order</dt>
          <dd>{incident.correlation_id}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{humanize(incident.status)}</dd>
        </div>
        <div>
          <dt>Amount at risk</dt>
          <dd>{formatMoney(incident.amount_at_risk)}</dd>
        </div>
      </dl>
      <p>
        This journey is indexed, but provider-confirmed proof is available only after the bounded
        recovery completes.
      </p>
      <a href="/payments/authorize">Run a complete verified recovery →</a>
    </section>
  );
}

function ScaleResult({ result }: { result: Extract<TraceResult, { kind: "scale" }> }) {
  return (
    <section className="traceResult" aria-live="polite">
      <p className="eyebrow">Evidence commitment found</p>
      <h2>{result.label}</h2>
      <code>{result.hash}</code>
      <p>The value is bound into Chakravyuh’s content-addressed scale evidence report.</p>
      <a href="/judge">Open verified scale evidence →</a>
    </section>
  );
}

function matches(item: IncidentSummary, value: string): boolean {
  return (
    item.incident_id === value ||
    item.correlation_id === value ||
    item.affected_entity.entity_id === value
  );
}

function supported(value: string): boolean {
  return /^(pay|order)_[A-Za-z0-9]+$/.test(value) || uuid(value) || sha256(value);
}

function uuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function sha256(value: string): boolean {
  return /^[0-9a-f]{64}$/i.test(value);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatMoney(value: IncidentSummary["amount_at_risk"]): string {
  if (!value) return "Not recorded";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: value.currency }).format(
    value.amount_subunits / 100,
  );
}

async function fetchJson<T>(path: string, demo = true): Promise<T> {
  const url = demo ? `/api/demo${path}` : path;
  let response = await fetch(url, {
    headers: { "X-Request-ID": crypto.randomUUID() },
    cache: "no-store",
  });
  if (response.status === 429) {
    const seconds = Number(response.headers.get("Retry-After"));
    const delay = Number.isFinite(seconds) ? seconds * 1_000 : 1_000;
    await new Promise((resolve) =>
      window.setTimeout(resolve, Math.min(Math.max(delay, 250), 5_000)),
    );
    response = await fetch(url, {
      headers: { "X-Request-ID": crypto.randomUUID() },
      cache: "no-store",
    });
  }
  if (!response.ok) throw new Error(`Lookup failed with status ${response.status}.`);
  return (await response.json()) as T;
}
