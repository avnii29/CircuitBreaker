export type TransactionStatus =
  | "INITIATED"
  | "FAILED"
  | "AUTOMATED_LOOP"
  | "RETRYING"
  | "REROUTING"
  | "RECOVERED"
  | "ESCALATED";

export type TransactionState = TransactionStatus;

export const ACTIVE_RECOVERY_STATES: TransactionState[] = [
  "AUTOMATED_LOOP",
  "RETRYING",
  "REROUTING",
];

export function isActiveRecovery(state: TransactionState): boolean {
  return ACTIVE_RECOVERY_STATES.includes(state);
}

export const STATE_SORT_ORDER: Record<TransactionState, number> = {
  INITIATED: 0,
  FAILED: 1,
  AUTOMATED_LOOP: 2,
  RETRYING: 3,
  REROUTING: 4,
  RECOVERED: 5,
  ESCALATED: 6,
};

export type CartStatus = "HELD" | "RELEASED";

export type PageId = "overview" | "recovery" | "transactions";

export interface CustomerDetails {
  name: string;
  email: string;
  phone: string;
}

export interface OrderItem {
  sku: string;
  name: string;
  quantity: number;
  unit_amount: number;
}

export interface OrderPayload {
  order_id: string;
  merchant_id: string;
  merchant_name: string;
  items: OrderItem[];
  amount: number;
  currency: string;
  reservation_id: string | null;
  cart_released_at: string | null;
}

export interface RoutingTelemetry {
  bank: string;
  attempted_route: string;
  fallback_route: string;
  error_code: string;
  error_label: string;
  diagnosis: string;
  recovery_eligible: boolean;
  simulation_error: boolean;
  latency_ms: number;
  recovery_strategy?: string;
  last_route_outcome?: string | null;
  route_attempts?: RouteAttempt[];
}

export interface RouteAttempt {
  sequence: number;
  route: string;
  outcome: string;
  reason: string;
  at: string;
}

export interface GuardrailCheck {
  key: string;
  label: string;
  passed: boolean;
}

export interface GuardrailResult {
  passed: boolean;
  checks: GuardrailCheck[];
  output_message: string;
  blocked_reason: string | null;
  used_fallback: boolean;
  reason?: string;
}

export interface RecoveryState {
  window_seconds: number;
  window_started_at: string;
  window_expires_at: string;
  attempt_count: number;
  max_attempts: number;
  payment_link: string;
  cart_held: boolean;
  recommendation: string;
  confidence: number;
  customer_message: string;
  raw_llm_output: string;
  ai_simulation: boolean;
  guardrail: GuardrailResult | null;
  recovered_at: string | null;
  escalated_at: string | null;
  auto_recover: boolean;
  recovery_route: string;
  message_language: string;
  message_channel: string;
  message_generated_at: string | null;
  alternate_link_generated: string | null;
  cooldown_routes: string[];
  force_route_failure: boolean;
  locked_amount: number | null;
  retry_count?: number;
  last_attempt_at?: string | null;
}

export interface RouteScoreBreakdown {
  base_score: number;
  failure_compatibility: number;
  historical_success: number;
  transient_bonus: number;
  retry_penalty: number;
  risk_penalty: number;
}

export interface RecoveryRoute {
  route_id: string;
  display_name: string;
  description?: string;
}

export interface RouteScore {
  route: string;
  display_name: string;
  score: number;
  score_breakdown: RouteScoreBreakdown;
  eligible: boolean;
}

export interface FailureClassification {
  error_code: string;
  category: string;
  recoverable: boolean;
  severity: string;
  recommended_routes: string[];
  explanation: string;
  strategy?: string;
}

export interface RoutingDecisionAlternative {
  route: string;
  display_name: string;
  score: number;
}

export interface InterventionCandidate {
  id: string;
  label: string;
  predicted_success_probability: number;
  expected_recovery_value: number;
  intervention_cost: number;
  risk_penalty: number;
  net_expected_value: number;
  simulated?: boolean;
}

export interface RecoveryEconomics {
  event_type: string;
  revenue_at_risk: number;
  root_cause: string;
  predicted_loss_probability: number;
  window_recovery_probability?: number;
  candidates: InterventionCandidate[];
  selected_action: "ACT" | "DO_NOTHING" | "ESCALATE" | string;
  selected_intervention: string;
  predicted_success_probability: number;
  expected_recovery_value: number;
  intervention_cost: number;
  risk_penalty: number;
  net_expected_value: number;
  actual_recovered: number;
  counterfactual: {
    label: string;
    without_recovery_rate: number;
    without_expected: number;
    with_expected?: number;
    incremental_expected?: number;
    incremental_actual?: number;
  };
  cost_avoided?: number;
  rationale: string;
  priority_score?: number;
  simulated?: boolean;
  guardrail_result?: boolean | null;
  net_revenue_protected?: number;
}

