"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { humanize, MoneyGraph } from "./money-graph";
import type {
  IncidentDetail,
  IncidentOverview,
  IncidentPage,
  IncidentSummary,
  Money,
} from "./operator-types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function OperatorDashboard() {
  const [token, setToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [overview, setOverview] = useState<IncidentOverview | null>(null);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadDetail = useCallback(
    async (incidentId: string, signal?: AbortSignal) => {
      setSelectedId(incidentId);
      const next = await fetchJson<IncidentDetail>(
        `/v1/operator/incidents/${incidentId}`,
        token,
        signal,
      );
      setDetail(next);
    },
    [token],
  );

  useEffect(() => {
    if (!connected) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      fetchJson<IncidentOverview>("/v1/operator/overview", token, controller.signal),
      fetchJson<IncidentPage>("/v1/operator/incidents?limit=50", token, controller.signal),
    ])
      .then(async ([nextOverview, page]) => {
        setOverview(nextOverview);
        setIncidents(page.items);
        setNextCursor(page.next_cursor);
        const preferred =
          page.items.find(
            (incident) => incident.status !== "resolved" && incident.diagnosis_disposition !== null,
          ) ??
          page.items.find((incident) => incident.diagnosis_disposition !== null) ??
          page.items[0];
        if (preferred) await loadDetail(preferred.incident_id, controller.signal);
      })
      .catch((failure: unknown) => {
        if (failure instanceof DOMException && failure.name === "AbortError") return;
        setError(
          failure instanceof Error ? failure.message : "The operator console could not load.",
        );
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [connected, loadDetail, token]);

  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) return;
    setConnected(true);
  }

  function endSession() {
    setConnected(false);
    setToken("");
    setOverview(null);
    setIncidents([]);
    setNextCursor(null);
    setDetail(null);
    setSelectedId(null);
    setError(null);
  }

  async function selectIncident(incidentId: string) {
    setLoading(true);
    setError(null);
    try {
      await loadDetail(incidentId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The incident could not load.");
    } finally {
      setLoading(false);
    }
  }

  async function loadMoreIncidents() {
    if (!nextCursor || loading) return;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchJson<IncidentPage>(
        `/v1/operator/incidents?limit=50&cursor=${encodeURIComponent(nextCursor)}`,
        token,
      );
      setIncidents((current) => {
        const existing = new Set(current.map((incident) => incident.incident_id));
        return [
          ...current,
          ...page.items.filter((incident) => !existing.has(incident.incident_id)),
        ];
      });
      setNextCursor(page.next_cursor);
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "The next incident page could not load.",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!connected) {
    return (
      <main className="accessShell">
        <section className="accessCard" aria-labelledby="product-title">
          <div className="brandMark" aria-hidden="true">
            च
          </div>
          <p className="eyebrow">Phase 8 · Operator control plane</p>
          <h1 id="product-title">Chakravyuh</h1>
          <p className="tagline">Every rupee has a path.</p>
          <p className="summary">
            Inspect deterministic incidents, the exact evidence mesh, and every AI guard decision.
            This surface is read-only by design.
          </p>
          <form className="accessForm" onSubmit={connect}>
            <label htmlFor="operator-token">Operator access token</label>
            <div>
              <input
                autoComplete="off"
                id="operator-token"
                onChange={(event) => setToken(event.target.value)}
                placeholder="Paste the token for this session"
                type="password"
                value={token}
              />
              <button type="submit">Open operator console</button>
            </div>
            <p>The token stays in memory and is never stored by this browser.</p>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="consoleShell">
      <header className="topbar">
        <div>
          <span className="miniMark" aria-hidden="true">
            च
          </span>
          <div>
            <p>Chakravyuh</p>
            <span className="productSubtitle">Money path operations</span>
          </div>
        </div>
        <div className="topbarActions">
          <div className="readOnlyBadge">
            <span /> Read-only control plane
          </div>
          <button className="endSession" onClick={endSession} type="button">
            End session
          </button>
        </div>
      </header>

      <section className="overview" aria-label="Incident overview">
        <Metric label="Open incidents" value={openCount(overview)} />
        <Metric label="Amount at risk" value={formatRisk(overview)} />
        <Metric
          label="Awaiting diagnosis"
          value={String(overview?.awaiting_diagnosis_count ?? "—")}
        />
        <Metric
          alert={Boolean(overview?.diagnosis_dead_letter_count)}
          label="Diagnosis dead letters"
          value={String(overview?.diagnosis_dead_letter_count ?? "—")}
        />
      </section>

      {error ? (
        <div className="errorBanner" role="alert">
          {error}
        </div>
      ) : null}
      {loading ? (
        <div className="loadingBar" role="status">
          Refreshing evidence…
        </div>
      ) : null}

      <div className="workspace">
        <aside className="incidentRail" aria-label="Incident queue">
          <div className="railHeader">
            <div>
              <p className="kicker">Prioritized queue</p>
              <h2>Incidents</h2>
            </div>
            <span>{incidents.length}</span>
          </div>
          <div className="incidentList">
            {incidents.length ? (
              incidents.map((incident) => (
                <button
                  className={
                    incident.incident_id === selectedId ? "incidentRow selected" : "incidentRow"
                  }
                  key={incident.incident_id}
                  onClick={() => selectIncident(incident.incident_id)}
                  type="button"
                >
                  <span className={`statusPip status-${incident.status}`} />
                  <span>
                    <strong>{humanize(incident.incident_type)}</strong>
                    <small>
                      {incident.affected_entity.entity_id} · {humanize(incident.status)} ·{" "}
                      {incident.diagnosis_disposition ? "AI reviewed" : "Diagnosis pending"}
                    </small>
                  </span>
                  <span className="incidentAmount">{formatMoney(incident.amount_at_risk)}</span>
                </button>
              ))
            ) : (
              <p className="emptyState">No incidents match this view.</p>
            )}
          </div>
          {nextCursor ? (
            <button
              className="loadMore"
              disabled={loading}
              onClick={loadMoreIncidents}
              type="button"
            >
              Load more incidents
            </button>
          ) : null}
        </aside>

        <section className="incidentCanvas" aria-label="Selected incident">
          {detail ? (
            <IncidentView detail={detail} />
          ) : (
            <p className="emptyState">Select an incident.</p>
          )}
        </section>
      </div>
    </main>
  );
}

function IncidentView({ detail }: { detail: IncidentDetail }) {
  const incident = detail.incident;
  const diagnosis = detail.latest_diagnosis;
  const decision = diagnosis?.diagnosis.effective_decision;
  return (
    <>
      <header className="incidentHeader">
        <div>
          <p className="kicker">
            {incident.merchant_id} · {incident.correlation_id}
          </p>
          <h2>{humanize(incident.incident_type)}</h2>
          <p>
            {incident.evidence[0]?.description ?? "Deterministic payment invariant was violated."}
          </p>
        </div>
        <div className={`statusBadge status-${incident.status}`}>{humanize(incident.status)}</div>
      </header>

      <section className="diagnosisGrid" aria-label="Latest diagnosis">
        <article className="diagnosisCard primary">
          <p className="kicker">Grounded diagnosis</p>
          <h3>{decision ? humanize(decision.root_cause) : "Diagnosis pending"}</h3>
          <p>{decision?.summary ?? "The evidence worker has not checkpointed a diagnosis yet."}</p>
          {decision ? (
            <div className="confidence">
              <span style={{ width: `${Math.round(decision.confidence * 100)}%` }} />
              <small>{Math.round(decision.confidence * 100)}% model confidence</small>
            </div>
          ) : null}
        </article>
        <article className="diagnosisCard action">
          <p className="kicker">Bounded recommendation</p>
          <h3>{decision ? humanize(decision.recommended_action) : "No proposal"}</h3>
          <p>
            {diagnosis?.diagnosis.guard_reason
              ? `Withheld by guard: ${humanize(diagnosis.diagnosis.guard_reason)}`
              : "A recommendation cannot move money or call Razorpay from this phase."}
          </p>
          <button disabled type="button" title="Phase 9 policy and approval controls are required">
            Request approval · policy gate required
          </button>
        </article>
      </section>

      {diagnosis ? <MoneyGraph evidence={diagnosis.evidence_subgraph} /> : null}

      <section className="auditPanel" aria-labelledby="audit-title">
        <div className="sectionHeader">
          <div>
            <p className="kicker">Append-only history</p>
            <h3 id="audit-title">Incident lifecycle</h3>
          </div>
          <span>{detail.revisions.length} revisions</span>
        </div>
        <ol className="timeline">
          {detail.revisions.map((revision) => (
            <li key={revision.revision_id}>
              <span />
              <div>
                <strong>{humanize(revision.reason)}</strong>
                <small>
                  State generation {revision.state_generation} · {formatDate(revision.recorded_at)}
                </small>
              </div>
              <code>{revision.finding_hash.slice(0, 12)}</code>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function Metric({
  label,
  value,
  alert = false,
}: {
  label: string;
  value: string;
  alert?: boolean;
}) {
  return (
    <article className={alert ? "metric alert" : "metric"}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}

async function fetchJson<T>(path: string, token: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    cache: "no-store",
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("Operator token was rejected.");
    if (response.status === 503) throw new Error("Operator API is not configured.");
    throw new Error(`Operator API returned ${response.status}.`);
  }
  return (await response.json()) as T;
}

function openCount(overview: IncidentOverview | null): string {
  if (!overview) return "—";
  return String(
    Object.entries(overview.status_counts)
      .filter(([status]) => status !== "resolved")
      .reduce((total, [, count]) => total + count, 0),
  );
}

function formatRisk(overview: IncidentOverview | null): string {
  if (!overview) return "—";
  const entries = Object.entries(overview.total_at_risk_subunits);
  if (!entries.length) return "₹0";
  return entries
    .map(([currency, amount]) => formatMoney({ currency, amount_subunits: amount }))
    .join(" · ");
}

function formatMoney(money: Money | null): string {
  if (!money) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: money.currency,
    maximumFractionDigits: 0,
  }).format(money.amount_subunits / 100);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}
