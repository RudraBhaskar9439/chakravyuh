"use client";

import { useEffect, useState } from "react";

import { meshEdges, meshNodes, proofLedger, recoveryStages } from "./proof-data";

const replayIntervalMs = 1500;

export function RecoveryStory() {
  const [activeStage, setActiveStage] = useState(0);
  const [playing, setPlaying] = useState(false);
  const stage = recoveryStages[activeStage] ?? recoveryStages[0];

  useEffect(() => {
    if (!playing) return;
    if (activeStage === recoveryStages.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(
      () => setActiveStage((current) => current + 1),
      replayIntervalMs,
    );
    return () => window.clearTimeout(timer);
  }, [activeStage, playing]);

  function replay() {
    setActiveStage(0);
    setPlaying(true);
    document.getElementById("recovery-theatre")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  return (
    <main className="storyShell">
      <header className="storyTopbar">
        <a className="storyBrand" href="/recovery-story">
          <span className="miniMark" aria-hidden="true">
            च
          </span>
          <span>
            <strong>Chakravyuh</strong>
            <small>Verified recovery story</small>
          </span>
        </a>
        <nav aria-label="Recovery story navigation">
          <a href="#proof-ledger">Proof ledger</a>
          <a href="/judge">Scale evidence</a>
          <a href="/">Ops console</a>
        </nav>
        <div className="storyReadOnly">
          <span /> Read-only replay
        </div>
      </header>

      <section className="storyHero">
        <div>
          <p className="eyebrow">One real Razorpay Test Mode journey</p>
          <h1>
            A payment got stuck.
            <br />
            <span>Chakravyuh brought it home.</span>
          </h1>
          <p>
            Watch one verified ₹10 authorization move from a broken payment path to a
            provider-confirmed recovery—without giving AI access to money.
          </p>
          <div className="storyHeroActions">
            <button onClick={replay} type="button">
              <span aria-hidden="true">▶</span>{" "}
              {playing ? "Replaying verified recovery…" : "Replay verified recovery"}
            </button>
            <a href="#proof-ledger">Inspect every proof hash</a>
          </div>
        </div>
        <dl className="storyMetrics" aria-label="Verified recovery metrics">
          <Metric label="Recovered" value="₹10" />
          <Metric label="Detected in" value="59s" />
          <Metric label="Exact mutations" value="1" />
          <Metric label="Duplicate actions" value="0" />
        </dl>
      </section>

      <section className="storySourceBar" aria-label="Proof source">
        <div>
          <span>Provider</span>
          <strong>Razorpay Test Mode</strong>
        </div>
        <div>
          <span>Payment</span>
          <strong>pay_TTyg…rQEd</strong>
        </div>
        <div>
          <span>Outcome</span>
          <strong className="storyHealthy">Captured · order paid</strong>
        </div>
      </section>

      <section className="storyTheatre" id="recovery-theatre" aria-labelledby="story-theatre-title">
        <header className="storySectionHeader">
          <div>
            <p className="eyebrow">The recovery in five moments</p>
            <h2 id="story-theatre-title">See the system think—then prove it.</h2>
          </div>
          <span>Verified 25 Aug 2026</span>
        </header>

        <nav className="storyStageRail" aria-label="Recovery stages">
          {recoveryStages.map((item, index) => (
            <button
              aria-label={`0${index + 1} ${item.label} — ${item.time}`}
              aria-current={index === activeStage ? "step" : undefined}
              className={index === activeStage ? "active" : index < activeStage ? "complete" : ""}
              key={item.label}
              onClick={() => {
                setPlaying(false);
                setActiveStage(index);
              }}
              type="button"
            >
              <span>0{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.time}</small>
            </button>
          ))}
        </nav>

        <div className="storyCanvas">
          <div className="storyCanvasHeader">
            <span>Live evidence mesh</span>
            <span className={activeStage === recoveryStages.length - 1 ? "recovered" : "watching"}>
              {activeStage === recoveryStages.length - 1 ? "Recovered" : "Following the money"}
            </span>
          </div>
          <div className="storyMeshViewport">
            <svg
              aria-label="Animated evidence path from authorization to provider-confirmed capture"
              className="storyMesh"
              role="img"
              viewBox="0 0 1000 420"
            >
              <title>Verified recovery evidence mesh</title>
              {meshEdges.map(([sourceIndex, targetIndex, edgeStage]) => {
                const source = meshNodes[sourceIndex];
                const target = meshNodes[targetIndex];
                if (!source || !target) return null;
                return (
                  <line
                    className={edgeStage <= activeStage ? "storyEdge reached" : "storyEdge"}
                    key={`${source.label}-${target.label}`}
                    x1={source.x}
                    x2={target.x}
                    y1={source.y}
                    y2={target.y}
                  />
                );
              })}
              {meshNodes.map((node, index) => (
                <g
                  className={`${node.stage <= activeStage ? "reached" : ""} ${node.stage === activeStage ? "current" : ""}`}
                  key={node.label}
                  transform={`translate(${node.x} ${node.y})`}
                >
                  <circle className="storyNodeHalo" r="30" />
                  <circle className={`storyNode storyNode-${node.tone}`} r="15" />
                  <text
                    textAnchor={
                      index === 0 ? "start" : index === meshNodes.length - 1 ? "end" : "middle"
                    }
                    x={index === 0 ? -14 : index === meshNodes.length - 1 ? 14 : 0}
                    y={50}
                  >
                    {node.label}
                  </text>
                </g>
              ))}
            </svg>
          </div>
          <article className="storyNarrative" aria-live="polite">
            <span>0{activeStage + 1}</span>
            <div>
              <p>{stage.label}</p>
              <h3>{stage.title}</h3>
              <p>{stage.copy}</p>
            </div>
            <div className="storyEvidenceCallout">
              <small>Proof at this moment</small>
              <strong>{stage.evidence}</strong>
            </div>
            <div className="storyProgress" aria-hidden="true">
              <span style={{ width: `${((activeStage + 1) / recoveryStages.length) * 100}%` }} />
            </div>
          </article>
        </div>
      </section>

      <section className="storyBoundaries" aria-labelledby="boundary-title">
        <header>
          <p className="eyebrow">Why this is safe enough to trust</p>
          <h2 id="boundary-title">AI gets a voice. Never the keys.</h2>
          <p>
            The model explains a bounded graph. Deterministic systems retain every decision that can
            move money.
          </p>
        </header>
        <div>
          <Boundary
            number="01"
            title="Detect without AI"
            copy="Invariant evaluation is deterministic and replayable."
          />
          <Boundary
            number="02"
            title="Ground every diagnosis"
            copy="The model sees only cited, content-hashed evidence."
          />
          <Boundary
            number="03"
            title="Gate every rupee"
            copy="Policy fixes the target and exact amount before approval."
          />
          <Boundary
            number="04"
            title="Credit only confirmation"
            copy="Recovery counts only after provider webhooks arrive."
          />
        </div>
      </section>

      <section className="storyProofLedger" id="proof-ledger" aria-labelledby="proof-ledger-title">
        <header className="storySectionHeader">
          <div>
            <p className="eyebrow">Tamper-evident trail</p>
            <h2 id="proof-ledger-title">Every claim has a fingerprint.</h2>
          </div>
          <span>SHA-256 · full values shown</span>
        </header>
        <div>
          {proofLedger.map((proof, index) => (
            <article key={proof.label}>
              <span>0{index + 1}</span>
              <strong>{proof.label}</strong>
              <code>{proof.hash}</code>
            </article>
          ))}
        </div>
      </section>

      <section className="storyModelReceipt" aria-label="Live model receipt">
        <div>
          <p className="eyebrow">Live model receipt</p>
          <h2>Intelligence was metered. Authority was not delegated.</h2>
        </div>
        <dl>
          <Metric label="Model" value="Gemini 3.5 Flash Lite" compact />
          <Metric label="Tokens" value="2,119" compact />
          <Metric label="Cost" value="$0.000940" compact />
          <Metric label="Money permissions" value="None" compact />
        </dl>
      </section>

      <footer className="storyFooter">
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
          This is a read-only replay of one completed Razorpay Test Mode recovery. It does not call
          an action API and makes no production-SLA claim.
        </p>
        <a href="/">Open engineering console →</a>
      </footer>
    </main>
  );
}

function Metric({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "storyMetric compact" : "storyMetric"}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Boundary({ number, title, copy }: { number: string; title: string; copy: string }) {
  return (
    <article>
      <span>{number}</span>
      <h3>{title}</h3>
      <p>{copy}</p>
    </article>
  );
}
