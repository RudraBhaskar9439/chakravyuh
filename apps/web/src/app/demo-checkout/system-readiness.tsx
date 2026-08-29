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
    try {
      const response = await fetch("/api/readiness", { cache: "no-store" });
      const payload = (await response.json()) as Readiness;
      setReadiness(payload);
      onReadyChange(payload.status === "ready");
    } catch {
      setReadiness(null);
      onReadyChange(false);
    } finally {
      setChecking(false);
    }
  }, [onReadyChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section className="systemReadiness" aria-labelledby="system-readiness-title">
      <header>
        <div>
          <p className="eyebrow">Live preflight</p>
          <h2 id="system-readiness-title">System readiness</h2>
        </div>
        <button disabled={checking} onClick={() => void refresh()} type="button">
          {checking ? "Checking…" : "Run checks again"}
        </button>
      </header>
      {readiness ? (
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
      ) : (
        <p className="readinessUnavailable">
          Readiness could not be established. No transaction can start.
        </p>
      )}
    </section>
  );
}
