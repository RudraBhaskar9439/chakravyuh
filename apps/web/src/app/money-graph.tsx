"use client";

import { useMemo, useState } from "react";

import type { EvidenceFact, EvidenceSubgraph } from "./operator-types";

type Position = { x: number; y: number };

const columns: EvidenceFact["kind"][] = ["invariant", "journey", "entity", "event"];
const xByKind: Record<EvidenceFact["kind"], number> = {
  invariant: 100,
  journey: 330,
  entity: 590,
  event: 850,
};

export function MoneyGraph({ evidence }: { evidence: EvidenceSubgraph }) {
  const [selectedId, setSelectedId] = useState(evidence.facts[0]?.evidence_id ?? "");
  const positions = useMemo(() => layout(evidence.facts), [evidence.facts]);
  const selected = evidence.facts.find((fact) => fact.evidence_id === selectedId);

  return (
    <section className="graphPanel" aria-labelledby="graph-title">
      <div className="sectionHeader">
        <div>
          <p className="kicker">Immutable diagnosis input</p>
          <h3 id="graph-title">Evidence mesh</h3>
        </div>
        <span className="graphCount">
          {evidence.facts.length} facts · {evidence.relationships.length} links
        </span>
      </div>

      <div className="graphViewport" role="img" aria-label="Connected payment evidence graph">
        <svg viewBox="0 0 960 560" preserveAspectRatio="xMidYMid meet">
          <title>Connected payment evidence graph</title>
          {evidence.relationships.map((edge) => {
            const source = positions.get(edge.source_evidence_id);
            const target = positions.get(edge.target_evidence_id);
            if (!source || !target) return null;
            return (
              <g
                key={`${edge.relationship_type}:${edge.source_evidence_id}:${edge.target_evidence_id}`}
              >
                <line
                  className="graphEdge"
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                />
                <text
                  className="edgeLabel"
                  x={(source.x + target.x) / 2}
                  y={(source.y + target.y) / 2 - 5}
                >
                  {humanize(edge.relationship_type)}
                </text>
              </g>
            );
          })}
          {evidence.facts.map((fact) => {
            const position = positions.get(fact.evidence_id);
            if (!position) return null;
            return (
              <g className={`graphNode graphNode-${fact.kind}`} key={fact.evidence_id}>
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={fact.evidence_id === selectedId ? 15 : 11}
                />
                <text x={position.x} y={position.y + 29} textAnchor="middle">
                  {shortLabel(fact)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="graphLegend">
        {columns.map((kind) => (
          <span key={kind} className={`legend-${kind}`}>
            {humanize(kind)}
          </span>
        ))}
      </div>

      <div className="evidenceExplorer">
        <div className="evidenceChips">
          {evidence.facts.map((fact) => (
            <button
              className={fact.evidence_id === selectedId ? "evidenceChip selected" : "evidenceChip"}
              key={fact.evidence_id}
              onClick={() => setSelectedId(fact.evidence_id)}
              type="button"
            >
              {humanize(fact.kind)} · {shortLabel(fact)}
            </button>
          ))}
        </div>
        {selected ? (
          <article className="evidenceInspector" aria-live="polite">
            <p className="kicker">Selected fact</p>
            <h4>{shortLabel(selected)}</h4>
            <p>{selected.description}</p>
            <dl>
              <div>
                <dt>Evidence ID</dt>
                <dd>{selected.evidence_id}</dd>
              </div>
              {selected.provider_status ? (
                <div>
                  <dt>Provider status</dt>
                  <dd>{selected.provider_status}</dd>
                </div>
              ) : null}
              {selected.occurred_at ? (
                <div>
                  <dt>Occurred</dt>
                  <dd>{formatDate(selected.occurred_at)}</dd>
                </div>
              ) : null}
            </dl>
          </article>
        ) : null}
      </div>
      <p className="hashLine">
        Subgraph SHA-256 <code>{evidence.subgraph_hash}</code>
      </p>
    </section>
  );
}

function layout(facts: EvidenceFact[]): Map<string, Position> {
  const positions = new Map<string, Position>();
  for (const kind of columns) {
    const group = facts.filter((fact) => fact.kind === kind);
    group.forEach((fact, index) => {
      positions.set(fact.evidence_id, {
        x: xByKind[kind],
        y: ((index + 1) * 500) / (group.length + 1) + 30,
      });
    });
  }
  return positions;
}

function shortLabel(fact: EvidenceFact): string {
  return (
    fact.entity?.entity_id ??
    fact.event_type ??
    fact.evidence_id.split(":").slice(-1)[0] ??
    fact.kind
  ).slice(0, 24);
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
