"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { humanize, MoneyGraph } from "./money-graph";
import type {
  ActionView,
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
  const [actions, setActions] = useState<ActionView[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  const loadDetail = useCallback(
    async (incidentId: string, signal?: AbortSignal) => {
      setSelectedId(incidentId);
      const [next, actionHistory] = await Promise.all([
        fetchJson<IncidentDetail>(`/v1/operator/incidents/${incidentId}`, token, { signal }),
        fetchJson<ActionView[]>(`/v1/operator/incidents/${incidentId}/actions`, token, {
          signal,
        }),
      ]);
      setDetail(next);
      setActions(actionHistory);
    },
    [token],
  );

  useEffect(() => {
    if (!connected) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      fetchJson<IncidentOverview>("/v1/operator/overview", token, { signal: controller.signal }),
      fetchJson<IncidentPage>("/v1/operator/incidents?limit=50", token, {
        signal: controller.signal,
      }),
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
    setActions([]);
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

  async function runAction(path: string, body?: object) {
    if (actionBusy) return;
    setActionBusy(true);
    setError(null);
    try {
      const next = await fetchJson<ActionView>(path, token, {
        method: "POST",
        body,
      });
      setActions((current) => [
        next,
        ...current.filter((item) => item.proposal.proposal_id !== next.proposal.proposal_id),
      ]);
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "The action request could not complete.",
      );
    } finally {
      setActionBusy(false);
    }
  }

  if (!connected) {
    return (
      <main className="accessShell">
        <header className="accessTopbar">
          <a className="accessBrand" href="/" aria-label="Chakravyuh home">
            <span className="miniMark" aria-hidden="true">
              च
            </span>
            <span>
              <strong>Chakravyuh</strong>
              <small>Payment recovery control</small>
            </span>
          </a>
          <nav aria-label="Product navigation">
            <a href="/payments/authorize">Live authorization</a>
            <a href="/recoveries/verified">Verified recovery</a>
            <a href="/reliability">Reliability</a>
          </nav>
          <div className="environmentBadge">
            <span /> Razorpay Test Mode
          </div>
        </header>

        <section className="accessHero" aria-labelledby="product-title">
          <div className="accessCopy">
            <p className="eyebrow">Payment recovery control plane</p>
            <h1 id="product-title">Recover money stuck between states.</h1>
            <p className="tagline">Every rupee has a path.</p>
            <p className="summary">
              Detect stalled payment lifecycles, verify the connected evidence, and recover funds
              through deterministic policy, independent approval, and provider confirmation.
            </p>
            <section className="capabilityList" aria-label="Product safeguards">
              <article>
                <span>01</span>
                <strong>Deterministic detection</strong>
                <p>Replayable invariants identify broken payment states without model authority.</p>
              </article>
              <article>
                <span>02</span>
                <strong>Controlled execution</strong>
                <p>Policy fixes the exact target and amount before independent approval.</p>
              </article>
              <article>
                <span>03</span>
                <strong>Confirmed recovery</strong>
                <p>Revenue is credited only after the provider returns authoritative evidence.</p>
              </article>
            </section>
          </div>

          <aside className="accessPanel" aria-label="Secure operator access">
            <div className="accessPanelHeader">
              <span>Secure operator access</span>
              <span className="accessState">
                <i /> Protected
              </span>
            </div>
            <div className="accessPanelBody">
              <p className="kicker">Operations workspace</p>
              <h2>Continue to incident control.</h2>
              <p>
                Use a scoped operator credential to inspect evidence and run policy-approved Test
                Mode recoveries.
              </p>
              <form className="accessForm" onSubmit={connect}>
                <label htmlFor="operator-token">Operator access token</label>
                <input
                  autoComplete="off"
                  id="operator-token"
                  onChange={(event) => setToken(event.target.value)}
                  placeholder="Enter your session token"
                  type="password"
                  value={token}
                />
                <button disabled={!token.trim()} type="submit">
                  Continue to operations <span aria-hidden="true">→</span>
                </button>
                <p>Session-only credential · cleared when you end the session</p>
              </form>
            </div>
            <div className="accessPanelFooter">
              <span>Environment</span>
              <strong>Test Mode · dual control enabled</strong>
            </div>
          </aside>
        </section>

        <section className="accessProductNav" aria-label="Product areas">
          <a href="/payments/authorize">
            <span>Live authorization</span>
            <strong>Create and follow a Razorpay Test Mode payment.</strong>
            <em>Open transaction →</em>
          </a>
          <a href="/recoveries/verified">
            <span>Verified recovery</span>
            <strong>Inspect one completed recovery from event to confirmation.</strong>
            <em>View recovery →</em>
          </a>
          <a href="/reliability">
            <span>Reliability</span>
            <strong>Review safety, scale, failure, and counterfactual measurements.</strong>
            <em>View reliability →</em>
          </a>
        </section>

        <footer className="accessFooter">
          <span>Test environment</span>
          <p>Razorpay Test Mode semantics · no live funds move</p>
          <p>Signed evidence · immutable audit trail</p>
        </footer>
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
            <span /> Test Mode · scoped dual control
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
            <IncidentView
              actions={actions}
              busy={actionBusy}
              detail={detail}
              onApprove={(proposalId) =>
                runAction(`/v1/operator/actions/${proposalId}/decisions`, {
                  decision: "approved",
                  rationale: "Evidence, target, amount, and policy were independently verified.",
                })
              }
              onExecute={(proposalId) => runAction(`/v1/operator/actions/${proposalId}/execute`)}
              onPropose={() =>
                runAction(`/v1/operator/incidents/${detail.incident.incident_id}/actions/proposals`)
              }
              onReject={(proposalId) =>
                runAction(`/v1/operator/actions/${proposalId}/decisions`, {
                  decision: "rejected",
                  rationale: "The independent checker rejected this bounded proposal.",
                })
              }
            />
          ) : (
            <p className="emptyState">Select an incident.</p>
          )}
        </section>
      </div>
    </main>
  );
}

function IncidentView({
  detail,
  actions,
  busy,
  onPropose,
  onApprove,
  onReject,
  onExecute,
}: {
  detail: IncidentDetail;
  actions: ActionView[];
  busy: boolean;
  onPropose: () => void;
  onApprove: (proposalId: string) => void;
  onReject: (proposalId: string) => void;
  onExecute: (proposalId: string) => void;
}) {
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
        <ActionCard
          actions={actions}
          busy={busy}
          diagnosis={diagnosis}
          onApprove={onApprove}
          onExecute={onExecute}
          onPropose={onPropose}
          onReject={onReject}
        />
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

function ActionCard({
  actions,
  busy,
  diagnosis,
  onPropose,
  onApprove,
  onReject,
  onExecute,
}: {
  actions: ActionView[];
  busy: boolean;
  diagnosis: IncidentDetail["latest_diagnosis"];
  onPropose: () => void;
  onApprove: (proposalId: string) => void;
  onReject: (proposalId: string) => void;
  onExecute: (proposalId: string) => void;
}) {
  const recommendation = diagnosis?.diagnosis.effective_decision;
  const action = actions[0];
  if (!action) {
    const unavailable =
      !recommendation ||
      recommendation.disposition === "abstained" ||
      recommendation.recommended_action === "abstain";
    return (
      <article className="diagnosisCard action">
        <p className="kicker">Deterministic action boundary</p>
        <h3>{recommendation ? humanize(recommendation.recommended_action) : "No proposal"}</h3>
        <p>
          {diagnosis?.diagnosis.guard_reason
            ? `Withheld by guard: ${humanize(diagnosis.diagnosis.guard_reason)}`
            : "The server derives the target and exact amount from this immutable diagnosis."}
        </p>
        <button disabled={busy || unavailable} onClick={onPropose} type="button">
          {busy ? "Evaluating policy…" : "Evaluate deterministic policy"}
        </button>
      </article>
    );
  }

  const rejected = action.approvals.some((item) => item.decision === "rejected");
  const approved = action.approvals.some((item) => item.decision === "approved");
  const awaitsApproval = action.policy.outcome === "require_approval" && !approved && !rejected;
  const executable =
    !action.stale &&
    !action.expired &&
    !rejected &&
    action.policy.outcome !== "deny" &&
    (action.policy.outcome === "allow" || approved) &&
    (action.execution_status === "ready" || action.execution_status === "retryable");
  const stateLabel = action.stale
    ? "Stale proposal"
    : action.expired
      ? "Expired proposal"
      : rejected
        ? "Rejected by checker"
        : action.policy.outcome === "deny"
          ? "Denied by policy"
          : action.execution_status
            ? humanize(action.execution_status)
            : humanize(action.policy.outcome);
  return (
    <article className="diagnosisCard action">
      <div className="actionHeading">
        <p className="kicker">Policy {action.policy.policy_version}</p>
        <span
          className={`actionState actionState-${action.execution_status ?? action.policy.outcome}`}
        >
          {stateLabel}
        </span>
      </div>
      <h3>{humanize(action.proposal.action_type)}</h3>
      <p>
        {action.proposal.amount
          ? `${formatMoney(action.proposal.amount)} · ${humanize(action.proposal.risk)} · ${action.proposal.target.entity_id}`
          : `Read-only provider verification · ${action.proposal.target.entity_id}`}
      </p>
      {action.policy.reasons.length ? (
        <p className="policyReasons">{action.policy.reasons.map(humanize).join(" · ")}</p>
      ) : null}
      {awaitsApproval ? (
        <div className="approvalControls">
          <p>
            A second operator must end this session, sign in with a different token, and
            independently check the graph before deciding.
          </p>
          <div>
            <button
              disabled={busy}
              onClick={() => onApprove(action.proposal.proposal_id)}
              type="button"
            >
              Approve as independent checker
            </button>
            <button
              className="rejectAction"
              disabled={busy}
              onClick={() => onReject(action.proposal.proposal_id)}
              type="button"
            >
              Reject proposal
            </button>
          </div>
        </div>
      ) : null}
      {executable ? (
        <button
          disabled={busy}
          onClick={() => onExecute(action.proposal.proposal_id)}
          type="button"
        >
          {busy ? "Verifying authoritative state…" : "Execute bounded Test Mode action"}
        </button>
      ) : null}
      {action.execution_status === "processing" ? (
        <button disabled type="button">
          Execution lease active
        </button>
      ) : null}
      {action.latest_result ? (
        <div className="actionReceipt">
          <strong>
            {humanize(action.latest_result.outcome)}
            {action.latest_result.already_applied ? " · reconciled without retry" : ""}
          </strong>
          <small>
            {action.latest_result.provider_state
              ? `${humanize(action.latest_result.provider_state.status)} · ${formatMoney(action.latest_result.provider_state.amount)}`
              : humanize(action.latest_result.error_code ?? "no provider receipt")}
          </small>
          <code>{action.latest_result.result_hash.slice(0, 16)}</code>
        </div>
      ) : null}
      <p className="proposalMeta">
        Proposal <code>{action.proposal.proposal_hash.slice(0, 12)}</code> · expires{" "}
        {formatDate(action.proposal.expires_at)}
      </p>
    </article>
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

async function fetchJson<T>(
  path: string,
  token: string,
  options: { signal?: AbortSignal; method?: "GET" | "POST"; body?: object } = {},
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    cache: "no-store",
    credentials: "omit",
    method: options.method ?? "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("Operator token was rejected.");
    if (response.status === 503) throw new Error("Operator API is not configured.");
    const failure = (await response.json().catch(() => null)) as {
      detail?: { code?: string } | string;
    } | null;
    const code =
      typeof failure?.detail === "object" && failure.detail?.code
        ? humanize(failure.detail.code)
        : null;
    throw new Error(code ?? `Operator API returned ${response.status}.`);
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
