"""Version-one eval interchange types, not Phase 1 runtime contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Name = Annotated[str, Field(min_length=1)]
Money = Annotated[str, Field(pattern=r"^\d+(?:\.\d+)?$")]
Failure = Literal["QUALITY_FAILURE", "VALIDATION_FAILURE", "TOOL_FAILURE", "TIMEOUT",
                  "RATE_LIMIT", "PROVIDER_FAILURE", "MALFORMED_OUTPUT", "BUDGET_FAILURE",
                  "CAPABILITY_FAILURE", "UNKNOWN_FAILURE"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def version_is_integer(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer, not a boolean")
        return value


class Pair(Record):
    model: Name
    effort: Name


class Classification(Record):
    task_family: Name
    components: dict[str, int]
    confidence: Annotated[float, Field(ge=0, le=1)]
    flags: dict[str, bool] = Field(default_factory=dict)
    provenance: Name = "eval-author-v1"


class Context(Record):
    input_tokens: Annotated[int, Field(ge=0)] = 1000
    expected_output_tokens: Annotated[int, Field(ge=0)] = 1000
    cached_input_tokens: Annotated[int, Field(ge=0)] = 0
    cache_write_tokens: Annotated[int, Field(ge=0)] = 0
    cache_evidence: bool = False

    @model_validator(mode="after")
    def input_buckets(self):
        if self.cached_input_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("cache buckets exceed total input")
        return self


class Limits(Record):
    model_tier_floor: Annotated[int, Field(ge=0)] | None = None
    model_tier_ceiling: Annotated[int, Field(ge=0)] | None = None
    task_cost_ceiling_usd: Money | None = None
    task_deadline_ms: Annotated[int, Field(gt=0)] | None = None
    live_execution_enabled: bool | None = None


class Request(Record):
    input: Name
    consequence: Literal["low", "moderate", "high", "critical"] = "low"
    requirements: list[Name] = Field(default_factory=lambda: ["text_input", "text_output"])
    context: Context = Field(default_factory=Context)
    constraints: Limits = Field(default_factory=Limits)
    application_id: Name | None = None
    approval_evidence: bool = False
    side_effecting_tool: bool = False
    idempotency_evidence: bool = False


class Environment(Record):
    snapshot: Name = "offline-v1"
    health_scenario: Name = "healthy"
    budget_scenario: Name = "ample"
    # Recursive patches of synthetic snapshots. No application dispatch code.
    overrides: dict[str, JsonValue] = Field(default_factory=dict)
    application_overlay: Limits | None = None
    application_overlay_version: Name | None = None


class Check(Record):
    path: Name
    op: Literal["eq", "contains", "excludes", "between"]
    value: JsonValue
    why: Name

    @model_validator(mode="after")
    def valid_interval(self):
        if self.op == "between":
            from decimal import Decimal, InvalidOperation
            try:
                if not isinstance(self.value, list) or len(self.value) != 2:
                    raise ValueError("between requires two bounds")
                lo, hi = (Decimal(str(v)) for v in self.value)
                if not lo.is_finite() or not hi.is_finite() or lo > hi:
                    raise ValueError("invalid interval")
            except InvalidOperation as error:
                raise ValueError("invalid numeric bounds") from error
        return self


class TraceStep(Record):
    failure: Failure | None
    action: Name
    route: Pair | None
    validated: bool
    # Preserve the original failure even when diagnosis changes its category.
    original_failure: Failure | None = None


class Scenario(Record):
    initial_route: Pair
    events: list[Name]
    limits: dict[str, int | str]


class Expected(Record):
    routing_result: Literal["valid", "rejected", "not_applicable"]
    acceptable_model_efforts: list[Pair] = Field(default_factory=list)
    forbidden_models: list[Name] = Field(default_factory=list)
    minimum_tier: Annotated[int, Field(ge=0)] | None = None
    maximum_tier: Annotated[int, Field(ge=0)] | None = None
    validation_profile: Literal["V0", "V1", "V2", "V3"] | None = None
    required_rationale_codes: list[Name] = Field(default_factory=list)
    forbidden_rationale_codes: list[Name] = Field(default_factory=list)
    expected_failure: Failure | None = None
    acceptable_failure_types: list[Failure] = Field(default_factory=list)
    execution_readiness: Literal["ready", "blocked", "not_applicable"]
    cost_status: Literal["known", "partial", "unavailable"] | None = None
    expected_recovery: list[TraceStep] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    acceptable_task_families: list[Name] = Field(default_factory=list)
    forbidden_task_families: list[Name] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    component_envelopes: dict[str, list[int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        if self.minimum_tier is not None and self.maximum_tier is not None:
            if self.minimum_tier > self.maximum_tier:
                raise ValueError("contradictory tier envelope")
        if set(self.required_rationale_codes) & set(self.forbidden_rationale_codes):
            raise ValueError("contradictory rationales")
        if set(self.acceptable_task_families) & set(self.forbidden_task_families):
            raise ValueError("contradictory families")
        pairs = [(p.model, p.effort) for p in self.acceptable_model_efforts]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate model/effort pair")
        if any(p.model in self.forbidden_models for p in self.acceptable_model_efforts):
            raise ValueError("allowed model is forbidden")
        if self.routing_result == "valid":
            if not pairs or self.validation_profile is None or self.cost_status is None:
                raise ValueError("valid route needs pairs, validation and cost status")
            if self.execution_readiness == "not_applicable":
                raise ValueError("valid route needs readiness")
            if self.expected_failure or self.acceptable_failure_types:
                raise ValueError("valid initial decision cannot also be a rejection")
            if self.cost_status != "known" and self.execution_readiness == "ready":
                raise ValueError("unknown costs cannot certify readiness")
        elif pairs or self.validation_profile is not None or self.cost_status is not None:
            raise ValueError("non-route must not fabricate route fields")
        if self.routing_result == "rejected":
            if not (self.expected_failure or self.acceptable_failure_types) or self.execution_readiness != "blocked":
                raise ValueError("rejection needs failure and blocked readiness")
        if self.expected_failure is not None and self.acceptable_failure_types:
            raise ValueError("use an exact failure or a failure envelope, not both")
        if self.routing_result == "not_applicable" and self.execution_readiness != "not_applicable":
            raise ValueError("classification seed has no execution readiness")
        for bounds in self.component_envelopes.values():
            if len(bounds) != 2 or bounds[0] > bounds[1]:
                raise ValueError("invalid component envelope")
        return self


class Case(Record):
    schema_version: Literal[1]
    id: Name
    category: Literal["routing", "classification", "constraint", "recovery", "health",
                      "budget", "context_cache", "validation", "overlay", "anti_overrouting"]
    description: Name
    basis: Name
    tags: list[Name]
    request: Request
    classification: Classification | None
    environment: Environment
    scenario: Scenario | None = None
    expected: Expected

    @model_validator(mode="after")
    def case_kind(self):
        if self.category == "classification":
            if self.classification is not None or not self.expected.acceptable_task_families:
                raise ValueError("classification seed needs families, not supplied classification")
            if self.expected.routing_result != "not_applicable":
                raise ValueError("classification seed cannot select a route")
        elif self.classification is None or self.expected.routing_result == "not_applicable":
            raise ValueError("routing cases require supplied classification and route expectation")
        if (self.scenario is not None) != bool(self.expected.expected_recovery):
            raise ValueError("scripted scenario and expected trace must occur together")
        return self


class Cost(Record):
    status: Literal["known", "partial", "unavailable"]
    amount: Money | None
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def completeness(self):
        if (self.status == "known") != (self.amount is not None):
            raise ValueError("only a known total can have an amount; partial subtotal belongs in facts")
        return self


class Observation(Record):
    schema_version: Literal[1]
    case_id: Name
    routing_result: Literal["valid", "rejected", "not_applicable"]
    policy_version: Name
    selected_model_alias: Name | None = None
    model_tier: int | None = None
    reasoning_effort: Name | None = None
    validation_level: Literal["V0", "V1", "V2", "V3"] | None = None
    rationale_codes: list[Name] = Field(default_factory=list)
    failure_type: Failure | None = None
    execution_readiness: Literal["ready", "blocked", "not_applicable"]
    estimated_cost: Cost | None = None
    classification: Classification | None = None
    recovery: list[TraceStep] = Field(default_factory=list)
    # Adapter-projected evidence checked by explicit path assertions.
    facts: dict[str, JsonValue] = Field(default_factory=dict)
