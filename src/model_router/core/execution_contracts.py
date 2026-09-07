"""Phase 3 shared records and ports. No framework, SDK or database imports."""
from __future__ import annotations
from model_router.core.phase4_contracts import HealthSnapshot

from datetime import datetime
from typing import Literal, Protocol
from enum import StrEnum
from pydantic import Field, StrictBool, BaseModel
from model_router.core.contracts import (Record, Name, Count, Duration, Money, FailureType,
    RouteDecision, RouteRejection, Classification, Request, EnvironmentSnapshot, Effort)
from model_router.core.provider_contracts import ProviderResult, ProviderFailure

class TaskStatus(StrEnum):
    CREATED = 'created'
    CLASSIFIED = 'classified'
    ROUTED = 'routed'
    ADMITTED = 'admitted'
    RUNNING = 'running'
    VALIDATING = 'validating'
    RECOVERING = 'recovering'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    BLOCKED = 'blocked'
    CANCELLED = 'cancelled'

class AttemptStatus(StrEnum):
    STARTED = 'started'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    UNKNOWN = 'unknown'
    CANCELLED = 'cancelled'

class Failure(Record):
    failure_type: FailureType
    source: Literal['provider', 'adapter', 'validation', 'tool', 'admission', 'orchestrator', 'storage', 'classifier', 'evaluator']
    stage: Name
    cause_code: Name
    retryable: StrictBool = False
    retry_after_ms: Count | None = None

class ExecutionLimits(Record):
    # No defaults: unresolved operational values are not unlimited.
    max_total_generation_attempts: Duration
    max_quality_escalations: Count
    max_infrastructure_retries: Count
    max_tool_recoveries: Count
    max_elapsed_ms: Duration
    initial_backoff_ms: Count
    max_backoff_ms: Count
    task_cost_ceiling_usd: Money

class Counters(Record):
    generation_attempts: Count = 0
    quality_escalations: Count = 0
    infrastructure_retries: Count = 0
    tool_recoveries: Count = 0

class RouteTarget(Record):
    model: Name
    effort: Effort

class RecoveryAction(Record):
    action: Literal['increase_effort', 'increase_tier', 'retry_backoff', 'health_aware_fallback',
        'retry_tool', 'alternate_tool', 'recoverable_failure', 'stop_reconcile', 'diagnose',
        'retry_evaluator', 'stop', 'stop_budget', 'stop_deadline', 'stop_attempts', 'stop_approval', 'stop_success']
    failure: FailureType | None = None
    original_failure: FailureType | None = None
    route: RouteTarget | None = None
    validated: StrictBool = False
    backoff_ms: Count = 0
    rationale_codes: tuple[Name, ...] = ()
    reason: Name

class ValidationOutcome(Record):
    evaluation_id: Name
    check: Name
    status: Literal['passed', 'failed', 'error', 'skipped']
    applicable: StrictBool = True
    failure: Failure | None = None
    # A diagnosis is separate evidence; never overwrite the observation.
    diagnosed_failure: FailureType | None = None
    evidence_code: Name | None = None
    cost_usd: Money | None = '0'
    evaluator_attempt_id: Name | None = None
    target_attempt_id: Name | None = None
    rubric_version: Name | None = None
    score: float | None = None
    score_min: float | None = None
    score_max: float | None = None

class Attempt(Record):
    attempt_id: Name
    task_id: Name
    trace_id: Name
    sequence: Duration
    purpose: Literal['generation', 'classification', 'evaluation'] = 'generation'
    role: Literal['production', 'shadow'] = 'production'
    evaluator_ref: Name | None = None
    rubric_version: Name | None = None
    phase4_version: Name | None = None
    parent_attempt_id: Name | None = None
    decision: RouteDecision | None = None
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime | None = None
    estimated_cost_usd: Money | None = None
    actual_cost_usd: Money | None = None
    pricing_version: Name
    provider_outcome: ProviderResult | ProviderFailure | None = None
    failure: Failure | None = None
    validations: tuple[ValidationOutcome, ...] = ()

class ToolCall(Record):
    tool: Name
    operation: Name
    side_effecting: StrictBool = False
    idempotency_key: Name | None = Field(default=None, exclude=True, repr=False)
    reconciliation_evidence: StrictBool = False
    cost_upper_bound_usd: Money | None = None
    arguments: dict = Field(default_factory=dict, exclude=True, repr=False)
    alternate_tool: Name | None = None

class ToolOutcome(Record):
    tool_event_id: Name
    tool: Name
    operation: Name
    status: Literal['succeeded', 'failed', 'started', 'unknown']
    failure: Failure | None = None
    cost_usd: Money | None = None
    estimated_cost_usd: Money | None = None
    parent_attempt_id: Name | None = None
    latency_ms: Count = 0
    side_effecting: StrictBool = False
    replay_safe: StrictBool = False
    output: object | None = Field(default=None, exclude=True, repr=False)

