"""Typed Phase 5 wire projections shared by telemetry HTTP endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Cost(WireModel):
    amount: str | None
    known_subtotal: str
    missing_count: int
    status: Literal["known", "partial", "unavailable"]


class Rate(WireModel):
    value: float | None
    numerator: int
    denominator: int


class Meta(WireModel):
    metric_definition_version: str
    start: str
    end: str
    generated_at: str
    freshness: str | None
    synthetic: bool
    currency: Literal["USD"]
    filters: dict[str, str | None]
    notes: list[str]


class Metrics(WireModel):
    total_tasks: int
    terminal_tasks: int
    pending_tasks: int
    cancelled_tasks: int
    blocked_tasks: int
    successful_tasks: int
    first_pass_success: Rate
    final_success: Rate
    escalation_rate: Rate
    infrastructure_retry_rate: Rate
    tool_recovery_rate: Rate
    cost: Cost
    cost_per_task: Cost
    effective_cost_per_success: Cost
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class Summary(WireModel):
    meta: Meta
    metrics: Metrics
    spend_today: Cost
    spend_mtd: Cost
    projected_month: Cost
    forecast_method: str
    policy_versions: list[str]


class SpendPoint(WireModel):
    date: str
    production: Cost
    shadow: Cost
    cumulative_production: Cost


class SpendGroup(WireModel):
    key: str
    cost: Cost
    count: int


class Spend(WireModel):
    meta: Meta
    production: Cost
    shadow: Cost
    all_spend: Cost
    unallocated: Cost
    series: list[SpendPoint]
    by_model: list[SpendGroup]
    by_effort: list[SpendGroup]
    by_application: list[SpendGroup]
    by_task_family: list[SpendGroup]
    by_policy: list[SpendGroup]
    by_purpose: list[SpendGroup]
    by_contribution: list[SpendGroup]


class Distribution(WireModel):
    key: str
    count: int
    share: float | None


class Flow(WireModel):
    source: str
    target: str
    count: int


class TrendPoint(WireModel):
    date: str
    first_pass_success: Rate
    final_success: Rate
    effective_cost_per_success: Cost


class Routing(WireModel):
    meta: Meta
    models: list[Distribution]
    efforts: list[Distribution]
    complexities: list[Distribution]
    task_families: list[Distribution]
    validations: list[Distribution]
    rationale_codes: list[Distribution]
    family_model_flow: list[Flow]
    escalation_flow: list[Flow]
    preferred_floor_relaxation: Rate
    constrained_fallback: Rate
    trend: list[TrendPoint]


class QualityGroup(WireModel):
    rubric_version: str
    check: str
    score_min: float
    score_max: float
    mean: float
    sample_size: int
    role: str


class Quality(WireModel):
    comparable: bool
    reason: str | None
    groups: list[QualityGroup]


class Cohort(WireModel):
    key: str
    model: str | None
    effort: str | None
    policy_version: str | None
    metrics: Metrics
    quality: Quality
    insufficient_sample: bool


class Efficacy(WireModel):
    meta: Meta
    cohorts: list[Cohort]


class Policies(WireModel):
    meta: Meta
    cohorts: list[Cohort]
    comparison_note: str


HealthState = Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "STALE", "UNKNOWN"]


class HealthComponent(WireModel):
    component: str
    model: str | None
    capability: str | None
    state: HealthState
    observed_at: str | None
    valid_until: str | None
    circuit_state: str
    failure_count: int
    latency_ms: float | None
    required: bool


class DegradedPeriod(WireModel):
    start: str
    end: str | None
    component: str
    state: str


class Health(WireModel):
    meta: Meta
    state: HealthState
    production_ready: Literal[False]
    readiness_note: str
    components: list[HealthComponent]
    outbox_pending: int
    oldest_pending_at: str | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    failure_rate: Rate
    timeouts: int
    rate_limits: int
    degraded_periods: list[DegradedPeriod]


class TaskItem(WireModel):
    task_id: str
    created_at: str
    application: str | None
    task_family: str | None
    complexity: int | None
    model: str | None
    effort: str | None
    status: str
    cost: Cost
    latency_ms: float | None
    escalated: bool
    policy_version: str
    synthetic: bool


class TaskList(WireModel):
    meta: Meta
    items: list[TaskItem]
    total: int
    offset: int
    limit: int


MetadataValue = str | int | float | bool | None


class TimelineStep(WireModel):
    id: str
    kind: str
    timestamp: str | None
    title: str
    model: str | None
    effort: str | None
    rationale_codes: list[str]
    tokens: dict[str, int | None]
    cost: Cost | None
    latency_ms: float | None
    validation: str | None
    failure_type: str | None
    recovery_action: str | None
    health_snapshot_id: str | None
    policy_version: str | None
    pricing_version: str | None
    role: str
    metadata: dict[str, MetadataValue]


class TaskDetail(WireModel):
    meta: Meta
    task: TaskItem
    timeline: list[TimelineStep]
    total: int
    offset: int
    limit: int


__all__ = [
    "Efficacy", "Health", "Policies", "Routing", "Spend", "Summary",
    "TaskDetail", "TaskList",
]
