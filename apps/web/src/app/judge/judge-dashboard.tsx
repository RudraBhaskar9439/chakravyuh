"use client";

import { type CSSProperties, useState } from "react";

import { chaosChecks, exceptions, funnel, meshNodes, proofRoots, strategies } from "./proof-data";

const views = ["Tournament", "Recovery funnel", "Evidence mesh", "Chaos", "Exceptions"] as const;
type View = (typeof views)[number];

export function JudgeDashboard() {
  const [view, setView] = useState<View>("Tournament");

  return (
    <main className="judgeShell">
      <header className="judgeTopbar">
        <a href="/" className="judgeBrand">
          <span className="miniMark" aria-hidden="true">
            च
          </span>
          <span>
            <strong>Chakravyuh</strong>
            <small>Recovery Arena · locked proof</small>
          </span>
        </a>
        <div className="judgeBoundary">
          <span /> Read-only · no action API connected
        </div>
      </header>

      <section className="judgeHero">
        <div>
          <p className="eyebrow">Phase 12 · judge evidence room</p>
          <h1>
            Follow the money.
            <br />
            Challenge every claim.
          </h1>
        </div>
        <p>
          A held-out counterfactual tournament, a metered live-model sample, one real Razorpay Test
          Mode payment, and a 100,000-event local pipeline proof—kept visibly separate.
        </p>
      </section>

      <section className="sourceStrip" aria-label="Evidence source boundaries">
        <SourceCard
          kind="synthetic"
          label="Held-out synthetic"
          value="10,005 journeys"
          note="Deterministic provider twin · labelled INR"
        />
        <SourceCard
          kind="live-ai"
          label="Live AI"
          value="100 calls · $0.127755"
          note="OpenRouter · diagnosis only · zero money access"
        />
        <SourceCard
          kind="real-provider"
          label="Real provider"
          value="₹10 Test Mode"
          note="Razorpay authorization and recovery semantics"
        />
        <SourceCard
          kind="local-scale"
          label="Local scale"
          value="110,000 deliveries"
          note="PostgreSQL + Neo4j · single MacBook process"
        />
      </section>

      <nav className="judgeTabs" aria-label="Judge proof views">
        {views.map((item, index) => (
          <button
            aria-current={item === view ? "page" : undefined}
            className={item === view ? "selected" : ""}
            key={item}
            onClick={() => setView(item)}
            type="button"
          >
            <span>0{index + 1}</span> {item}
          </button>
        ))}
      </nav>

      <section className="judgeCanvas" aria-live="polite">
        {view === "Tournament" ? <Tournament /> : null}
        {view === "Recovery funnel" ? <RecoveryFunnel /> : null}
        {view === "Evidence mesh" ? <EvidenceMesh /> : null}
        {view === "Chaos" ? <Chaos /> : null}
        {view === "Exceptions" ? <Exceptions /> : null}
      </section>

      <footer className="judgeFooter">
        <p>
          Proofs are reproducible local measurements, not a production SLA or merchant revenue
          claim. Only webhook-confirmed synthetic recovery is scored.
        </p>
        <a href="/demo-checkout">Inspect the separate real Test Mode proof →</a>
      </footer>
    </main>
  );
}

