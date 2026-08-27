import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

const incidentSummary = {
  incident_id: "11111111-1111-4111-8111-111111111111",
  merchant_id: "merchant_demo",
  correlation_id: "order_demo",
  incident_type: "captured_but_order_unpaid",
  status: "diagnosed",
  affected_entity: { entity_type: "payment", entity_id: "pay_demo" },
  amount_at_risk: { amount_subunits: 125000, currency: "INR" },
  occurrence_count: 2,
  first_detected_at: "2026-08-24T12:00:00Z",
  last_detected_at: "2026-08-24T12:05:00Z",
  revision_count: 2,
  diagnosis_disposition: "diagnosed",
  diagnosis_confidence: 0.96,
  latest_diagnosed_at: "2026-08-24T12:06:00Z",
};

const nextIncidentSummary = {
  ...incidentSummary,
  incident_id: "66666666-6666-4666-8666-666666666666",
  correlation_id: "order_next",
  incident_type: "authorized_not_captured",
  status: "detected",
  affected_entity: { entity_type: "payment", entity_id: "pay_next" },
  diagnosis_disposition: null,
  diagnosis_confidence: null,
  latest_diagnosed_at: null,
};

const incidentDetail = {
  incident: {
    incident_id: incidentSummary.incident_id,
    incident_key: "a".repeat(64),
    merchant_id: incidentSummary.merchant_id,
    correlation_id: incidentSummary.correlation_id,
    incident_type: incidentSummary.incident_type,
    status: incidentSummary.status,
    rule_id: "captured-payment-order-state",
    rule_version: "1",
    affected_entity: incidentSummary.affected_entity,
    amount_at_risk: incidentSummary.amount_at_risk,
    evidence: [
      {
        evidence_id: "event:captured",
        description: "Payment is captured but the order is not paid.",
        entity: incidentSummary.affected_entity,
        event_id: "22222222-2222-4222-8222-222222222222",
        supports_hypothesis: true,
      },
    ],
    finding_hash: "b".repeat(64),
    state_generation: 2,
    occurrence_count: 2,
    first_detected_at: incidentSummary.first_detected_at,
    last_detected_at: incidentSummary.last_detected_at,
    resolved_at: null,
    last_evaluation_id: "33333333-3333-4333-8333-333333333333",
  },
  revisions: [
    {
      revision_id: "44444444-4444-4444-8444-444444444444",
      evaluation_id: "33333333-3333-4333-8333-333333333333",
      state_generation: 2,
      reason: "finding_changed",
      status: "diagnosed",
      finding_hash: "b".repeat(64),
      recorded_at: "2026-08-24T12:06:00Z",
    },
  ],
  latest_diagnosis: {
    diagnosis_id: "55555555-5555-4555-8555-555555555555",
    source_revision_id: "44444444-4444-4444-8444-444444444444",
    target_version: 1,
    model: "gemini-3.5-flash",
    provider_interaction_id: "interaction_demo",
    prompt_hash: "c".repeat(64),
    evidence_subgraph: {
      incident_id: incidentSummary.incident_id,
      source_revision_id: "44444444-4444-4444-8444-444444444444",
      incident_type: incidentSummary.incident_type,
      affected_entity: incidentSummary.affected_entity,
      amount_at_risk: incidentSummary.amount_at_risk,
      state_generation: 2,
      state_hash: "d".repeat(64),
      projection_epoch: "2026-08-24T12:00:00Z",
      facts: [
        {
          evidence_id: "invariant:captured_requires_paid_order",
          kind: "invariant",
          description: "A captured payment must have a paid order.",
        },
        {
          evidence_id: "journey:payment_to_order",
          kind: "journey",
          entity: { entity_type: "order", entity_id: "order_demo" },
          description: "Payment pay_demo belongs to order order_demo.",
        },
        {
          evidence_id: "entity:payment:pay_demo",
          kind: "entity",
          entity: incidentSummary.affected_entity,
          provider_status: "captured",
          amount: incidentSummary.amount_at_risk,
          description: "Payment projection is captured.",
        },
        {
          evidence_id: "event:payment.captured",
          kind: "event",
          event_id: "22222222-2222-4222-8222-222222222222",
          event_type: "payment.captured",
          occurred_at: "2026-08-24T12:04:00Z",
          description: "Razorpay reported payment capture.",
        },
      ],
      relationships: [
        {
          source_evidence_id: "invariant:captured_requires_paid_order",
          target_evidence_id: "journey:payment_to_order",
          relationship_type: "applies_to",
        },
        {
          source_evidence_id: "journey:payment_to_order",
          target_evidence_id: "entity:payment:pay_demo",
          relationship_type: "contains",
        },
        {
          source_evidence_id: "entity:payment:pay_demo",
          target_evidence_id: "event:payment.captured",
          relationship_type: "observed_in",
        },
      ],
      assembled_at: "2026-08-24T12:06:00Z",
      subgraph_hash: "e".repeat(64),
    },
    diagnosis: {
      model_decision: {
        disposition: "diagnosed",
        summary: "Capture completed but the order projection did not advance.",
        root_cause: "order_projection_not_advanced",
        confidence: 0.96,
        cited_evidence_ids: ["event:payment.captured"],
        recommended_action: "reconcile_order_projection",
        missing_evidence: [],
      },
      effective_decision: {
        disposition: "diagnosed",
        summary: "Capture completed but the order projection did not advance.",
        root_cause: "order_projection_not_advanced",
        confidence: 0.96,
        cited_evidence_ids: ["event:payment.captured"],
        recommended_action: "reconcile_order_projection",
        missing_evidence: [],
      },
      guard_reason: null,
    },
    diagnosed_at: "2026-08-24T12:06:00Z",
    recorded_at: "2026-08-24T12:06:01Z",
  },
};

