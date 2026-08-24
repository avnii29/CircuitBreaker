from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class TransactionState(str, Enum):
    INITIATED = "INITIATED"
    FAILED = "FAILED"
    AUTOMATED_LOOP = "AUTOMATED_LOOP"
    RETRYING = "RETRYING"
    REROUTING = "REROUTING"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"


ACTIVE_RECOVERY_STATES = {
    TransactionState.AUTOMATED_LOOP,
    TransactionState.RETRYING,
    TransactionState.REROUTING,
}


def is_active_recovery(state: TransactionState) -> bool:
    return state in ACTIVE_RECOVERY_STATES


class Actor(str, Enum):
    MERCHANT_CHECKOUT = "MERCHANT_CHECKOUT"
    RECOVERY_ENGINE = "RECOVERY_ENGINE"
    AI_SIMULATION = "AI_SIMULATION"
    GUARDRAIL = "GUARDRAIL"
    OPERATOR = "OPERATOR"
    CUSTOMER_FALLBACK_LINK = "CUSTOMER_FALLBACK_LINK"
    STOPPING_RULE = "STOPPING_RULE"


class CustomerDetails(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 8:
            raise ValueError("Phone number is too short.")
        return value


class OrderItem(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=100)
    unit_amount: int = Field(ge=1, le=10_000_000)


class OrderPayload(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    merchant_id: str = Field(min_length=1, max_length=64)
    merchant_name: str = Field(min_length=1, max_length=80)
    items: list[OrderItem] = Field(min_length=1, max_length=20)
    amount: int = Field(ge=1, le=10_000_000)
    currency: str = "INR"
    reservation_id: Optional[str] = None
    cart_released_at: Optional[datetime] = None

    @field_validator("currency")
    @classmethod
    def inr_only(cls, value: str) -> str:
        if value != "INR":
            raise ValueError("Only INR is supported.")
        return value


class RouteAttempt(BaseModel):
    sequence: int
    route: str
    outcome: str
    reason: str
    at: datetime


class RoutingTelemetry(BaseModel):
    bank: str
    attempted_route: str
    fallback_route: str
    error_code: str
    error_label: str
    diagnosis: str
    recovery_eligible: bool = True
    simulation_error: bool = True
    latency_ms: int = 0
    recovery_strategy: str = "RETRY"
    last_route_outcome: Optional[str] = None
    route_attempts: list[RouteAttempt] = Field(default_factory=list)


class GuardrailCheck(BaseModel):
    key: str
    label: str
    passed: bool


class GuardrailResult(BaseModel):
    passed: bool
    checks: list[GuardrailCheck] = Field(default_factory=list)
    output_message: str = ""
    blocked_reason: Optional[str] = None
    reason: str = ""
    used_fallback: bool = False


class CartStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class RecoveryState(BaseModel):
    window_seconds: int
    window_started_at: datetime
    window_expires_at: datetime
    attempt_count: int = 0
    max_attempts: int = 3
    payment_link: str
    cart_held: bool = False
    recommendation: str = ""
    confidence: float = 0.0
    customer_message: str = ""
    raw_llm_output: str = ""
    ai_simulation: bool = True
    guardrail: Optional[GuardrailResult] = None
    recovered_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    auto_recover: bool = False
    recovery_route: str = "UPI FALLBACK"
    message_language: str = "Hinglish"
    message_channel: str = "WHATSAPP_SIMULATION"
    message_generated_at: Optional[datetime] = None
    alternate_link_generated: Optional[str] = None
    cooldown_routes: list[str] = Field(default_factory=list)
    force_route_failure: bool = False
    locked_amount: Optional[int] = None
    retry_count: int = 0
    last_attempt_at: Optional[datetime] = None


class RouteScoreBreakdown(BaseModel):
    base_score: int
    failure_compatibility: int
    historical_success: int
    transient_bonus: int = 0
    retry_penalty: int = 0
    risk_penalty: int = 0


class RouteAlternative(BaseModel):
    route: str
    display_name: str = ""
    score: int


class ScoredRoute(BaseModel):
    route: str
    display_name: str
    score: int
    score_breakdown: RouteScoreBreakdown
    eligible: bool = True


class FailureClassification(BaseModel):
    error_code: str = ""
    category: str
    recoverable: bool
    severity: str = "medium"
    recommended_routes: list[str] = Field(default_factory=list)
    explanation: str = ""
    strategy: str = "RETRY"


class SmartRoutingState(BaseModel):
    failure_classification: Optional[FailureClassification] = None
    selected_route: Optional[str] = None
    display_name: str = ""
    route_score: Optional[int] = None
    confidence: Optional[float] = None
    reason: str = ""
    why: list[str] = Field(default_factory=list)
    alternatives: list[RouteAlternative] = Field(default_factory=list)
    scored_routes: list[ScoredRoute] = Field(default_factory=list)
    score_breakdown: Optional[RouteScoreBreakdown] = None
    guardrail_status: str = "PENDING"
    policy_allowed: bool = True
    policy_reason: str = ""
    policy_blocked: bool = False
    cooldown_routes: list[str] = Field(default_factory=list)
    attempted_routes: list[str] = Field(default_factory=list)
    last_outcome: Optional[str] = None
    simulated: bool = True
    force_route_failure: bool = False
    demo_scenario: str = ""
    first_route_recovery: bool = False
    fallback_recovery: bool = False
    routes_evaluated_count: int = 0
    recovery_phase: str = ""
    preemptive: bool = False
    predicted_failure_probability: Optional[float] = None
    learned_score_source: str = ""
    last_decision: Optional[dict[str, Any]] = None
    policy_version: str = ""


class AuditEvent(BaseModel):
    timestamp: datetime
    action: str
    transaction_id: str
    previous_state: Optional[TransactionState] = None
    new_state: Optional[TransactionState] = None
    actor: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class Transaction(BaseModel):
    transaction_id: str
    state: TransactionState
    customer: CustomerDetails
    order: OrderPayload
    routing: RoutingTelemetry
    recovery: RecoveryState
    audit_trail: list[AuditEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    batch_id: Optional[str] = None
    cart_status: CartStatus = CartStatus.RELEASED
    money_recovered: int = 0
    bank: str = "HDFC"
    failure_reason: str = ""
    smart_routing: Optional[SmartRoutingState] = None
    demo_scenario: str = ""
    tenant_id: str = "TENANT_DEFAULT"
    failed_at: Optional[datetime] = None


class SimulateCheckoutRequest(BaseModel):
    bank: Optional[str] = Field(default=None, max_length=32)
    scenario: Optional[str] = Field(default=None, max_length=64)
    amount: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    customer_phone: Optional[str] = Field(default=None, min_length=8, max_length=20)
    customer_email: Optional[EmailStr] = None
    merchant_id: Optional[str] = Field(default=None, max_length=64)
    auto_recover: bool = False
    force_route_failure: bool = False
    expire_window: bool = False
    demo_scenario: Optional[str] = Field(default=None, max_length=64)
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)


class ExecuteRecoveryRequest(BaseModel):
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)


class SimulateBatchRequest(BaseModel):
    count: int = Field(default=50, ge=1, le=200)


class RoutingSummary(BaseModel):
    transactions_evaluated: int = 0
    routes_evaluated: int = 0
    recovered: int = 0
    escalated: int = 0
    first_route_recovery: int = 0
    fallback_recovery: int = 0
    average_attempts: float = 0.0
    revenue_recovered: int = 0
    revenue_at_risk: int = 0
    most_effective_route: Optional[str] = None


class RunRecoverySimulationResponse(BaseModel):
    selected: list[str]
    recover: list[str] = Field(default_factory=list)
    escalate: list[str] = Field(default_factory=list)
    summary: Optional[RoutingSummary] = None


class BatchResult(BaseModel):
    batch_id: str
    batch_size: int
    failures_intercepted: int
    recovery_attempts: int
    recovered: int
    escalated: int
    in_progress: int
    recovery_rate: float
    revenue_recovered: int
    revenue_at_risk: int
    complete: bool
    created_at: datetime
    transaction_ids: list[str] = Field(default_factory=list)
    routing_summary: Optional[RoutingSummary] = None


class RoutingDashboardStats(BaseModel):
    total_route_decisions: int = 0
    successful_route_executions: int = 0
    failed_route_executions: int = 0
    average_route_score: float = 0.0
    most_selected_route: Optional[str] = None


class IntelligenceTelemetry(BaseModel):
    """Adaptive / intelligence performance. Additive; v1 clients ignore this object."""

    primary_success_rate: float = 0.0
    reroute_success_rate: float = 0.0
    fail_then_reroute_rate: float = 0.0
    predictive_routing_rate: float = 0.0
    recovery_rate: float = 0.0
    average_recovery_time: Optional[float] = None
    retry_success_rate: float = 0.0
    escalation_rate: float = 0.0
    time_to_detect: Optional[float] = None
    time_to_open: Optional[float] = None
    time_to_recover: Optional[float] = None
    false_open_rate: float = 0.0
    policy_adjustments: int = 0
    positive_adjustments: int = 0
    negative_adjustments: int = 0
    rollback_count: int = 0
    active_policy_version: Optional[str] = None
    best_route: Optional[str] = None
    predicted_failure_probability: Optional[float] = None


class RoutePerformance(BaseModel):
    route_id: str
    display_name: str
    attempts: int
    successful: int
    success_rate: float


class RoutingEvent(BaseModel):
    timestamp: datetime
    transaction_id: str
    event: str
    route: Optional[str] = None
    score: Optional[int] = None
    message: str


class RoutingPerformanceResponse(BaseModel):
    routes: list[RoutePerformance]
    events: list[RoutingEvent]
    last_summary: Optional[RoutingSummary] = None
    simulated: bool = True


class CircuitBreakerStatus(BaseModel):
    rail: str
    state: str
    failure_rate: float = 0.0
    samples: int = 0
    opened_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    tenant_id: str = "TENANT_DEFAULT"
    baseline_rate: float = 0.0
    zscore: float = 0.0
    opened_by: str = "threshold"


class TelemetryDashboard(BaseModel):
    total_failures_intercepted: int
    total_transactions_rescued: int
    total_revenue_recovered: int
    active_held_carts: int
    total_escalated: int
    recovery_rate: float
    average_recovery_time_seconds: Optional[float] = None
    revenue_at_risk: int
    revenue_recovered: int
    demo_mode: bool
    recovery_window_seconds: int
    engine_online: bool = True
    last_heartbeat: datetime
    last_batch: Optional[BatchResult] = None
    routing: RoutingDashboardStats = Field(default_factory=RoutingDashboardStats)
    circuit_breakers: list[CircuitBreakerStatus] = Field(default_factory=list)
    tenant_id: Optional[str] = None
    intelligence: IntelligenceTelemetry = Field(default_factory=IntelligenceTelemetry)
    recovery_queue_depth: int = 0


class ExecuteRecoveryResponse(BaseModel):
    executed: bool
    blocked: bool = False
    reason: Optional[str] = None
    fallback_message: Optional[str] = None
    transaction: Transaction


class SelectRecoveryRouteResponse(BaseModel):
    transaction_id: str
    failure_classification: dict[str, Any]
    selected_route: dict[str, Any]
    alternatives: list[dict[str, Any]]
    reason: str
    why: list[str] = Field(default_factory=list)
    guardrail_status: str
    scored_routes: list[dict[str, Any]] = Field(default_factory=list)
    simulated: bool = True
    transaction: Transaction


class ExecuteSelectedRouteResponse(BaseModel):
    executed: bool
    succeeded: bool = False
    blocked: bool = False
    outcome: str
    route: Optional[str] = None
    reason: Optional[str] = None
    simulated: bool = True
    transaction: Transaction


class HealthResponse(BaseModel):
    status: str
    engine: str
    demo_mode: bool
    recovery_window_seconds: int
    heartbeat: datetime
    llm_provider: str
    db_connected: bool = True
    rails_reachable: bool = True
    recovery_queue_depth: int = 0
    open_circuits: int = 0
