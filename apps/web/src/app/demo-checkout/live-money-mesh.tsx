import type { ActionView, IncidentDetail } from "../operator-types";

type LivePayment = {
  payment_id: string;
  order_id: string;
  status: string;
};

export function LiveMoneyMesh({
  payment,
  incident,
  action,
  activeStage,
  recovered,
}: {
  payment: LivePayment;
  incident: IncidentDetail | null;
  action: ActionView | null;
  activeStage: number;
  recovered: boolean;
}) {
  const diagnosis = incident?.latest_diagnosis;
  const decision = diagnosis?.diagnosis.effective_decision;
  const captureAccepted = action?.latest_result?.outcome === "succeeded" || recovered;
  const evidence = diagnosis?.evidence_subgraph;
  const approvalRecorded =
    action?.approvals.some((approval) => approval.decision === "approved") ?? false;
  const breakTitle = recovered
    ? "The payment path is whole"
    : captureAccepted
      ? "Waiting for signed provider confirmation"
      : activeStage >= 1
        ? "Payment stopped before capture"
        : "Watching the capture boundary";
  const breakDetail = recovered
    ? "Razorpay capture and signed webhooks agree. The incident is closed."
    : captureAccepted
      ? "The exact capture succeeded. Chakravyuh is waiting for payment.captured and order.paid."
      : (decision?.summary ??
        "The payment is authorized, but no capture event has completed the money path.");

  return (
    <section className={recovered ? "liveMoneyMesh recovered" : "liveMoneyMesh"}>
      <header className="liveMoneyMeshHeader">
        <div>
          <p className="eyebrow">Inside the transaction</p>
          <h3>See exactly where the money stopped.</h3>
          <p>
            This mesh is assembled from the live payment, its order, deterministic invariants, AI
            diagnosis, policy decision and provider confirmation.
          </p>
        </div>
        <div className={recovered ? "meshVerdict restored" : "meshVerdict broken"}>
          <span>{recovered ? "Path restored" : "Break located"}</span>
          <strong>{recovered ? "Verified end to end" : "Payment → Capture"}</strong>
        </div>
      </header>

      <div className="liveMeshViewport">
        <svg
          aria-label="Animated evidence graph showing the exact payment recovery path"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          viewBox="0 0 1120 520"
        >
          <title>Live payment evidence and recovery mesh</title>
          <defs>
            <filter height="220%" id="meshGlow" width="220%" x="-60%" y="-60%">
              <feGaussianBlur result="blur" stdDeviation="6" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <text className="liveMeshLaneLabel" x="54" y="62">
            CONTROL PLANE · EXPLAINS AND GOVERNS
          </text>
          <text className="liveMeshLaneLabel" x="54" y="300">
            MONEY PLANE · MOVES THE PAYMENT
          </text>

          <MeshEdge active={activeStage >= 1} path="M 302 368 C 360 368, 386 182, 452 182" />
          <MeshEdge active={activeStage >= 2} path="M 500 182 L 665 182" />
          <MeshEdge active={activeStage >= 3} path="M 713 182 L 878 182" />
          <MeshEdge active={approvalRecorded} path="M 926 182 C 972 182, 972 280, 905 345" />

          <MeshEdge active path="M 152 368 L 254 368" />
          <MeshEdge active={captureAccepted} broken={!captureAccepted} path="M 302 368 L 524 368" />
          <MeshEdge active={captureAccepted} path="M 572 368 L 764 368" />
          <MeshEdge active={recovered} path="M 812 368 L 982 368" />

          <MeshNode detail="Razorpay event" label="Authorized" state="provider" x={128} y={368} />
          <MeshNode
            detail={shortId(payment.payment_id)}
            label="Payment"
            state="entity"
            x={278}
            y={368}
          />
          <MeshNode
            detail={captureAccepted ? "Provider accepted" : "Event missing"}
            label="Capture"
            state={captureAccepted ? "healthy" : "fault"}
            x={548}
            y={368}
          />
          <MeshNode
            detail={shortId(payment.order_id)}
            label="Order paid"
            state={captureAccepted ? "entity" : "idle"}
            x={788}
            y={368}
          />
          <MeshNode
            detail={recovered ? "Signed + matched" : "Awaiting provider"}
            label="Webhooks"
            state={recovered ? "healthy" : "idle"}
            x={1006}
            y={368}
          />

          <MeshNode
            detail={activeStage >= 1 ? "Violation found" : "Watching window"}
            label="Invariant"
            state={activeStage >= 1 ? "invariant" : "idle"}
            x={476}
            y={182}
          />
          <MeshNode
            detail={
              diagnosis ? `${Math.round((decision?.confidence ?? 0) * 100)}% grounded` : "Pending"
            }
            label="AI diagnosis"
            state={activeStage >= 2 ? "model" : "idle"}
            x={689}
            y={182}
          />
          <MeshNode
            detail={
              approvalRecorded ? "Independently checked" : action ? "Approval required" : "Bounded"
            }
            label="Policy gate"
            state={activeStage >= 3 ? "policy" : "idle"}
            x={902}
            y={182}
          />

          {!captureAccepted ? (
            <g className="meshFaultMarker" transform="translate(437 368)">
              <circle r="24" />
              <circle className="meshFaultPulse" r="10" />
              <path d="M -4 -4 L 4 4 M 4 -4 L -4 4" />
              <text textAnchor="middle" x="0" y="50">
                STOPPED HERE
              </text>
            </g>
          ) : null}

          {recovered ? (
            <circle className="meshMovingPacket recovered" filter="url(#meshGlow)" r="6">
              <animateMotion
                dur="3.2s"
                path="M 128 368 L 278 368 L 548 368 L 788 368 L 1006 368"
                repeatCount="indefinite"
              />
            </circle>
          ) : (
            <circle className="meshMovingPacket" filter="url(#meshGlow)" r="6">
              <animateMotion
                dur="2.2s"
                path="M 128 368 L 278 368 L 420 368"
                repeatCount="indefinite"
              />
            </circle>
          )}
        </svg>
      </div>

      <div className="liveMeshFinding">
        <div>
          <span>{recovered ? "RECOVERY PROOF" : "ROOT CAUSE"}</span>
          <h4>{breakTitle}</h4>
          <p>{breakDetail}</p>
        </div>
        <dl>
          <div>
            <dt>Provider state</dt>
            <dd>{captureAccepted ? "captured" : payment.status}</dd>
          </div>
          <div>
            <dt>Evidence</dt>
            <dd>
              {evidence
                ? `${evidence.facts.length} facts · ${evidence.relationships.length} links`
                : "assembling"}
            </dd>
          </div>
          <div>
            <dt>Graph integrity</dt>
            <dd>{evidence ? shortHash(evidence.subgraph_hash) : "pending"}</dd>
          </div>
        </dl>
      </div>

      {evidence ? (
        <div className="liveEvidenceFacts">
          {evidence.facts.slice(0, 4).map((fact) => (
            <article key={fact.evidence_id}>
              <span>{fact.kind}</span>
              <strong>{fact.entity?.entity_id ?? fact.event_type ?? "Payment evidence"}</strong>
              <p>{fact.description}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MeshEdge({
  path,
  active,
  broken = false,
}: {
  path: string;
  active: boolean;
  broken?: boolean;
}) {
  return (
    <path
      className={`liveMeshEdge ${active ? "active" : "idle"} ${broken ? "broken" : ""}`}
      d={path}
    />
  );
}

function MeshNode({
  x,
  y,
  label,
  detail,
  state,
}: {
  x: number;
  y: number;
  label: string;
  detail: string;
  state: "provider" | "entity" | "invariant" | "model" | "policy" | "fault" | "healthy" | "idle";
}) {
  return (
    <g className={`liveMeshNode ${state}`} transform={`translate(${x} ${y})`}>
      <circle r="24" />
      <circle className="meshNodeCore" r="7" />
      <text className="meshNodeLabel" textAnchor="middle" x="0" y="45">
        {label}
      </text>
      <text className="meshNodeDetail" textAnchor="middle" x="0" y="62">
        {detail}
      </text>
    </g>
  );
}

function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

function shortHash(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}