export interface LeakageBreakdown {
  event_type: string;
  count: number;
  amount: number;
  recovered: number;
}

export interface SmartRoutingState {
  failure_classification: FailureClassification | null;
  selected_route: string | null;
  display_name: string;
  route_score: number | null;
  confidence: number | null;
  reason: string;
  why: string[];
  alternatives: RoutingDecisionAlternative[];
  scored_routes: RouteScore[];
  score_breakdown: RouteScoreBreakdown | null;
  guardrail_status: string;
  policy_allowed: boolean;
  policy_reason: string;
  policy_blocked: boolean;
  cooldown_routes: string[];
  attempted_routes: string[];
  last_outcome: string | null;
  simulated: boolean;
  force_route_failure: boolean;
  demo_scenario: string;
  first_route_recovery: boolean;
  fallback_recovery: boolean;
  routes_evaluated_count: number;
  recovery_phase?: string;
  preemptive?: boolean;
  predicted_failure_probability?: number | null;
  learned_score_source?: string;
  last_decision?: Record<string, unknown> | null;
  policy_version?: string;
  economics?: RecoveryEconomics | null;
}

export interface RoutingDecision {
  transaction_id: string;
  failure_classification: {
    category: string;
    recoverable: boolean;
  };
  selected_route: {
    route_id: string;
    score: number;
    confidence: number;
  };
  alternatives: RoutingDecisionAlternative[];
  reason: string;
  why: string[];
  guardrail_status: string;
  scored_routes: RouteScore[];
  simulated: boolean;
  transaction: Transaction;
}

export interface RoutingEvent {
  timestamp: string;
  transaction_id: string;
  event: string;
  route: string | null;
  score: number | null;
  message: string;
}

export interface RoutePerformance {
  route_id: string;
  display_name: string;
  attempts: number;
  successful: number;
  success_rate: number;
}

export interface RoutingDashboardStats {
  total_route_decisions: number;
  successful_route_executions: number;
  failed_route_executions: number;
  average_route_score: number;
  most_selected_route: string | null;
}

export type RoutingTelemetrySnapshot = RoutingDashboardStats;

export interface RoutingSummary {
  transactions_evaluated: number;
  routes_evaluated: number;
  recovered: number;
  escalated: number;
  first_route_recovery: number;
  fallback_recovery: number;
  average_attempts: number;
  revenue_recovered: number;
  revenue_at_risk: number;
  most_effective_route: string | null;
  net_revenue_protected?: number;
  intervention_cost?: number;
  intentionally_skipped?: number;
  baseline_recovered?: number;
  incremental_value_protected?: number;
}

export interface RoutingPerformanceResponse {
  routes: RoutePerformance[];
  events: RoutingEvent[];
  last_summary: RoutingSummary | null;
  simulated: boolean;
}

export interface AuditEvent {
  timestamp: string;
  action: string;
  transaction_id: string;
  previous_state: TransactionState | null;
  new_state: TransactionState | null;
  actor: string;
  metadata: Record<string, unknown>;
  reason?: string;
}

export interface Transaction {
  transaction_id: string;
  state: TransactionState;
  customer: CustomerDetails;
  order: OrderPayload;
  routing: RoutingTelemetry;
  recovery: RecoveryState;
  audit_trail: AuditEvent[];
  created_at: string;
  updated_at: string;
  batch_id: string | null;
  cart_status: CartStatus;
  money_recovered: number;
  bank: string;
  failure_reason: string;
  smart_routing: SmartRoutingState | null;
  demo_scenario: string;
  failed_at?: string | null;
  tenant_id?: string;
}

export interface BatchResult {
  batch_id: string;
  batch_size: number;
  failures_intercepted: number;
  recovery_attempts: number;
  recovered: number;
  escalated: number;
  in_progress: number;
  recovery_rate: number;
  revenue_recovered: number;
  revenue_at_risk: number;
  complete: boolean;
  created_at: string;
  transaction_ids: string[];
  routing_summary: RoutingSummary | null;
  net_revenue_protected?: number;
  intervention_cost?: number;
  intentionally_skipped?: number;
  agent_act?: number;
  agent_do_nothing?: number;
  agent_escalate?: number;
  revenue_leakage_total?: number;
  baseline_recovered?: number;
  incremental_value_protected?: number;
  cost_avoided_total?: number;
  leakage?: LeakageBreakdown[];
}

