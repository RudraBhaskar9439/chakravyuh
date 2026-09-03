"use client";

import { useCallback, useEffect, useState } from "react";

type Readiness = {
  status: "ready" | "degraded";
  checked_at: string;
  checks: Array<{
    id: string;
    label: string;
    status: "ready" | "unavailable";
    detail: string;
  }>;
};

export function SystemReadiness({ onReadyChange }: { onReadyChange: (ready: boolean) => void }) {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    setChecking(true);
    onReadyChange(false);
    let latest: Readiness | null = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch("/api/readiness", { cache: "no-store" });
        latest = (await response.json()) as Readiness;
        setReadiness(latest);
        if (response.ok && latest.status === "ready") {
          onReadyChange(true);
          setChecking(false);
          return;
        }
      } catch {
        latest = null;
      }
      if (attempt < 2) await delay(1_000 * (attempt + 1));
    }
    setReadiness(latest);
    onReadyChange(false);
    setChecking(false);
  }, [onReadyChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section
      className={`systemReadiness ${readiness?.status === "ready" ? "ready" : "degraded"}`}
      aria-labelledby="system-readiness-title"
    >
      <header>
        <div className="readinessSummary">
          <span aria-hidden="true" />
          <div>
            <h2 id="system-readiness-title">
              {checking
                ? "Connecting to recovery services"
                : readiness?.status === "ready"
                  ? "All systems operational"
                  : "Recovery services need attention"}
            </h2>
            <p>
              {checking
                ? "Securely waking and verifying the provider, ledger, graph, and policy services."
                : readiness?.status === "ready"
                  ? "Razorpay, evidence storage, policy controls, and recovery workers are ready."
                  : "No payment can start until every required service is available."}
            </p>
          </div>
        </div>
        <button disabled={checking} onClick={() => void refresh()} type="button">
          {checking ? "Connecting…" : "Refresh status"}
        </button>
      </header>
      {readiness ? <ReadinessDetails readiness={readiness} /> : null}
      {!checking && !readiness ? (
        <p className="readinessUnavailable">
          The recovery API could not be reached after three attempts. Refresh the status to try
          again.
        </p>
      ) : null}
    </section>
  );
}

function ReadinessDetails({ readiness }: { readiness: Readiness }) {
  const unavailable = readiness.checks.filter((item) => item.status === "unavailable");
  return (
    <details className="readinessDetails" open={unavailable.length > 0}>
      <summary>
        {unavailable.length > 0
          ? `${unavailable.length} service ${unavailable.length === 1 ? "is" : "are"} unavailable`
          : `View ${readiness.checks.length} verified services`}
      </summary>
      <div className="readinessGrid">
        {readiness.checks.map((item) => (
          <article className={item.status} key={item.id}>
            <span aria-hidden="true" />
            <div>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </div>
          </article>
        ))}
      </div>
    </details>
  );
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
