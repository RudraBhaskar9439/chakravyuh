import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveProofRoom } from "./live-proof-room";

const paymentId = "pay_liveproof123";
const incidentId = "11111111-1111-4111-8111-111111111111";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Live provider proof room", () => {
  it("loads a resolved ledger record and independently re-verifies Razorpay", async () => {
    let proofReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/v1/operator/incidents?limit=100")) {
        return jsonResponse({
          items: [
            {
              incident_id: incidentId,
              status: "resolved",
              affected_entity: { entity_type: "payment", entity_id: paymentId },
            },
          ],
          next_cursor: null,
        });
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentId}`)) {
        return jsonResponse({
          incident: {
            incident_id: incidentId,
            status: "resolved",
            finding_hash: "1".repeat(64),
            resolved_at: "2026-08-28T10:42:05Z",
          },
          revisions: [
            {
              reason: "detected",
              recorded_at: "2026-08-28T10:40:03Z",
              finding_hash: "2".repeat(64),
            },
            {
              reason: "resolved",
              recorded_at: "2026-08-28T10:42:05Z",
              finding_hash: "3".repeat(64),
            },
          ],
          latest_diagnosis: {
            model: "openrouter:google/gemini-3.5-flash-lite",
            diagnosed_at: "2026-08-28T10:40:30Z",
            prompt_hash: "4".repeat(64),
            evidence_subgraph: { subgraph_hash: "5".repeat(64) },
            diagnosis: {
              effective_decision: {
                confidence: 1,
                recommended_action: "capture_payment",
              },
            },
          },
        });
      }
      if (url.endsWith(`/v1/operator/incidents/${incidentId}/actions`)) {
        return jsonResponse([
          {
            proposal: {
              target: { entity_type: "payment", entity_id: paymentId },
              amount: { amount_subunits: 1000, currency: "INR" },
              action_type: "capture_payment",
              risk: "money_movement",
              proposal_hash: "6".repeat(64),
            },
            policy: {
              policy_version: "recovery-policy-v1",
              outcome: "require_approval",
              input_hash: "7".repeat(64),
              decided_at: "2026-08-28T10:40:45Z",
            },
            approvals: [
              {
                decision: "approved",
                principal_id: "checker",
                decided_at: "2026-08-28T10:41:01Z",
                approval_id: "22222222-2222-4222-8222-222222222222",
              },
            ],
            latest_result: {
              outcome: "succeeded",
              already_applied: false,
              completed_at: "2026-08-28T10:42:05Z",
              result_hash: "8".repeat(64),
              provider_state: {
                payment_id: paymentId,
                status: "captured",
                captured: true,
                order_id: "order_liveproof123",
                amount: { amount_subunits: 1000, currency: "INR" },
              },
            },
          },
        ]);
      }
      if (url.endsWith(`/v1/demo/checkout/verifications/${paymentId}/proof`)) {
        proofReads += 1;
        return jsonResponse(providerProof(proofReads));
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LiveProofRoom paymentId={paymentId} />);

    expect(await screen.findByText("LIVE API VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("Ask Razorpay again.")).toBeInTheDocument();
    expect(screen.getAllByText(paymentId).length).toBeGreaterThan(1);
    expect(screen.getByText("Fresh Razorpay API query")).toBeInTheDocument();
    expect(screen.getByText("AI money permissions")).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
    const rawProof = screen.getByRole("link", { name: "Open raw provider proof ↗" });
    expect(rawProof).toHaveAttribute(
      "href",
      `/api/demo/v1/demo/checkout/verifications/${paymentId}/proof`,
    );

    fireEvent.click(screen.getByRole("button", { name: "Re-verify with Razorpay now" }));
    await waitFor(() => expect(proofReads).toBe(2));
    expect(fetchMock).toHaveBeenCalled();
    expect(screen.getAllByText(shortProofHash(2))).toHaveLength(2);
  });

  it("fails closed instead of rendering a cached story", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));

    render(<LiveProofRoom paymentId="pay_missing123" />);

    expect(
      await screen.findByRole("heading", { name: "Proof could not be established." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/No provider-confirmed recovery exists/i)).toBeInTheDocument();
    expect(screen.queryByText("LIVE API VERIFIED")).not.toBeInTheDocument();
  });
});

function providerProof(read: number) {
  return {
    mode: "razorpay_test",
    verification_id: "33333333-3333-4333-8333-333333333333",
    verification_hash: "a".repeat(64),
    verified_at: "2026-08-28T10:39:50Z",
    original_authorization: {
      payment_id: paymentId,
      order_id: "order_liveproof123",
      status: "authorized",
      amount_subunits: 1000,
      currency: "INR",
      captured: false,
    },
    current_provider_state: {
      payment_id: paymentId,
      order_id: "order_liveproof123",
      status: "captured",
      amount_subunits: 1000,
      currency: "INR",
      captured: true,
    },
    provider_checked_at: `2026-08-28T10:4${read}:05Z`,
    provider_proof_hash: String(read).repeat(64),
  };
}

function shortProofHash(read: number): string {
  return `${String(read).repeat(12)}…${String(read).repeat(8)}`;
}

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
