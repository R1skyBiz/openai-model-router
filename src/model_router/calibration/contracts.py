"""Version-one experiment boundary, independent of production telemetry."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from enum import StrEnum
from pydantic import Field, StrictBool, StrictStr, model_validator
from model_router.core.contracts import Record, Name, Money, Count, Duration, Effort, Context, Classification
from model_router.core.provider_contracts import ProviderUsage

class Disposition(StrEnum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    UNKNOWN = 'UNKNOWN'
    INVALID = 'INVALID'
    NEEDS_REVIEW = 'NEEDS_REVIEW'

class DeterministicRule(Record):
    kind: Literal['exact', 'numeric', 'schema', 'fields', 'invariant', 'fixture']
    expected: object | None = Field(default=None, repr=False)
    tolerance: Money = '0'
    required_fields: tuple[Name, ...] = ()
    forbidden_fields: tuple[Name, ...] = ()
    registry_ref: Name | None = None

class Rubric(Record):
    rubric_id: Name
    version: Name
    instructions: StrictStr = Field(repr=False)
    score_min: Money = '0'
    score_max: Money = '1'
    threshold: Money = '0.8'
    reference_facts: tuple[StrictStr, ...] = Field(default=(), repr=False)
    @model_validator(mode='after')
    def scale(self):
        if not self.score_min <= self.threshold <= self.score_max or self.score_min == self.score_max:
            raise ValueError('invalid rubric scale')
        return self

class GradingPlan(Record):
    deterministic: tuple[DeterministicRule, ...] = ()
    rubric: Rubric | None = None
    human_review: StrictBool = False
    deterministic_authoritative: StrictBool = True
    @model_validator(mode='after')
    def present(self):
        if not self.deterministic and self.rubric is None and not self.human_review:
            raise ValueError('case requires a grading plan')
        return self

class OutputContract(Record):
    format: Literal['text', 'json'] = 'text'
    json_schema: dict | None = Field(default=None, repr=False)
    constraints: tuple[StrictStr, ...] = ()

class ToolPolicy(Record):
    available: tuple[Name, ...] = ()
    side_effects: Literal[False] = False

class CalibrationCase(Record):
    schema_version: Literal[1] = 1
    case_id: Name
    corpus_version: Name
    task_family_hint: Name | None = None
    source_kind: Literal['historical_real', 'authored_realistic', 'application_replay', 'coding_fixture', 'synthetic_control']
    task: StrictStr = Field(repr=False)
    instructions: StrictStr = Field(default='', repr=False)
    context_text: StrictStr = Field(default='', repr=False)
    requirements: tuple[Name, ...] = ('text_input', 'text_output')
    consequence: Literal['low', 'moderate', 'high', 'critical'] = 'low'
    context: Context
    deadline_ms: Duration = 30000
    output_contract: OutputContract = Field(default_factory=OutputContract)
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)
    grading: GradingPlan
    privacy: Literal['public', 'internal', 'sensitive', 'restricted']
    tags: tuple[Name, ...] = ()
    notes: StrictStr = Field(default='', repr=False)
    reference_metadata: dict = Field(default_factory=dict, repr=False)

class CorpusManifest(Record):
    schema_version: Literal[1] = 1
    corpus_version: Name
    corpus_sha256: Name
    case_count: Count
    privacy: Literal['public', 'internal', 'sensitive', 'restricted']
    description: StrictStr = ''
    case_hashes: dict[Name, Name] = Field(default_factory=dict)

class Strategy(Record):
    name: Name
    kind: Literal['router', 'fixed']
    model: Name | None = None
    effort: Effort | None = None
    recovery_enabled: StrictBool = False
    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'fixed' and (self.model is None or self.effort is None or self.recovery_enabled):
            raise ValueError('fixed strategies require model/effort and one attempt')
        if self.kind == 'router' and (self.model is not None or self.effort is not None):
            raise ValueError('router selects its own model/effort')
        return self

class EvaluatorConfig(Record):
    model: Name
    effort: Effort
    max_input_tokens: Duration
    max_output_tokens: Duration
    timeout_ms: Duration
    retries: Count = 0

class ExperimentConfig(Record):
    schema_version: Literal[1] = 1
    version: Name
    strategies: tuple[Strategy, ...]
    seed: Count = 1
    min_cohort_size: Duration = 30
    aggregate_cap_usd: Money
    max_input_tokens: Duration
    max_output_tokens: Duration
    input_overhead_tokens: Count = 1024
    max_generation_attempts: Duration = 1
    deadline_ms: Duration = 30000
    evaluator: EvaluatorConfig | None = None
    adjudicator: EvaluatorConfig | None = None
    adjudication_sample_rate: Money = '0'
    max_adjudications: Count = 0
    production_validation: Literal['V0'] = 'V0'
    material_cost_ratio: Money = '1.1'
    policy_directory: Name = 'config'
    classifier_path: Name = 'config/classifier.yaml'
    release_manifest: Name | None = None
    live_enabled: StrictBool = False
    privacy_policy_version: Name = 'calibration-privacy-v1'
    allowed_privacy: tuple[Literal['public', 'internal', 'sensitive', 'restricted'], ...] = ('public',)
    capture_review_outputs: StrictBool = False
    allocation_id: Name | None = None
    allocation_cap_usd: Money | None = None
    allocation_directory: Name | None = None
    @model_validator(mode='after')
    def valid(self):
        if self.aggregate_cap_usd <= 0 or self.adjudication_sample_rate > 1 or self.material_cost_ratio < 1:
            raise ValueError('invalid experiment bounds')
        if len(self.strategies) < 2 or len({s.name for s in self.strategies}) != len(self.strategies):
            raise ValueError('at least two uniquely named strategies required')
        return self

class CallEvidence(Record):
    call_id: Name
    purpose: Literal['classification', 'generation', 'production_validation', 'judge', 'adjudication']
    model: Name | None = None
    effort: Effort | None = None
    cost_usd: Money | None
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    status: Literal['completed', 'failed', 'unknown', 'started']
    failure_type: Name | None = None
    pricing_version: Name | None = None
    attempt_number: Duration = 1

class SemanticScore(Record):
    rubric_id: Name
    rubric_version: Name
    score: Money | None = None
    status: Literal['scored', 'error']
    calls: tuple[CallEvidence, ...] = ()

class Grade(Record):
    candidate_id: Name
    disposition: Disposition
    deterministic: Disposition | None = None
    primary: SemanticScore | None = None
    adjudicator: SemanticScore | None = None
    disagreement: StrictBool = False
    human_review_needed: StrictBool = False
    evidence_codes: tuple[Name, ...] = ()
    output_reference: Name | None = None

class BlindCandidate(Record):
    candidate_id: Name
    task: StrictStr = Field(exclude=True, repr=False)
    instructions: StrictStr = Field(exclude=True, repr=False)
    context_text: StrictStr = Field(exclude=True, repr=False)
    output: StrictStr | None = Field(exclude=True, repr=False)
    output_contract: OutputContract
    grading: GradingPlan
    complete: StrictBool = True

class StrategyRun(Record):
    strategy_run_id: Name
    case_id: Name
    strategy: Strategy
    input_sha256: Name
    validation_signature: Name
    policy_version: Name
    calls: tuple[CallEvidence, ...] = ()
    classification: Classification | None = None
    route_rationale: tuple[Name, ...] = ()
    recovery_actions: tuple[Name, ...] = ()
    initial_model: Name | None = None
    initial_effort: Effort | None = None
    initial_generation_passed: StrictBool | None = None
    execution_status: Literal['completed', 'failed', 'unknown', 'invalid']
    complete: StrictBool = False
    output: StrictStr | None = Field(default=None, exclude=True, repr=False)
    grade: Grade | None = None
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    task_family: Name | None = None
    complexity_band: Name | None = None
    source_kind: Name
    consequence: Name
    tags: tuple[Name, ...] = ()

class RunManifest(Record):
    schema_version: Literal[1] = 1
    run_id: Name
    created_at: datetime
    corpus: CorpusManifest
    policy_version: Name
    policy_sha256: Name
    model_catalog: dict
    pricing_snapshot: dict
    classifier: dict
    rubrics: tuple[dict, ...]
    config: ExperimentConfig
    software_commit: Name | None = None
    offline: StrictBool
    strategy_order: dict[str, tuple[str, ...]]

class CalibrationRun(Record):
    manifest: RunManifest
    strategy_runs: tuple[StrategyRun, ...] = ()
    status: Literal['completed', 'stopped', 'started']
    stop_reason: Name | None = None

class BudgetPlan(Record):
    cases: Count
    strategies: Count
    maximum_generation_calls: Count
    maximum_classifier_calls: Count
    maximum_evaluator_calls: Count
    estimated_upper_bound_usd: Money | None
    configured_cap_usd: Money
    admissible: StrictBool
    blockers: tuple[Name, ...] = ()
