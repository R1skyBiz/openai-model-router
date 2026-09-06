"""Normalized Phase 1 inputs and evidence; no execution or transport types."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    StrictStr,
    field_serializer,
    model_validator,
)


class FrozenDict(Mapping):
    """Read-only mapping whose backing dictionary is never exposed."""

    __slots__ = ("__data",)

    def __init__(self, values: Mapping | None = None, /, **kwargs):
        try:
            object.__getattribute__(self, "_FrozenDict__data")
        except AttributeError:
            pass
        else:
            raise TypeError("snapshot mappings cannot be reinitialized")
        data = dict(values or {})
        data.update(kwargs)
        object.__setattr__(
            self,
            "_FrozenDict__data",
            MappingProxyType({key: freeze(value) for key, value in data.items()}),
        )

    def __setattr__(self, name, value):
        raise TypeError("snapshot mappings are immutable")

    def __delattr__(self, name):
        raise TypeError("snapshot mappings are immutable")

    def __getitem__(self, key):
        return self.__data[key]

    def __iter__(self) -> Iterator:
        return iter(self.__data)

    def __len__(self) -> int:
        return len(self.__data)

    def __repr__(self) -> str:
        return repr(dict(self.__data))

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    """Return ordinary containers for serialization without exposing backing data."""

    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(thaw(item) for item in value)
    if isinstance(value, list):
        return [thaw(item) for item in value]
    return value


def money(value):
    if not isinstance(value, (str, Decimal)):
        raise ValueError("money requires a decimal string or Decimal, never float")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("invalid decimal amount") from error
    if not result.is_finite() or result < 0:
        raise ValueError("money must be finite and nonnegative")
    return result


Money = Annotated[Decimal, BeforeValidator(money)]
Count = Annotated[StrictInt, Field(ge=0)]
Duration = Annotated[StrictInt, Field(gt=0)]
Name = Annotated[StrictStr, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @model_validator(mode="after")
    def freeze_mappings(self):
        for name in type(self).model_fields:
            object.__setattr__(self, name, freeze(getattr(self, name)))
        return self

    @field_serializer("*", mode="wrap", check_fields=False)
    def serialize_fields(self, value, handler: SerializerFunctionWrapHandler):
        return handler(thaw(value))


class FailureType(StrEnum):
    QUALITY_FAILURE = "QUALITY_FAILURE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    BUDGET_FAILURE = "BUDGET_FAILURE"
    CAPABILITY_FAILURE = "CAPABILITY_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class Effort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ValidationLevel(StrEnum):
    V0 = "V0"
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"


class RationaleCode(StrEnum):
    """Runtime vocabulary; the bundle supplies descriptions and rule bindings."""

    BASELINE_PRIOR = "BASELINE_PRIOR"
    ENGINEERING_COMPLEX = "ENGINEERING_COMPLEX"
    TECHNICAL_PRECISION_HIGH = "TECHNICAL_PRECISION_HIGH"
    MULTISTEP = "MULTISTEP"
    TOOL_ORCHESTRATION_HIGH = "TOOL_ORCHESTRATION_HIGH"
    LONG_CONTEXT = "LONG_CONTEXT"
    TASK_FAMILY_FLOOR = "TASK_FAMILY_FLOOR"
    APPLICATION_BUDGET_CAP = "APPLICATION_BUDGET_CAP"
    MODEL_DEGRADED = "MODEL_DEGRADED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    FLOOR_RELAXED = "FLOOR_RELAXED"
    EXCEPTIONAL_AGENTIC = "EXCEPTIONAL_AGENTIC"
    CAPABILITY_FILTER = "CAPABILITY_FILTER"
    CONTEXT_CONSTRAINT = "CONTEXT_CONSTRAINT"
    CONSTRAINED_FALLBACK = "CONSTRAINED_FALLBACK"
    QUALITY_ESCALATION = "QUALITY_ESCALATION"
    INFRASTRUCTURE_RECOVERY = "INFRASTRUCTURE_RECOVERY"
    TOOL_RECOVERY = "TOOL_RECOVERY"
    ESTIMATE_UNAVAILABLE = "ESTIMATE_UNAVAILABLE"
    LOW_CLASSIFIER_CONFIDENCE = "LOW_CLASSIFIER_CONFIDENCE"


class InputError(ValueError):
    """Typed input/policy vocabulary error, distinct from expected rejection."""


class ConfigurationError(ValueError):
    """An invalid configuration bundle cannot be used for routing."""


class ComplexityComponents(Record):
    # Ranges are verified against the pinned policy, never a Python policy table.
    reasoning_depth: Count
    step_dependency: Count
    context_synthesis: Count
    technical_precision: Count
    ambiguity: Count
    tool_orchestration: Count
    reliability_requirement: Count

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in type(self).model_fields)


class Classification(Record):
    task_family: Name
    task_subclass: Name | None = None
    components: ComplexityComponents
    confidence: Annotated[float, Field(ge=0, le=1, strict=True)]
    flags: dict[Name, StrictBool] = Field(default_factory=dict)
    provenance: Name
    supplied_total: Count | None = None

    @model_validator(mode="after")
    def verify_total(self):
        if self.supplied_total is not None and self.supplied_total != self.components.total:
            raise ValueError("supplied total does not equal component sum")
        return self


class Context(Record):
    input_tokens: Count
    expected_output_tokens: Count
    cached_input_tokens: Count = 0
    cache_write_tokens: Count = 0
    cache_evidence: StrictBool = False

    @model_validator(mode="after")
    def buckets(self):
        if self.cached_input_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("cache buckets exceed input tokens")
        return self


class Limits(Record):
    model_tier_floor: Count | None = None
    model_tier_ceiling: Count | None = None
    task_cost_ceiling_usd: Money | None = None
    task_deadline_ms: Duration | None = None
    period_spend_ceiling_usd: Money | None = None
    period: Literal["day", "calendar_month"] | None = None
    live_execution_enabled: StrictBool | None = None


class Request(Record):
    task_id: Name
    trace_id: Name
    input: StrictStr = Field(default="", exclude=True, repr=False)
    application_id: Name | None = None
    requirements: Annotated[tuple[Name, ...], Field(min_length=1)]
    consequence: Literal["low", "moderate", "high", "critical"]
    context: Context
    constraints: Limits = Field(default_factory=Limits)
    requested_validation: ValidationLevel | None = None
    approval_evidence: StrictBool = False
    domain_clearance_evidence: StrictBool = False
    side_effecting_tool: StrictBool = False
    idempotency_evidence: StrictBool = False
    policy_version: Name | None = None


class ModelHealth(Record):
    state: Literal["HEALTHY", "DEGRADED", "UNHEALTHY"]
    account_access: Literal["verified", "unknown", "unavailable"] = "unknown"
    usable: StrictBool = True


class EnvironmentSnapshot(Record):
    snapshot_id: Name
    synthetic: StrictBool = False
    clock: datetime
    pricing_version: Name
    health_snapshot_id: Name | None = None
    health_observed_at: datetime | None = None
    health_valid_until: datetime | None = None
    models: dict[Name, ModelHealth] = Field(default_factory=dict)
    budget: Limits = Field(default_factory=Limits)
    remaining_usd: Money | None = None
    trusted_application_id: Name | None = None
    application_overlay: Limits | None = None
    application_overlay_version: Name | None = None
    validation: dict[ValidationLevel, Literal["configured_mock", "unconfigured"]] = Field(default_factory=dict)
    required_evaluator_cost_usd: Money | None = None
    required_domain_validator_cost_usd: Money | None = None
    required_tool_charge: StrictBool = False
    required_tool_charge_usd: Money | None = None
    requested_validation: ValidationLevel | None = None
    minimum_next_action_ms: Count | None = None
    latency_source: Name | None = None
    recovery_bounded: StrictBool = False
    durable_retention: StrictBool = False

    @model_validator(mode="after")
    def provenance(self):
        if (self.application_overlay is None) != (self.application_overlay_version is None):
            raise ValueError("application overlay and version must accompany each other")
        for stamp in (self.clock, self.health_observed_at, self.health_valid_until):
            if stamp is not None and stamp.utcoffset() is None:
                raise ValueError("snapshot timestamps must be timezone-aware")
        if not self.synthetic and (self.validation or self.recovery_bounded):
            raise ValueError("mock validation/recovery evidence requires synthetic snapshot")
        return self


class Candidate(Record):
    model: Name
    effort: Effort
    source: Literal["prior", "modifier", "floor", "fallback"]


class FloorEvidence(Record):
    rule_id: Name
    strength: Literal["hard", "preferred"]
    min_tier: Count


class CandidatePlan(Record):
    candidates: tuple[Candidate, ...]
    floors: tuple[FloorEvidence, ...]
    rationale_codes: tuple[Name, ...]
    matched_rules: tuple[Name, ...]
    hard_floor: Count
    preferred_floor: Count


class CostEstimate(Record):
    status: Literal["known", "partial", "unavailable"]
    amount: Money | None
    currency: Name
    pricing_version: Name
    model_pricing_version: Name
    token_assumptions: Context
    known_subtotal: Money
    generation_subtotal: Money
    breakdown: dict[Name, Money | None]
    unknown_charges: tuple[Name, ...] = ()
    cache_read_tokens: Count = 0
    long_context: StrictBool = False
    scope: Name = "generation_and_required_validation_and_tools"

    @model_validator(mode="after")
    def coherent(self):
        if (self.status == "known") != (self.amount is not None):
            raise ValueError("only complete costs have a total amount")
        return self


class Feasibility(Record):
    violations: tuple[Name, ...] = ()
    blockers: tuple[Name, ...] = ()
    rationale_codes: tuple[Name, ...] = ()


class ValidationRequirements(Record):
    level: ValidationLevel
    profiles: tuple[ValidationLevel, ...]
    checks: tuple[Name, ...]
    evaluator_refs: tuple[Name, ...] = ()
    validator_refs: tuple[Name, ...] = ()
    blockers: tuple[Name, ...] = ()
    evaluator_required: StrictBool = False
    approval_required: StrictBool = False
    evidence: Name
    execution_restrictions: tuple[Name, ...] = ()


class DecisionBase(Record):
    task_id: Name
    trace_id: Name
    decision_id: Name
    policy_version: Name
    catalog_version: Name
    pricing_version: Name
    budget_version: Name
    validation_version: Name
    application_overlay_version: Name | None
    effective_configuration_hash: Name
    classification: Classification
    complexity_score: Count
    rationale_codes: tuple[Name, ...]
    rationale_details: dict[str, Any]
    effective_limits: Limits
    environment_snapshot_id: Name
    synthetic: StrictBool
    health_snapshot_id: Name | None
    readiness_blockers: tuple[Name, ...]


class RouteDecision(DecisionBase):
    routing_result: Literal["valid"] = "valid"
    selected_model_alias: Name
    provider_model_id: Name
    model_tier: Count
    reasoning_effort: Effort
    validation_level: ValidationLevel
    validation_requirements: ValidationRequirements
    estimated_cost: CostEstimate
    executable: StrictBool


class RouteRejection(DecisionBase):
    routing_result: Literal["rejected"] = "rejected"
    failure_type: FailureType
    violated_constraints: tuple[Name, ...]
    retryable: StrictBool = False
    executable: Literal[False] = False
