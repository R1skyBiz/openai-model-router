"""Strict, immutable configuration records for the deterministic router.

The classes in this module describe the version-one YAML contract.  They do not
contain routing decisions: cross-document validation only proves that a bundle
is internally coherent and safe for the policy engine to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BeforeValidator, Field, StrictBool, StrictInt, StrictStr, ValidationError, model_validator
import yaml

from .contracts import ComplexityComponents, ConfigurationError, FailureType, Name, RationaleCode, Record, ValidationLevel, freeze


def _decimal_string(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("money values must be decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("money values must be valid decimal strings") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("money values must be finite and nonnegative")
    return result


MoneyString = Annotated[Decimal, BeforeValidator(_decimal_string)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Rate = Annotated[float, Field(strict=True, ge=0, le=1)]
Tier = Annotated[StrictStr, Field(pattern=r"^L[0-9]+$")]
EffortName = Literal["none", "low", "medium", "high", "xhigh", "max"]
Capability = StrictBool | None


def _schema_version(value: Any) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("schema_version must be integer 1")
    return value


def _false_only(value: Any) -> bool:
    if type(value) is not bool or value is not False:
        raise ValueError("value must be boolean false")
    return value


def _true_only(value: Any) -> bool:
    if type(value) is not bool or value is not True:
        raise ValueError("value must be boolean true")
    return value


SchemaVersion = Annotated[Literal[1], BeforeValidator(_schema_version)]
FalseOnly = Annotated[Literal[False], BeforeValidator(_false_only)]
TrueOnly = Annotated[Literal[True], BeforeValidator(_true_only)]


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("value must be a finite number")
    return result


FiniteNumber = Annotated[float, BeforeValidator(_finite_number)]


def _unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")


class Verification(Record):
    checked_at: Name
    method: Literal["official_model_pages"]
    scope: Literal["documented_metadata_not_account_access"]
    live_account_probe_performed: StrictBool


class Capabilities(Record):
    text_input: Capability = None
    text_output: Capability = None
    image_input: Capability = None
    audio_input: Capability = None
    video_input: Capability = None
    streaming: Capability = None
    function_calling: Capability = None
    structured_outputs: Capability = None


class Availability(Record):
    configured_enabled: StrictBool
    account_status: Literal["requires_verification", "verified", "unavailable"]


class LongContextPricing(Record):
    input_tokens_gt: PositiveInt
    scope: Literal["full_request"]
    input_multiplier: MoneyString
    output_multiplier: MoneyString
    cached_input_multiplier: MoneyString | None
    cache_write_multiplier: MoneyString | None


class Pricing(Record):
    version: Name
    status: Literal["partially_verified", "verified"]
    service_tier: Literal["standard"]
    unit_tokens: PositiveInt
    input_usd: MoneyString | None
    cached_input_usd: MoneyString | None
    output_usd: MoneyString | None
    cache_write_input_multiplier: MoneyString | None
    promotion_available_at_least_through: Name | None = None
    long_context: LongContextPricing | None
    additional_tool_prices: dict[Name, MoneyString] | None
    requires_verification: tuple[Name, ...]

    @model_validator(mode="after")
    def unique_verification_items(self):
        _unique(self.requires_verification, "pricing requires_verification")
        return self


class ModelEntry(Record):
    tier: Tier
    tier_rank: NonNegativeInt
    provider_model_id: Name
    source_url: Name
    metadata_status: Literal["documentation_verified", "verified"]
    reasoning_efforts: tuple[EffortName, ...]
    capabilities: Capabilities
    context_window_tokens: PositiveInt
    max_output_tokens: PositiveInt
    availability: Availability
    pricing: Pricing

    @model_validator(mode="after")
    def model_invariants(self):
        if not self.reasoning_efforts:
            raise ValueError("reasoning_efforts must not be empty")
        _unique(self.reasoning_efforts, "reasoning_efforts")
        if self.max_output_tokens > self.context_window_tokens:
            raise ValueError("max_output_tokens cannot exceed context_window_tokens")
        return self


class CatalogDocument(Record):
    schema_version: SchemaVersion
    catalog_version: Name
    status: Literal["draft", "active", "retired"]
    provider: Literal["openai"]
    currency: Literal["USD"]
    verification: Verification
    models: dict[Name, ModelEntry]

    @model_validator(mode="after")
    def catalog_invariants(self):
        if not self.models:
            raise ValueError("models must not be empty")
        ranks = tuple(model.tier_rank for model in self.models.values())
        tiers = tuple(model.tier for model in self.models.values())
        _unique(ranks, "model tier ranks")
        _unique(tiers, "model tiers")
        return self


class ComponentRange(Record):
    min: NonNegativeInt
    max: NonNegativeInt

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("component min cannot exceed max")
        return self


class Complexity(Record):
    total_min: NonNegativeInt
    total_max: NonNegativeInt
    components: dict[Name, ComponentRange]
    aggregation: Literal["sum"]
    score_type: Literal["integer"]

    @model_validator(mode="after")
    def totals_match_components(self):
        if not self.components:
            raise ValueError("complexity components must not be empty")
        expected_components = set(ComplexityComponents.model_fields)
        if set(self.components) != expected_components:
            raise ValueError(
                f"complexity components must be exactly {sorted(expected_components)}"
            )
        if self.total_min > self.total_max:
            raise ValueError("complexity total_min cannot exceed total_max")
        if sum(item.min for item in self.components.values()) != self.total_min:
            raise ValueError("component minima do not sum to total_min")
        if sum(item.max for item in self.components.values()) != self.total_max:
            raise ValueError("component maxima do not sum to total_max")
        return self


class CandidateSpec(Record):
    model: Name
    efforts: tuple[EffortName, ...]

    @model_validator(mode="after")
    def efforts_are_ordered_set(self):
        if not self.efforts:
            raise ValueError("candidate efforts must not be empty")
        _unique(self.efforts, "candidate efforts")
        return self


class ComplexityBand(Record):
    min: NonNegativeInt
    max: NonNegativeInt
    candidates: tuple[CandidateSpec, ...]

    @model_validator(mode="after")
    def band_invariants(self):
        if self.min > self.max:
            raise ValueError("complexity band min cannot exceed max")
        if not self.candidates:
            raise ValueError("complexity band candidates must not be empty")
        pairs = tuple((candidate.model, effort) for candidate in self.candidates for effort in candidate.efforts)
        _unique(pairs, "complexity band model/effort pairs")
        return self


class RuleMatch(Record):
    families: tuple[Name, ...] = ()
    flags_all: tuple[Name, ...] = ()
    complexity_min: NonNegativeInt | None = None
    component_min: dict[Name, NonNegativeInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def match_invariants(self):
        if not (self.families or self.flags_all or self.complexity_min is not None or self.component_min):
            raise ValueError("rule match must contain at least one predicate")
        _unique(self.families, "match families")
        _unique(self.flags_all, "match flags_all")
        return self


class FloorRule(Record):
    id: Name
    match: RuleMatch
    strength: Literal["hard", "preferred"]
    min_tier: Tier
    rationale_codes: tuple[Name, ...]

    @model_validator(mode="after")
    def rationale_nonempty(self):
        if not self.rationale_codes:
            raise ValueError("floor rule rationale_codes must not be empty")
        _unique(self.rationale_codes, "floor rule rationale_codes")
        return self


class ModifierEffect(Record):
    add_candidates: tuple[CandidateSpec, ...] = ()
    preferred_min_tier: Tier | None = None
    annotate_only: StrictBool | None = None

    @model_validator(mode="after")
    def exactly_one_effect(self):
        supplied = sum((bool(self.add_candidates), self.preferred_min_tier is not None, self.annotate_only is not None))
        if supplied != 1:
            raise ValueError("modifier effect must define exactly one effect")
        if self.annotate_only is not None and not self.annotate_only:
            raise ValueError("annotate_only may only be true")
        return self


class Modifier(Record):
    id: Name
    match: RuleMatch
    effect: ModifierEffect
    rationale_codes: tuple[Name, ...]

    @model_validator(mode="after")
    def rationale_nonempty(self):
        if not self.rationale_codes:
            raise ValueError("modifier rationale_codes must not be empty")
        _unique(self.rationale_codes, "modifier rationale_codes")
        return self


class SelectionPolicy(Record):
    cold_start: Literal["configured_candidate_order"]
    calibrated: Literal["expected_cost_per_successful_task"]
    calibration_version: Name | None
    tie_break: tuple[Literal["candidate_order", "estimated_cost", "tier_rank", "effort_order"], ...]
    preferred_floor_relaxation: Literal["only_if_no_feasible_preferred_candidate"]
    hard_constraint_conflict: Literal["reject"]
    missing_classifier: Literal["require_classification"]
    low_confidence: Literal["record_uncertainty_without_automatic_tier_jump"]
    floor_candidate_effort_preference: tuple[EffortName, ...]
    constrained_fallback: Literal["eligible_models_by_tier_rank"]
    latency: Literal["enforce_request_deadline_and_record_estimate_uncertainty"]

    @model_validator(mode="after")
    def ordered_values_unique(self):
        if not self.tie_break or not self.floor_candidate_effort_preference:
            raise ValueError("selection order lists must not be empty")
        _unique(self.tie_break, "selection tie_break")
        _unique(self.floor_candidate_effort_preference, "floor effort preference")
        return self


class ContextPolicy(Record):
    include_in_estimate: tuple[Literal["input_tokens", "cached_input_tokens", "cache_write_tokens", "expected_output_tokens", "reasoning_tokens", "retrieval_cost"], ...]
    check_combined_context_and_output_limit: TrueOnly
    allow_silent_truncation: FalseOnly
    retrieval: Literal["explicit_application_strategy_only"]
    cache_assumption: Literal["uncached_unless_evidenced"]
    long_context_threshold_source: Literal["model_pricing"]

    @model_validator(mode="after")
    def unique_estimate_fields(self):
        _unique(self.include_in_estimate, "context include_in_estimate")
        expected = {
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "expected_output_tokens",
            "reasoning_tokens",
            "retrieval_cost",
        }
        if set(self.include_in_estimate) != expected:
            raise ValueError("context include_in_estimate must declare every required v1 estimate bucket")
        return self


class HealthPolicy(Record):
    exclude_states: tuple[Literal["HEALTHY", "DEGRADED", "UNHEALTHY"], ...]
    degraded: Literal["allow_safe_alternate_with_rationale"]
    account_availability: Literal["require_verification_for_live_execution"]

    @model_validator(mode="after")
    def unique_states(self):
        _unique(self.exclude_states, "health exclude_states")
        if set(self.exclude_states) != {"UNHEALTHY"}:
            raise ValueError("health exclude_states must contain exactly UNHEALTHY")
        return self


class EscalationLimits(Record):
    max_total_generation_attempts: PositiveInt | None
    max_quality_escalations: NonNegativeInt | None
    max_infrastructure_retries: NonNegativeInt | None
    max_tool_recoveries: NonNegativeInt | None
    max_elapsed_ms: PositiveInt | None


class QualityEscalation(Record):
    failure_types: tuple[Literal["QUALITY_FAILURE"], ...]
    steps: tuple[Literal["increase_reasoning_effort", "revalidate", "increase_model_tier"], ...]
    revalidation_semantics: Literal["validate_new_attempt_before_next_escalation"]
    tier_change_effort: Literal["reselect_from_policy"]


class Backoff(Record):
    initial_ms: PositiveInt | None
    max_ms: PositiveInt | None
    jitter: Rate | None
    honor_retry_after: StrictBool

    @model_validator(mode="after")
    def range_is_ordered(self):
        if self.initial_ms is not None and self.max_ms is not None and self.initial_ms > self.max_ms:
            raise ValueError("backoff initial_ms cannot exceed max_ms")
        return self


class InfrastructureEscalation(Record):
    failure_types: tuple[Literal["TIMEOUT", "RATE_LIMIT", "PROVIDER_FAILURE"], ...]
    steps: tuple[Literal["retry", "backoff", "health_aware_fallback"], ...]
    automatic_intelligence_escalation: FalseOnly
    fallback_tier: Literal["same_or_lower_within_hard_constraints"]
    backoff: Backoff


class ToolEscalation(Record):
    failure_types: tuple[Literal["TOOL_FAILURE"], ...]
    steps: tuple[Literal["retry_or_recover_tool", "alternate_tool_or_strategy", "recoverable_failure"], ...]
    automatic_intelligence_escalation: FalseOnly


class DiagnosticEscalation(Record):
    failure_types: tuple[Literal["VALIDATION_FAILURE", "MALFORMED_OUTPUT", "UNKNOWN_FAILURE"], ...]
    action: Literal["diagnose_before_quality_escalation"]


class TerminalEscalation(Record):
    failure_types: tuple[Literal["BUDGET_FAILURE", "CAPABILITY_FAILURE"], ...]
    action: Literal["stop_with_structured_failure"]


class EscalationPolicy(Record):
    limits: EscalationLimits
    quality: QualityEscalation
    infrastructure: InfrastructureEscalation
    tool: ToolEscalation
    diagnostic: DiagnosticEscalation
    terminal: TerminalEscalation
    stop_when: tuple[Literal["success", "budget_exhausted", "deadline_exceeded", "attempts_exhausted", "no_safe_candidate", "approval_required"], ...]

    @model_validator(mode="after")
    def failure_partition_and_unique_lists(self):
        lists = (
            self.quality.failure_types,
            self.infrastructure.failure_types,
            self.tool.failure_types,
            self.diagnostic.failure_types,
            self.terminal.failure_types,
        )
        # Recovery programs may intentionally repeat an operation (the approved
        # quality program revalidates after both escalation steps).
        _unique(self.stop_when, "stop_when")
        flattened = tuple(item for values in lists for item in values)
        _unique(flattened, "escalation failure types")
        expected = {failure.value for failure in FailureType}
        if set(flattened) != expected:
            raise ValueError("escalation failure types must partition the failure vocabulary")
        return self


class PolicyDocument(Record):
    schema_version: SchemaVersion
    version: Name
    status: Literal["draft", "active", "retired"]
    objective: Literal["effective_cost_per_successful_task"]
    catalog_version: Name
    budget_version: Name
    validation_version: Name
    autonomous_policy_updates: FalseOnly
    task_families: tuple[Name, ...]
    complexity: Complexity
    complexity_bands: tuple[ComplexityBand, ...]
    task_family_floors: tuple[FloorRule, ...]
    modifiers: tuple[Modifier, ...]
    selection: SelectionPolicy
    context: ContextPolicy
    health: HealthPolicy
    escalation: EscalationPolicy
    rationale_codes: dict[Name, Name]

    @model_validator(mode="after")
    def local_policy_invariants(self):
        if not self.task_families:
            raise ValueError("task_families must not be empty")
        _unique(self.task_families, "task_families")
        if not self.complexity_bands:
            raise ValueError("complexity_bands must not be empty")
        cursor = self.complexity.total_min
        for band in self.complexity_bands:
            if band.min != cursor:
                raise ValueError("complexity bands must partition the total range without gaps or overlaps")
            cursor = band.max + 1
        if cursor != self.complexity.total_max + 1:
            raise ValueError("complexity bands must cover the complete total range")
        ids = tuple(rule.id for rule in self.task_family_floors) + tuple(rule.id for rule in self.modifiers)
        _unique(ids, "policy rule IDs")
        if not self.rationale_codes:
            raise ValueError("rationale_codes must not be empty")
        families = set(self.task_families)
        components = self.complexity.components
        for rule in (*self.task_family_floors, *self.modifiers):
            unknown_families = set(rule.match.families) - families
            if unknown_families:
                raise ValueError(f"rule {rule.id} references unknown task families: {sorted(unknown_families)}")
            for component, threshold in rule.match.component_min.items():
                if component not in components:
                    raise ValueError(f"rule {rule.id} references unknown complexity component {component}")
                bounds = components[component]
                if threshold < bounds.min or threshold > bounds.max:
                    raise ValueError(f"rule {rule.id} component threshold is outside configured bounds")
            if rule.match.complexity_min is not None and not (
                self.complexity.total_min <= rule.match.complexity_min <= self.complexity.total_max
            ):
                raise ValueError(f"rule {rule.id} complexity threshold is outside configured bounds")
            unknown_codes = set(rule.rationale_codes) - set(self.rationale_codes)
            if unknown_codes:
                raise ValueError(f"rule {rule.id} references unknown rationale codes: {sorted(unknown_codes)}")
        return self


class BudgetLimits(Record):
    model_tier_floor: Tier | None = None
    model_tier_ceiling: Tier | None = None
    task_cost_ceiling_usd: MoneyString | None = None
    task_deadline_ms: PositiveInt | None = None
    period_spend_ceiling_usd: MoneyString | None = None
    period: Literal["day", "calendar_month"] | None = None
    live_execution_enabled: StrictBool | None = None


class BudgetDefaults(BudgetLimits):
    model_tier_floor: Tier
    model_tier_ceiling: Tier
    on_exhaustion: Literal["reject"]
    on_floor_ceiling_conflict: Literal["reject"]
    on_unknown_cost: Literal["reject_live_execution"]
    require_finite_task_cost_ceiling_for_execution: StrictBool
    include_costs: tuple[Literal["classification", "generation", "retries", "tools", "validation"], ...]
    shadow_budget: Literal["separate"]
    live_execution_enabled: StrictBool

    @model_validator(mode="after")
    def aggregate_budget_pair_and_costs(self):
        if (self.period_spend_ceiling_usd is None) != (self.period is None):
            raise ValueError("default period spend ceiling and period must accompany each other")
        _unique(self.include_costs, "budget include_costs")
        expected = {"classification", "generation", "retries", "tools", "validation"}
        if set(self.include_costs) != expected:
            raise ValueError("budget include_costs must declare every required v1 cost bucket")
        return self


class OverlayContract(Record):
    key: Literal["application_id"]
    merge: Literal["defaults_then_application_then_request_tightening"]
    unknown_application: Literal["defaults"]
    allowed_fields: tuple[Literal["model_tier_floor", "model_tier_ceiling", "task_cost_ceiling_usd", "task_deadline_ms", "period_spend_ceiling_usd", "period", "live_execution_enabled"], ...]
    request_may_relax_limits: FalseOnly
    policy_hard_floors_may_be_relaxed: FalseOnly
    null_in_overlay: Literal["inherit"]
    period_values: tuple[Literal["day", "calendar_month"], ...]
    period_timezone: Literal["UTC"]

    @model_validator(mode="after")
    def lists_are_unique(self):
        if not self.allowed_fields or not self.period_values:
            raise ValueError("overlay allowlists must not be empty")
        _unique(self.allowed_fields, "overlay allowed_fields")
        _unique(self.period_values, "overlay period_values")
        return self


class BudgetsDocument(Record):
    schema_version: SchemaVersion
    version: Name
    status: Literal["draft", "active", "retired"]
    currency: Literal["USD"]
    defaults: BudgetDefaults
    overlay_contract: OverlayContract
    applications: dict[Name, BudgetLimits]

    @model_validator(mode="after")
    def overlay_schema_matches_applications(self):
        allowed = set(self.overlay_contract.allowed_fields)
        expected = set(BudgetLimits.model_fields)
        if allowed != expected:
            raise ValueError("overlay allowed_fields must match the application overlay schema")
        for application, limits in self.applications.items():
            if not limits.model_fields_set <= allowed:
                raise ValueError(f"application {application} contains a field outside overlay allowed_fields")
            effective_period_limit = (
                limits.period_spend_ceiling_usd
                if limits.period_spend_ceiling_usd is not None
                else self.defaults.period_spend_ceiling_usd
            )
            effective_period = limits.period if limits.period is not None else self.defaults.period
            if (effective_period_limit is None) != (effective_period is None):
                raise ValueError(f"application {application} has an incomplete aggregate period limit")
        return self


class V0Profile(Record):
    kind: Literal["deterministic"]
    checks_when_applicable: tuple[Name, ...]
    semantic_evaluator: None

    @model_validator(mode="after")
    def checks_unique(self):
        if not self.checks_when_applicable:
            raise ValueError("deterministic validation checks must not be empty")
        _unique(self.checks_when_applicable, "validation checks")
        return self


class SemanticProfile(Record):
    kind: Literal["lightweight_semantic", "strong_independent"]
    base_profile: Name
    evaluator_ref: Name


class DomainProfile(Record):
    kind: Literal["application_domain"]
    base_profile: Name
    validator_ref: Name | None
    required_semantic_profile: Name | None
    missing_validator: Literal["reject_execution"]


ValidationProfile = Annotated[V0Profile | SemanticProfile | DomainProfile, Field(discriminator="kind")]


class ScoreScale(Record):
    min: FiniteNumber
    max: FiniteNumber

    @model_validator(mode="after")
    def ordered(self):
        if self.min >= self.max:
            raise ValueError("evaluator score_scale min must be less than max")
        return self


class Evaluator(Record):
    enabled: StrictBool
    model_alias: Name | None
    reasoning_effort: EffortName | None
    rubric_version: Name | None
    score_scale: ScoreScale | None = None
    pass_threshold: FiniteNumber | None
    independence: Literal["separate_call", "separate_call_no_generator_self_grade"]

    @model_validator(mode="after")
    def complete_binding(self):
        fields = (self.model_alias, self.reasoning_effort, self.rubric_version, self.score_scale, self.pass_threshold)
        populated = sum(value is not None for value in fields)
        if populated not in (0, len(fields)):
            raise ValueError("evaluator binding fields must be configured together")
        if self.enabled and populated != len(fields):
            raise ValueError("enabled evaluator requires a complete binding")
        if self.score_scale is not None and self.pass_threshold is not None and not (
            self.score_scale.min <= self.pass_threshold <= self.score_scale.max
        ):
            raise ValueError("evaluator pass_threshold must be within score_scale")
        return self


class EvaluatorBoundary(Record):
    provider_interface: Literal["ModelProvider"]
    budget_scope: Literal["production_task"]
    missing_required_evaluator: Literal["reject_execution"]
    evaluator_error_is_quality_failure: FalseOnly
    always_evaluate_every_task: FalseOnly


class ConsequenceDefault(Record):
    profile: Name
    evidence: Name
    approval_gate: StrictBool
    execution_restrictions: tuple[Name, ...]

    @model_validator(mode="after")
    def restrictions_unique(self):
        _unique(self.execution_restrictions, "execution_restrictions")
        return self


class ShadowSampling(Record):
    unit: Literal["task_id"]
    method: Literal["deterministic_hash"]
    seed: Name
    rate: Rate


class ShadowBudget(Record):
    task_cost_ceiling_usd: MoneyString | None
    period_spend_ceiling_usd: MoneyString | None


class ShadowRoute(Record):
    model: Name
    reasoning_effort: EffortName


class ShadowComparison(Record):
    production: ShadowRoute
    shadow: ShadowRoute


class ShadowEvaluation(Record):
    enabled: StrictBool
    sampling: ShadowSampling
    output_visibility: Literal["telemetry_only"]
    execute_side_effecting_tools: FalseOnly
    budget: ShadowBudget
    comparisons: tuple[ShadowComparison, ...]

    @model_validator(mode="after")
    def enabled_settings(self):
        if self.enabled and (
            not self.comparisons
            or self.budget.task_cost_ceiling_usd is None
            or self.budget.period_spend_ceiling_usd is None
        ):
            raise ValueError("enabled shadow evaluation requires comparisons and finite separate budgets")
        return self


class ValidationDocument(Record):
    schema_version: SchemaVersion
    version: Name
    status: Literal["draft", "active", "retired"]
    default_profile: Name
    raw_prompt_storage: StrictBool
    raw_response_storage: StrictBool
    profiles: dict[Name, ValidationProfile]
    evaluators: dict[Name, Evaluator]
    evaluator_boundary: EvaluatorBoundary
    consequence_defaults: dict[Literal["low", "moderate", "high", "critical"], ConsequenceDefault]
    consequence_changes_generation_tier: FalseOnly
    shadow_evaluation: ShadowEvaluation

    @model_validator(mode="after")
    def validation_references(self):
        if set(self.profiles) != {"V0", "V1", "V2", "V3"}:
            raise ValueError("profiles must define exactly V0, V1, V2 and V3")
        if not isinstance(self.profiles["V0"], V0Profile):
            raise ValueError("V0 must be the deterministic profile")
        if not isinstance(self.profiles["V1"], SemanticProfile) or self.profiles["V1"].kind != "lightweight_semantic":
            raise ValueError("V1 must be the lightweight semantic profile")
        if not isinstance(self.profiles["V2"], SemanticProfile) or self.profiles["V2"].kind != "strong_independent":
            raise ValueError("V2 must be the strong independent profile")
        if not isinstance(self.profiles["V3"], DomainProfile):
            raise ValueError("V3 must be the application domain profile")
        if self.profiles["V3"].validator_ref is not None:
            raise ValueError("domain validator bindings require later-phase registry")
        if self.default_profile not in self.profiles:
            raise ValueError("default_profile references an unknown profile")
        if set(self.consequence_defaults) != {"low", "moderate", "high", "critical"}:
            raise ValueError("consequence_defaults must configure all consequence classes")
        for consequence, settings in self.consequence_defaults.items():
            if settings.profile not in self.profiles:
                raise ValueError(f"consequence {consequence} references an unknown profile")
        edges: dict[str, tuple[str, ...]] = {}
        for name, profile in self.profiles.items():
            refs: list[str] = []
            if isinstance(profile, (SemanticProfile, DomainProfile)):
                refs.append(profile.base_profile)
            if isinstance(profile, DomainProfile) and profile.required_semantic_profile is not None:
                refs.append(profile.required_semantic_profile)
            for ref in refs:
                if ref not in self.profiles:
                    raise ValueError(f"validation profile {name} references unknown profile {ref}")
            edges[name] = tuple(refs)
            if isinstance(profile, SemanticProfile) and profile.evaluator_ref not in self.evaluators:
                raise ValueError(f"validation profile {name} references unknown evaluator")
            if isinstance(profile, SemanticProfile) and profile.evaluator_ref in self.evaluators:
                evaluator = self.evaluators[profile.evaluator_ref]
                expected_independence = (
                    "separate_call"
                    if profile.kind == "lightweight_semantic"
                    else "separate_call_no_generator_self_grade"
                )
                if evaluator.independence != expected_independence:
                    raise ValueError(f"validation profile {name} has an inconsistent evaluator binding")
            if isinstance(profile, DomainProfile) and profile.required_semantic_profile is not None:
                referenced = self.profiles[profile.required_semantic_profile]
                if not isinstance(referenced, SemanticProfile):
                    raise ValueError("required_semantic_profile must reference a semantic profile")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError("validation profile inheritance contains a cycle")
            if name in visited:
                return
            visiting.add(name)
            for reference in edges[name]:
                visit(reference)
            visiting.remove(name)
            visited.add(name)

        for name in edges:
            visit(name)
        level_order = tuple(ValidationLevel)
        for name, references in edges.items():
            if any(level_order.index(ref) > level_order.index(name) for ref in references):
                raise ValueError("validation profile cannot inherit a stronger level")
        return self


@dataclass(frozen=True, slots=True, init=False)
class PolicyBundle:
    """A deeply immutable, validated configuration snapshot."""

    policy: Mapping[str, Any]
    catalog: Mapping[str, Any]
    budgets: Mapping[str, Any]
    validation: Mapping[str, Any]
    content_hash: str

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError("PolicyBundle instances must be created by a validated loader")

    @classmethod
    def _from_validated(cls, documents: Mapping[str, Mapping[str, Any]], content_hash: str) -> "PolicyBundle":
        bundle = object.__new__(cls)
        for name in ("policy", "catalog", "budgets", "validation"):
            object.__setattr__(bundle, name, freeze(dict(documents[name])))
        object.__setattr__(bundle, "content_hash", content_hash)
        return bundle


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, "found an unhashable key", key_node.start_mark
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"found duplicate key {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _hash_documents(documents: Mapping[str, Any]) -> str:
    payload = json.dumps(_canonical(documents), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _validate_cross_document(
    policy: PolicyDocument,
    catalog: CatalogDocument,
    budgets: BudgetsDocument,
    validation: ValidationDocument,
) -> None:
    if policy.catalog_version != catalog.catalog_version:
        raise ValueError("routing policy catalog_version does not match model catalog")
    if policy.budget_version != budgets.version:
        raise ValueError("routing policy budget_version does not match budgets")
    if policy.validation_version != validation.version:
        raise ValueError("routing policy validation_version does not match validation")
    if catalog.currency != budgets.currency:
        raise ValueError("catalog and budget currencies do not match")

    models = catalog.models
    tiers = {model.tier: model.tier_rank for model in models.values()}

    missing_rationale_codes = {code.value for code in RationaleCode} - set(policy.rationale_codes)
    if missing_rationale_codes:
        raise ValueError(
            f"rationale code registry is missing runtime codes: {sorted(missing_rationale_codes)}"
        )

    derived_efforts = set(policy.selection.floor_candidate_effort_preference)
    for alias, model in models.items():
        if model.availability.configured_enabled and not derived_efforts.intersection(model.reasoning_efforts):
            raise ValueError(
                f"floor candidate effort preference has no supported effort for enabled model {alias}"
            )

    def validate_candidate(candidate: CandidateSpec, source: str) -> None:
        if candidate.model not in models:
            raise ValueError(f"{source} references unknown model {candidate.model}")
        supported = set(models[candidate.model].reasoning_efforts)
        unsupported = set(candidate.efforts) - supported
        if unsupported:
            raise ValueError(f"{source} uses unsupported efforts for {candidate.model}: {sorted(unsupported)}")

    for band in policy.complexity_bands:
        for candidate in band.candidates:
            validate_candidate(candidate, "complexity band")
    for modifier in policy.modifiers:
        for candidate in modifier.effect.add_candidates:
            validate_candidate(candidate, f"modifier {modifier.id}")
        if modifier.effect.preferred_min_tier is not None and modifier.effect.preferred_min_tier not in tiers:
            raise ValueError(f"modifier {modifier.id} references unknown tier")
    for floor in policy.task_family_floors:
        if floor.min_tier not in tiers:
            raise ValueError(f"floor {floor.id} references unknown tier")

    defaults = budgets.defaults
    if defaults.model_tier_floor not in tiers or defaults.model_tier_ceiling not in tiers:
        raise ValueError("budget defaults reference an unknown model tier")
    if tiers[defaults.model_tier_floor] > tiers[defaults.model_tier_ceiling]:
        raise ValueError("budget default model tier floor exceeds ceiling")
    for application, limits in budgets.applications.items():
        for tier in (limits.model_tier_floor, limits.model_tier_ceiling):
            if tier is not None and tier not in tiers:
                raise ValueError(f"application {application} references an unknown model tier")
        floor_rank = max(
            tiers[defaults.model_tier_floor],
            tiers[limits.model_tier_floor] if limits.model_tier_floor is not None else tiers[defaults.model_tier_floor],
        )
        ceiling_rank = min(
            tiers[defaults.model_tier_ceiling],
            tiers[limits.model_tier_ceiling]
            if limits.model_tier_ceiling is not None
            else tiers[defaults.model_tier_ceiling],
        )
        if floor_rank > ceiling_rank:
            raise ValueError(f"application {application} model tier floor exceeds ceiling")

    if policy.status == "active" and any(document.status != "active" for document in (catalog, budgets, validation)):
        raise ValueError("active policy requires active referenced snapshots")
    if policy.status == "active":
        enabled_limits: list[tuple[str, Decimal | None, int | None]] = []
        if defaults.live_execution_enabled:
            enabled_limits.append(("budget defaults", defaults.task_cost_ceiling_usd, defaults.task_deadline_ms))
        for application, limits in budgets.applications.items():
            live_enabled = defaults.live_execution_enabled and limits.live_execution_enabled is not False
            if live_enabled:
                enabled_limits.append(
                    (
                        f"application {application}",
                        limits.task_cost_ceiling_usd
                        if limits.task_cost_ceiling_usd is not None
                        else defaults.task_cost_ceiling_usd,
                        limits.task_deadline_ms
                        if limits.task_deadline_ms is not None
                        else defaults.task_deadline_ms,
                    )
                )
        for source, task_ceiling, deadline in enabled_limits:
            if task_ceiling is None or deadline is None:
                raise ValueError(
                    f"{source} enables live execution without a finite task cost ceiling and deadline"
                )
        if enabled_limits:
            for alias, model in models.items():
                if (model.availability.configured_enabled
                        and tiers[defaults.model_tier_floor] <= model.tier_rank <= tiers[defaults.model_tier_ceiling]
                        and (model.pricing.input_usd is None or model.pricing.output_usd is None)):
                    raise ValueError(f"active live model {alias} requires known base input/output prices")
            recovery_values = (
                policy.escalation.limits.max_total_generation_attempts,
                policy.escalation.limits.max_quality_escalations,
                policy.escalation.limits.max_infrastructure_retries,
                policy.escalation.limits.max_tool_recoveries,
                policy.escalation.limits.max_elapsed_ms,
                policy.escalation.infrastructure.backoff.initial_ms,
                policy.escalation.infrastructure.backoff.max_ms,
                policy.escalation.infrastructure.backoff.jitter,
            )
            if any(value is None for value in recovery_values):
                raise ValueError("active live execution requires bounded recovery counters and backoff")

    for evaluator_name, evaluator in validation.evaluators.items():
        if evaluator.model_alias is None:
            continue
        if evaluator.model_alias not in models:
            raise ValueError(f"evaluator {evaluator_name} references unknown model")
        if evaluator.reasoning_effort not in models[evaluator.model_alias].reasoning_efforts:
            raise ValueError(f"evaluator {evaluator_name} uses an unsupported reasoning effort")
    for comparison in validation.shadow_evaluation.comparisons:
        for route in (comparison.production, comparison.shadow):
            if route.model not in models:
                raise ValueError(f"shadow comparison references unknown model {route.model}")
            if route.reasoning_effort not in models[route.model].reasoning_efforts:
                raise ValueError(f"shadow comparison uses unsupported effort for {route.model}")


def bundle_from_documents(
    policy: Mapping[str, Any],
    catalog: Mapping[str, Any],
    budgets: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> PolicyBundle:
    """Validate four already-decoded documents and return an immutable snapshot."""

    try:
        parsed_policy = PolicyDocument.model_validate(policy)
        parsed_catalog = CatalogDocument.model_validate(catalog)
        parsed_budgets = BudgetsDocument.model_validate(budgets)
        parsed_validation = ValidationDocument.model_validate(validation)
        _validate_cross_document(parsed_policy, parsed_catalog, parsed_budgets, parsed_validation)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ConfigurationError(f"invalid configuration bundle: {exc}") from exc

    documents = {
        "policy": parsed_policy.model_dump(mode="python"),
        "catalog": parsed_catalog.model_dump(mode="python"),
        "budgets": parsed_budgets.model_dump(mode="python"),
        "validation": parsed_validation.model_dump(mode="python"),
    }
    return PolicyBundle._from_validated(documents, _hash_documents(documents))


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = yaml.load(stream, Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot load configuration file {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigurationError(f"configuration file {path} must contain a mapping")
    return document


def load_bundle(path: str | Path = "config") -> PolicyBundle:
    """Load and validate the four version-one documents beneath *path*."""

    directory = Path(path)
    return bundle_from_documents(
        policy=_load_yaml(directory / "routing-policy.yaml"),
        catalog=_load_yaml(directory / "models.yaml"),
        budgets=_load_yaml(directory / "budgets.yaml"),
        validation=_load_yaml(directory / "validation.yaml"),
    )


__all__ = [
    "PolicyBundle",
    "bundle_from_documents",
    "load_bundle",
]