function SourceCard({
  kind,
  label,
  value,
  note,
}: {
  kind: string;
  label: string;
  value: string;
  note: string;
}) {
  return (
    <article className={`sourceCard source-${kind}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function ViewHeader({
  index,
  eyebrow,
  title,
  copy,
}: {
  index: string;
  eyebrow: string;
  title: string;
  copy: string;
}) {
  return (
    <header className="proofViewHeader">
      <span>{index}</span>
      <div>
        <p className="kicker">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{copy}</p>
      </div>
    </header>
  );
}

function Tournament() {
  const maximum = Math.max(...strategies.map((strategy) => Math.abs(strategy.netRupees)));
  return (
    <>
      <ViewHeader
        copy="Same observed cases. Independent provider clones. Revenue counted only after confirmation."
        eyebrow="Counterfactual comparison"
        index="01"
        title="Same recovery. Radically different risk."
      />
      <div className="strategyGrid">
        {strategies.map((strategy) => (
          <article
            className={strategy.name === "Chakravyuh" ? "strategyCard winner" : "strategyCard"}
            key={strategy.name}
          >
            <div className="strategyName">
              <h3>{strategy.name}</h3>
              {strategy.name === "Chakravyuh" ? <span>Selected</span> : null}
            </div>
            <strong className={strategy.netRupees < 0 ? "negativeValue" : ""}>
              {formatRupees(strategy.netRupees)}
            </strong>
            <small>net recovery value</small>
            <div className="netTrack" aria-hidden="true">
              <span
                className={strategy.netRupees < 0 ? "negative" : ""}
                style={{ width: `${Math.max(2, (Math.abs(strategy.netRupees) / maximum) * 100)}%` }}
              />
            </div>
            <dl>
              <Stat label="Confirmed recoveries" value={String(strategy.confirmedRecoveries)} />
              <Stat label="Action attempts" value={strategy.actions.toLocaleString("en-IN")} />
              <Stat
                label="Incorrect actions"
                value={strategy.incorrectActions.toLocaleString("en-IN")}
                danger={strategy.incorrectActions > 0}
              />
              <Stat label="Gross recovered" value={formatRupees(strategy.recoveredRupees)} />
            </dl>
          </article>
        ))}
      </div>
      <ProofHash label="Tournament report" value={proofRoots.tournament} />
    </>
  );
}

function RecoveryFunnel() {
  return (
    <>
      <ViewHeader
        copy="Every narrowing step has an explicit reason. Nothing becomes revenue merely because an API call returned."
        eyebrow="Decision accountability"
        index="02"
        title="10,005 journeys. 402 confirmed recoveries."
      />
      <div className="funnel">
        {funnel.map((step, index) => (
          <article
            key={step.label}
            style={{ "--funnel-width": `${100 - index * 10}%` } as CSSProperties}
          >
            <span>0{index + 1}</span>
            <div>
              <strong>{step.value.toLocaleString("en-IN")}</strong>
              <p>{step.label}</p>
            </div>
            <small>{step.note}</small>
          </article>
        ))}
      </div>
      <dl className="funnelFootnotes">
        <Stat label="Detector false positives" value="0" />
        <Stat label="Detector false negatives" value="0" />
        <Stat label="Duplicate mutations" value="0" />
        <Stat label="Unconfirmed recoveries credited" value="0" />
      </dl>
      <ProofHash label="Held-out portfolio" value={proofRoots.portfolio} />
    </>
  );
}

function EvidenceMesh() {
  return (
    <>
      <ViewHeader
        copy="AI is one constrained node inside the system. Deterministic layers retain authority before and after it."
        eyebrow="Connected money path"
        index="03"
        title="The model can explain. It cannot move money."
      />
      <div className="meshScroll" role="img" aria-label="End-to-end connected money evidence mesh">
        <div className="mesh">
          {meshNodes.map((node, index) => (
            <div className="meshStep" key={node.id}>
              <article
                className={
                  node.id === "model" ? "modelNode" : node.id === "confirmed" ? "confirmedNode" : ""
                }
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{node.label}</strong>
                <small>{node.detail}</small>
              </article>
              {index < meshNodes.length - 1 ? (
                <div className="meshEdge" aria-hidden="true">
                  →
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
      <div className="meshBoundaries">
        <article>
          <span>Observe</span>
          <strong>Signed intake → invariant</strong>
          <p>Append-only and deterministic.</p>
        </article>
        <article>
          <span>Reason</span>
          <strong>Evidence graph → AI → guard</strong>
          <p>Bounded citations; abstain on doubt.</p>
        </article>
        <article>
          <span>Act</span>
          <strong>Policy → checker → provider</strong>
          <p>Exact target, amount, and idempotency key.</p>
        </article>
        <article>
          <span>Confirm</span>
          <strong>Authoritative webhook</strong>
          <p>No confirmation, no recovery credit.</p>
        </article>
      </div>
      <ProofHash label="Live-AI report" value={proofRoots.liveAi} />
    </>
  );
}

function Chaos() {
  return (
    <>
      <ViewHeader
        copy="The proof is strongest where systems usually become ambiguous: retries, crashes, reordering, and partial failure."
        eyebrow="Adversarial gates"
        index="04"
        title="Nine ways to fail. Nine bounded outcomes."
      />
      <div className="chaosSummary">
        <article>
          <strong>100,000</strong>
          <small>unique events</small>
        </article>
        <article>
          <strong>10,000</strong>
          <small>duplicates rejected</small>
        </article>
        <article>
          <strong>356.13/s</strong>
          <small>worker drain</small>
        </article>
        <article>
          <strong>0</strong>
          <small>dead letters / lease loss</small>
        </article>
      </div>
      <ol className="chaosList">
        {chaosChecks.map(([fault, outcome], index) => (
          <li key={fault}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{fault}</strong>
            <p>{outcome}</p>
            <em>Passed</em>
          </li>
        ))}
      </ol>
      <div className="dualHash">
        <ProofHash label="Signed ingress" value={proofRoots.signedIngress} />
        <ProofHash label="Full pipeline" value={proofRoots.fullPipeline} />
      </div>
    </>
  );
}

function Exceptions() {
  return (
    <>
      <ViewHeader
        copy="Failures remain first-class results. Cost, abstention, replay, and lost revenue are never rounded away."
        eyebrow="Honest exception ledger"
        index="05"
        title="What did not work is part of the proof."
      />
      <section className="exceptionTable" aria-label="Reported proof exceptions">
        {exceptions.map((exception) => (
          <article key={exception.title}>
            <span className={`sourcePill source-${exception.source}`}>
              {exception.source.replace("-", " ")}
            </span>
            <strong>{exception.count}</strong>
            <div>
              <h3>{exception.title}</h3>
              <p>{exception.disposition}</p>
            </div>
          </article>
        ))}
      </section>
      <div className="exceptionPrinciple">
        <p className="kicker">Scoring rule</p>
        <strong>Safe abstention beats fabricated certainty.</strong>
        <p>
          Exceptions cannot execute, unconfirmed actions earn ₹0, and failed model calls still
          consume their reserved budget.
        </p>
      </div>
    </>
  );
}

function Stat({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={danger ? "negativeValue" : ""}>{value}</dd>
    </div>
  );
}

function ProofHash({ label, value }: { label: string; value: string }) {
  return (
    <p className="proofHash">
      <span>{label} SHA-256</span>
      <code>{value}</code>
    </p>
  );
}

function formatRupees(value: number): string {
  const sign = value < 0 ? "−" : "";
  return `${sign}₹${Math.abs(value).toLocaleString("en-IN")}`;
}