export interface CircuitBreakerStatus {
  rail: string;
  state: string;
  failure_rate: number;
  samples: number;
  opened_at: string | null;
  cooldown_until: string | null;
  tenant_id?: string;
  baseline_rate?: number;
  zscore?: number;
  opened_by?: string;
}

export interface IntelligenceTelemetry {
  primary_success_rate: number;
  reroute_success_rate: number;
  fail_then_reroute_rate: number;
  predictive_routing_rate: number;
  recovery_rate: number;
  average_recovery_time: number | null;
  retry_success_rate: number;
  escalation_rate: number;
  time_to_detect: number | null;
  time_to_open: number | null;
  time_to_recover: number | null;
  false_open_rate: number;
  policy_adjustments: number;
  positive_adjustments: number;
  negative_adjustments: number;
  rollback_count: number;
  active_policy_version: string | null;
  best_route: string | null;
  predicted_failure_probability?: number | null;
}

export interface TelemetryDashboard {
  total_failures_intercepted: number;
  total_transactions_rescued: number;
  total_revenue_recovered: number;
  active_held_carts: number;
  total_escalated: number;
  recovery_rate: number;
  average_recovery_time_seconds: number | null;
  revenue_at_risk: number;
  revenue_recovered: number;
  demo_mode: boolean;
  recovery_window_seconds: number;
  engine_online: boolean;
  last_heartbeat: string;
  last_batch: BatchResult | null;
  routing?: RoutingDashboardStats;
  circuit_breakers?: CircuitBreakerStatus[];
  tenant_id?: string | null;
  intelligence?: IntelligenceTelemetry;
  recovery_queue_depth?: number;
  net_revenue_protected?: number;
  intervention_cost_total?: number;
  intentionally_skipped?: number;
  agent_act?: number;
  agent_do_nothing?: number;
  agent_escalate?: number;
  revenue_leakage_total?: number;
  baseline_recovered?: number;
  incremental_value_protected?: number;
  cost_avoided_total?: number;
  leakage?: LeakageBreakdown[];
}

export interface HealthResponse {
  status: string;
  engine: string;
  demo_mode: boolean;
  recovery_window_seconds: number;
  heartbeat: string;
  llm_provider: string;
  db_connected?: boolean;
  rails_reachable?: boolean;
  recovery_queue_depth?: number;
  open_circuits?: number;
}

export interface SimulateCheckoutRequest {
  bank?: string;
  scenario?: string;
  amount?: number;
  customer_name?: string;
  customer_phone?: string;
  customer_email?: string;
  merchant_id?: string;
  auto_recover?: boolean;
  force_route_failure?: boolean;
  expire_window?: boolean;
  demo_scenario?: string;
  idempotency_key?: string;
}

export interface SimulateBatchRequest {
  count?: number;
  recover?: boolean;
}

export interface RunRecoverySimulationResponse {
  selected: string[];
  recover: string[];
  escalate: string[];
  summary: RoutingSummary | null;
}

export interface ExecuteRecoveryResponse {
  executed: boolean;
  blocked: boolean;
  reason: string | null;
  fallback_message: string | null;
  transaction: Transaction;
}

export interface ExecuteSelectedRouteResponse {
  executed: boolean;
  succeeded: boolean;
  blocked: boolean;
  outcome: string;
  route: string | null;
  reason: string | null;
  simulated: boolean;
  transaction: Transaction;
}

export interface BatchSimulateResponse {
  batch: BatchResult;
  transactions: Transaction[];
}

export interface PolicyThresholds {
  tenant_id?: string;
  max_retries: number;
  amount_limit: number;
  cooldown_seconds: number;
  predict_fail_threshold: number;
  version: number;
  rationale: string;
  updated_at?: string;
}

export interface RouteScoreRow {
  error_code: string;
  rail: string;
  success_rate: number;
  samples: number;
  rationale: string;
  computed_at?: string;
}

export interface PolicyView {
  tenant_id: string;
  thresholds: PolicyThresholds;
  route_scores: RouteScoreRow[];
  active_snapshot_version?: number;
  active_policy_version?: string;
  last_adjustment?: string;
}

export interface PolicySnapshot {
  id?: number;
  tenant_id: string;
  version: number;
  payload: {
    thresholds: PolicyThresholds;
    route_scores: RouteScoreRow[];
  };
  rationale: string;
  created_at?: string;
  active?: boolean;
}