class ExecutionControls(Record):
    idempotency_key: Name | None = Field(default=None, exclude=True, repr=False)
    authorized: StrictBool = False
    authorized_tools: tuple[Name, ...] = ()
    side_effects_authorized: StrictBool = False
    tool_calls: tuple[ToolCall, ...] = ()
    expected_fields: tuple[Name, ...] = ()
    required_checks: tuple[Name, ...] = ()
    output_type: type[BaseModel] | None = Field(default=None, exclude=True, repr=False)

class ExecutionEvent(Record):
    event_id: Name
    task_id: Name
    trace_id: Name
    kind: Literal['TASK_CREATED', 'TASK_CLASSIFIED', 'ROUTE_SELECTED', 'ATTEMPT_STARTED',
        'ATTEMPT_COMPLETED', 'VALIDATION_COMPLETED', 'RECOVERY_SELECTED', 'TOOL_STARTED',
        'TOOL_COMPLETED', 'TASK_SUCCEEDED', 'TASK_FAILED', 'TASK_BLOCKED', 'TASK_CANCELLED']
    occurred_at: datetime
    policy_version: Name
    attempt_id: Name | None = None
    decision_id: Name | None = None
    tool_event_id: Name | None = None
    evaluation_id: Name | None = None
    failure_type: FailureType | None = None
    action: Name | None = None

class ShadowRun(Record):
    shadow_id: Name
    production_attempt_id: Name
    config_version: Name
    sampling_seed: Name
    sampling_rate: float
    selected: StrictBool
    status: Literal['skipped', 'started', 'succeeded', 'failed']
    reason: Name
    attempts: tuple[Attempt, ...] = ()
    generation_cost_usd: Money | None = '0'
    validation_cost_usd: Money | None = '0'

class TaskResult(Record):
    application_id: Name | None = None
    task_id: Name
    trace_id: Name
    status: TaskStatus
    policy_version: Name
    created_at: datetime
    updated_at: datetime
    revision: Count = 0
    classification: Classification | None = None
    initial_decision: RouteDecision | RouteRejection | None = None
    decisions: tuple[RouteDecision | RouteRejection, ...] = ()
    attempts: tuple[Attempt, ...] = ()
    evaluator_attempts: tuple[Attempt, ...] = ()
    domain_validations: tuple[ValidationOutcome, ...] = ()
    health_snapshots: tuple[HealthSnapshot, ...] = ()
    shadow_runs: tuple[ShadowRun, ...] = ()
    phase4_version: Name | None = None
    phase4_config: dict | None = None
    production_generation_cost_usd: Money | None = '0'
    production_validation_cost_usd: Money | None = '0'
    tool_events: tuple[ToolOutcome, ...] = ()
    recovery_actions: tuple[RecoveryAction, ...] = ()
    counters: Counters = Field(default_factory=Counters)
    execution_limits: ExecutionLimits | None = None
    failure: Failure | None = None
    total_cost_usd: Money | None = '0'
    known_cost_usd: Money = '0'
    reserved_cost_usd: Money = '0'
    output: str | None = Field(default=None, exclude=True, repr=False)
    structured_output: BaseModel | None = Field(default=None, exclude=True, repr=False)

TaskExecution = TaskResult
AttemptOutcome = ProviderResult | ProviderFailure

class RepositoryUnavailable(RuntimeError):
    """Safe storage error. Started evidence must survive uncertain completion."""
class IdempotencyConflict(ValueError):
    pass
class ConcurrentUpdate(RuntimeError):
    pass

class TaskRepository(Protocol):
    def create(self, task: TaskResult, event: ExecutionEvent, *, scope: str,
               key_digest: str | None, request_digest: str) -> TaskResult | None:
        """Atomically claim ID/key and create task+event; return existing duplicate or None."""
        ...
    def pin_versions(self, *, policy_version: str, policy_snapshot: dict,
                     catalog_version: str, catalog_snapshot: dict) -> None: ...
    def save(self, task: TaskResult, events: tuple[ExecutionEvent, ...], *, expected_revision: int) -> None: ...
    def get(self, task_id: str) -> TaskResult | None: ...
    def retain_pending(self, task: TaskResult, events: tuple[ExecutionEvent, ...]) -> None:
        """Durable recovery journal if the primary transaction fails; raise if unavailable."""
        ...

class Clock(Protocol):
    def now(self) -> datetime: ...
    def sleep(self, milliseconds: int) -> None: ...

class BudgetAuthority(Protocol):
    def remaining(self, task_id: str) -> Money: ...
    def reserve(self, task_id: str, action_id: str, amount: Money) -> bool: ...
    def settle(self, task_id: str, action_id: str, actual: Money | None) -> None: ...

class ToolExecutor(Protocol):
    def execute(self, call: ToolCall, *, task_id: str, trace_id: str, event_id: str) -> ToolOutcome: ...

class RecoveryContext(Record):
    decision: RouteDecision
    failure: Failure
    counters: Counters
    limits: ExecutionLimits
    environment: EnvironmentSnapshot
    remaining_usd: Money
    elapsed_ms: Count
    validated: StrictBool = False
    original_failure: FailureType | None = None
    tool_call: ToolCall | None = None
    tool_retryable: StrictBool = False
    alternate_authorized: StrictBool = False