const actionView = {
  proposal: {
    proposal_id: "77777777-7777-4777-8777-777777777777",
    incident_id: incidentSummary.incident_id,
    source_revision_id: "44444444-4444-4444-8444-444444444444",
    diagnosis_id: "55555555-5555-4555-8555-555555555555",
    merchant_id: incidentSummary.merchant_id,
    incident_type: "authorized_not_captured",
    action_type: "capture_payment",
    risk: "money_movement",
    target: incidentSummary.affected_entity,
    amount: incidentSummary.amount_at_risk,
    rationale: "Capture the exact verified authorization.",
    evidence_ids: ["event:payment.captured"],
    confidence: 0.96,
    idempotency_key: "f".repeat(64),
    proposal_hash: "a".repeat(64),
    proposed_by: "maker",
    request_id: "proposal-request",
    proposed_at: "2026-08-24T12:07:00Z",
    expires_at: "2026-08-24T12:22:00Z",
  },
  policy: {
    decision_id: "88888888-8888-4888-8888-888888888888",
    proposal_id: "77777777-7777-4777-8777-777777777777",
    outcome: "require_approval",
    policy_version: "recovery-policy-v1",
    reasons: [],
    input_hash: "b".repeat(64),
    decided_at: "2026-08-24T12:07:00Z",
  },
  approvals: [],
  execution_status: "ready",
  latest_result: null,
  stale: false,
  expired: false,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("operator console", () => {
  it("states the Test Mode policy boundary before accepting a session token", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Recover money stuck between states." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Payment recovery control plane")).toBeInTheDocument();
    expect(screen.getByText(/provider confirmation/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Operator access token")).toHaveAttribute("type", "password");
    expect(screen.getByText(/session-only credential/i)).toBeInTheDocument();
  });

  it("loads audited incident evidence using an in-memory bearer token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/operator/overview")) {
        return jsonResponse({
          status_counts: { diagnosed: 1 },
          total_at_risk_subunits: { INR: 125000 },
          awaiting_diagnosis_count: 0,
          diagnosis_dead_letter_count: 0,
        });
      }
      if (url.includes("cursor=next-page")) {
        return jsonResponse({ items: [nextIncidentSummary], next_cursor: null });
      }
      if (url.includes("/v1/operator/incidents?")) {
        return jsonResponse({ items: [incidentSummary], next_cursor: "next-page" });
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentSummary.incident_id}/actions`)) {
        return jsonResponse([]);
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentSummary.incident_id}`)) {
        return jsonResponse(incidentDetail);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });

    render(<Home />);
    fireEvent.change(screen.getByLabelText("Operator access token"), {
      target: { value: "session-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue to operations" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Captured But Order Unpaid" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Order Projection Not Advanced")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Connected payment evidence graph" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Subgraph SHA-256/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Evaluate deterministic policy" })).toBeEnabled();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    fireEvent.click(screen.getByRole("button", { name: "Load more incidents" }));
    expect(await screen.findByText(/pay_next/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more incidents" })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));

    for (const [, options] of fetchMock.mock.calls) {
      expect(options).toEqual(
        expect.objectContaining({
          cache: "no-store",
          credentials: "omit",
          headers: { Authorization: "Bearer session-secret" },
        }),
      );
    }

    fireEvent.click(screen.getByRole("button", { name: "End session" }));
    expect(screen.getByRole("button", { name: "Continue to operations" })).toBeInTheDocument();
    expect(screen.getByLabelText("Operator access token")).toHaveValue("");
  });

  it("renders maker-checker approval and an exact Test Mode execution receipt", async () => {
    const approved = {
      ...actionView,
      approvals: [
        {
          approval_id: "99999999-9999-4999-8999-999999999999",
          proposal_id: actionView.proposal.proposal_id,
          principal_id: "checker",
          request_id: "approval-request",
          decision: "approved",
          rationale: "Evidence and exact amount independently verified.",
          decided_at: "2026-08-24T12:08:00Z",
        },
      ],
    };
    const executed = {
      ...approved,
      execution_status: "succeeded",
      latest_result: {
        execution_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        proposal_id: actionView.proposal.proposal_id,
        outcome: "succeeded",
        error_code: null,
        provider_state: {
          payment_id: "pay_demo",
          status: "captured",
          amount: incidentSummary.amount_at_risk,
          captured: true,
          order_id: "order_demo",
        },
        already_applied: false,
        completed_at: "2026-08-24T12:09:00Z",
        result_hash: "c".repeat(64),
      },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith("/v1/operator/overview")) {
        return jsonResponse({
          status_counts: { detected: 1 },
          total_at_risk_subunits: { INR: 125000 },
          awaiting_diagnosis_count: 0,
          diagnosis_dead_letter_count: 0,
        });
      }
      if (url.includes("/v1/operator/incidents?")) {
        return jsonResponse({ items: [incidentSummary], next_cursor: null });
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentSummary.incident_id}/actions`)) {
        return jsonResponse([actionView]);
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentSummary.incident_id}`)) {
        return jsonResponse(incidentDetail);
      }
      if (url.endsWith(`/v1/operator/actions/${actionView.proposal.proposal_id}/decisions`)) {
        expect(options?.method).toBe("POST");
        expect(JSON.parse(String(options?.body))).toEqual(
          expect.objectContaining({ decision: "approved" }),
        );
        return jsonResponse(approved);
      }
      if (url.endsWith(`/v1/operator/actions/${actionView.proposal.proposal_id}/execute`)) {
        expect(options?.method).toBe("POST");
        return jsonResponse(executed);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });

    render(<Home />);
    fireEvent.change(screen.getByLabelText("Operator access token"), {
      target: { value: "checker-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue to operations" }));

    fireEvent.click(await screen.findByRole("button", { name: "Approve as independent checker" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Execute bounded Test Mode action" }),
    );

    expect(await screen.findByText("Captured · ₹1,250")).toBeInTheDocument();
    expect(screen.getAllByText(/^Succeeded$/)).toHaveLength(2);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
  } as Response;
}
