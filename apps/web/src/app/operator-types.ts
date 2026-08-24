export type EntityReference = {
  entity_type: string;
  entity_id: string;
};

export type Money = {
  amount_subunits: number;
  currency: string;
};

export type IncidentSummary = {
  incident_id: string;
  merchant_id: string;
  correlation_id: string;
  incident_type: string;
  status: string;
  affected_entity: EntityReference;
  amount_at_risk: Money | null;
  occurrence_count: number;
  first_detected_at: string;
  last_detected_at: string;
  revision_count: number;
  diagnosis_disposition: string | null;
  diagnosis_confidence: number | null;
  latest_diagnosed_at: string | null;
};

export type IncidentLifecycle = {
  incident_id: string;
  incident_key: string;
  merchant_id: string;
  correlation_id: string;
  incident_type: string;
  status: string;
  rule_id: string;
  rule_version: string;
  affected_entity: EntityReference;
  amount_at_risk: Money | null;
  evidence: Array<{
    evidence_id: string;
    description: string;
    entity: EntityReference;
    event_id: string | null;
    supports_hypothesis: boolean;
  }>;
  finding_hash: string;
  state_generation: number;
  occurrence_count: number;
  first_detected_at: string;
  last_detected_at: string;
  resolved_at: string | null;
  last_evaluation_id: string;
};

export type EvidenceFact = {
  evidence_id: string;
  kind: "invariant" | "journey" | "entity" | "event";
  entity?: EntityReference | null;
  event_id?: string | null;
  event_type?: string | null;
  provider_status?: string | null;
  effective_payment_status?: string | null;
  amount?: Money | null;
  occurred_at?: string | null;
  description: string;
};

export type EvidenceRelationship = {
  source_evidence_id: string;
  target_evidence_id: string;
  relationship_type: string;
};

export type EvidenceSubgraph = {
  incident_id: string;
  source_revision_id: string;
  incident_type: string;
  affected_entity: EntityReference;
  amount_at_risk: Money | null;
  state_generation: number;
  state_hash: string;
  projection_epoch: string;
  facts: EvidenceFact[];
  relationships: EvidenceRelationship[];
  assembled_at: string;
  subgraph_hash: string;
};

export type DiagnosisDecision = {
  disposition: "diagnosed" | "abstained";
  summary: string;
  root_cause: string;
  confidence: number;
  cited_evidence_ids: string[];
  recommended_action: string;
  abstention_reason?: string | null;
  missing_evidence: string[];
};

export type DiagnosisRecord = {
  diagnosis_id: string;
  source_revision_id: string;
  target_version: number;
  model: string;
  provider_interaction_id: string | null;
  prompt_hash: string;
  evidence_subgraph: EvidenceSubgraph;
  diagnosis: {
    model_decision: DiagnosisDecision;
    effective_decision: DiagnosisDecision;
    guard_reason: string | null;
  };
  diagnosed_at: string;
  recorded_at: string;
};

export type IncidentDetail = {
  incident: IncidentLifecycle;
  revisions: Array<{
    revision_id: string;
    evaluation_id: string;
    state_generation: number;
    reason: string;
    status: string;
    finding_hash: string;
    recorded_at: string;
  }>;
  latest_diagnosis: DiagnosisRecord | null;
};

export type IncidentPage = {
  items: IncidentSummary[];
  next_cursor: string | null;
};

export type IncidentOverview = {
  status_counts: Record<string, number>;
  total_at_risk_subunits: Record<string, number>;
  awaiting_diagnosis_count: number;
  diagnosis_dead_letter_count: number;
};

export type ProviderPaymentState = {
  payment_id: string;
  status: string;
  amount: Money;
  captured: boolean;
  order_id: string | null;
};

export type ActionProposal = {
  proposal_id: string;
  incident_id: string;
  source_revision_id: string;
  diagnosis_id: string;
  merchant_id: string;
  incident_type: string;
  action_type: string;
  risk: "read_only" | "reversible" | "money_movement";
  target: EntityReference;
  amount: Money | null;
  rationale: string;
  evidence_ids: string[];
  confidence: number;
  idempotency_key: string;
  proposal_hash: string;
  proposed_by: string;
  request_id: string;
  proposed_at: string;
  expires_at: string;
};

export type ActionView = {
  proposal: ActionProposal;
  policy: {
    decision_id: string;
    proposal_id: string;
    outcome: "allow" | "require_approval" | "deny";
    policy_version: string;
    reasons: string[];
    input_hash: string;
    decided_at: string;
  };
  approvals: Array<{
    approval_id: string;
    proposal_id: string;
    principal_id: string;
    request_id: string;
    decision: "approved" | "rejected";
    rationale: string;
    decided_at: string;
  }>;
  execution_status:
    | "ready"
    | "processing"
    | "retryable"
    | "succeeded"
    | "blocked"
    | "uncertain"
    | null;
  latest_result: {
    execution_id: string;
    proposal_id: string;
    outcome: "succeeded" | "retryable" | "blocked" | "uncertain";
    error_code: string | null;
    provider_state: ProviderPaymentState | null;
    already_applied: boolean;
    completed_at: string;
    result_hash: string;
  } | null;
  stale: boolean;
  expired: boolean;
};
