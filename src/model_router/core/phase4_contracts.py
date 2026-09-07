"""Core-owned immutable Phase 4 operational records; no adapter dependencies."""
from datetime import datetime
from typing import Literal
from pydantic import Field, StrictBool, model_validator
from model_router.core.contracts import Record, Name, Count, Duration, Money, Effort, FailureType

class EvaluatorBinding(Record):
    ref: Name
    model_alias: Name
    reasoning_effort: Effort
    rubric_version: Name
    rubric: Name
    score_min: float = Field(strict=True, allow_inf_nan=False)
    score_max: float = Field(strict=True, allow_inf_nan=False)
    pass_threshold: float = Field(strict=True, allow_inf_nan=False)
    max_output_tokens: Duration
    max_input_tokens: Duration
    timeout_ms: Duration
    max_retries: Count
    backoff_ms: Count
    @model_validator(mode='after')
    def bounds(self):
        if not self.score_min < self.score_max or not self.score_min <= self.pass_threshold <= self.score_max:
            raise ValueError('invalid evaluator score bounds')
        return self

class HealthConfig(Record):
    version: Name
    freshness_ms: Duration
    failure_window_ms: Duration
    failure_threshold: Duration
    cooldown_ms: Duration
    half_open_max_probes: Duration
    recovery_success_threshold: Duration
    max_probes_per_run: Duration
    probe_timeout_ms: Duration
    live_probes_enabled: StrictBool = False
    required_components: tuple[Name, ...]
    @model_validator(mode='after')
    def bounded_recovery(self):
        if self.recovery_success_threshold > self.half_open_max_probes:
            raise ValueError('recovery threshold exceeds probe allowance')
        return self

class HealthObservation(Record):
    component: Name
    model: Name | None = None
    capability: Name | None = None
    state: Literal['HEALTHY', 'DEGRADED', 'UNHEALTHY']
    observed_at: datetime
    valid_until: datetime
    last_success_at: datetime | None = None
    required: StrictBool = True
    check_status: Literal['observed', 'missing', 'stale', 'disabled'] = 'observed'
    failure: FailureType | None = None
    failure_count: Count = 0
    circuit_state: Literal['closed', 'open', 'half_open'] = 'closed'
    latency_ms: Count | None = None
    @model_validator(mode='after')
    def timestamps(self):
        if any(x.utcoffset() is None for x in (self.observed_at, self.valid_until)) or self.valid_until <= self.observed_at:
            raise ValueError('health requires ordered aware timestamps')
        return self

class HealthSnapshot(Record):
    snapshot_id: Name
    config_version: Name
    observed_at: datetime
    valid_until: datetime
    synthetic: StrictBool = True
    observations: tuple[HealthObservation, ...] = ()

class Phase4Config(Record):
    schema_version: Literal[1]
    version: Name
    synthetic_only: Literal[True]
    evaluators: tuple[EvaluatorBinding, ...]
    domain_validator_ref: Name | None
    domain_cost_upper_bound_usd: Money
    health: HealthConfig
    @model_validator(mode='after')
    def unique(self):
        if len({b.ref for b in self.evaluators}) != len(self.evaluators):
            raise ValueError('duplicate evaluator binding')
        return self
