"""Strict, immutable Phase 6 release and activation records.

Release configuration is deliberately separate from routing policy.  It
describes which service operations an operator intends to expose and the
finite operational envelope in which those operations may run.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, StrictBool, StrictInt, StrictStr, model_validator

from model_router.core.contracts import Name, Record


def _money(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("money values must be decimal strings")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("money values must be valid decimal strings") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("money values must be finite and greater than zero")
    return amount


PositiveMoney = Annotated[Decimal, BeforeValidator(_money)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
EnvName = Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Scope = Literal["route", "read", "execute", "health", "classify_route"]


class PolicyVersions(Record):
    policy: Name
    catalog: Name
    budgets: Name
    validation: Name


class PolicyReference(Record):
    directory: Name
    content_sha256: Digest
    versions: PolicyVersions


class FileReference(Record):
    path: Name
    sha256: Digest
    version: Name


class Operations(Record):
    classify_route: StrictBool = False
    route: StrictBool
    read: StrictBool
    execute: StrictBool
    health: StrictBool
    live_provider: StrictBool
    live_classifier: StrictBool
    tools: StrictBool
    shadow: StrictBool
    modalities: tuple[Literal["text"], ...]
    validation_profiles: tuple[Literal["V0"], ...]

    @model_validator(mode="after")
    def safe_initial_surface(self):
        if self.tools or self.shadow:
            raise ValueError('release tools and shadow are not supported')
        if self.live_provider and not self.execute:
            raise ValueError("live_provider requires execute")
        if self.execute and not self.live_provider:
            raise ValueError("execute requires the explicitly guarded live provider")
        if self.live_classifier and not (self.execute or self.classify_route):
            raise ValueError("live_classifier requires execute or classify_route")
        if self.classify_route and not self.live_classifier:
            raise ValueError("classify_route requires live_classifier")
        if self.execute and (
            self.modalities != ("text",)
            or self.validation_profiles != ("V0",)
            or self.tools
            or self.shadow
        ):
            raise ValueError(
                "initial execution support is standard text V0 with tools and shadow disabled"
            )
        if not (self.execute or self.classify_route) and (self.live_provider or self.live_classifier):
            raise ValueError("disabled execution cannot enable live operations")
        return self


class ActionLimits(Record):
    max_total_generation_attempts: PositiveInt
    max_quality_escalations: NonNegativeInt
    max_infrastructure_retries: NonNegativeInt
    max_tool_recoveries: NonNegativeInt
    max_classifier_attempts: Literal[1]
    max_validation_attempts: Literal[1]


class BackoffLimits(Record):
    initial_ms: PositiveInt
    maximum_ms: PositiveInt
    honor_retry_after: Literal[True]

    @model_validator(mode="after")
    def ordered(self):
        if self.initial_ms > self.maximum_ms:
            raise ValueError("backoff initial_ms cannot exceed maximum_ms")
        return self


class OperationalLimits(Record):
    max_preview_records: PositiveInt | None = None
    allocation_id: Name
    application_cost_ceiling_usd: PositiveMoney
    task_cost_ceiling_usd: PositiveMoney
    task_deadline_ms: PositiveInt
    provider_timeout_ms: PositiveInt
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_concurrent_tasks: PositiveInt
    actions: ActionLimits
    backoff: BackoffLimits

    @model_validator(mode="after")
    def budget_and_time_order(self):
        if self.task_cost_ceiling_usd > self.application_cost_ceiling_usd:
            raise ValueError("task cost ceiling cannot exceed application cost ceiling")
        if self.provider_timeout_ms > self.task_deadline_ms:
            raise ValueError("provider timeout cannot exceed task deadline")
        return self


class AuthConfig(Record):
    mode: Literal["application_bearer_sha256"]
    credentials_env: EnvName
    required_scopes: tuple[Scope, ...]
    minimum_token_bytes: PositiveInt

    @model_validator(mode="after")
    def scopes_match_surface(self):
        if self.minimum_token_bytes < 32:
            raise ValueError('application tokens require at least 32 bytes')
        if len(self.required_scopes) != len(set(self.required_scopes)):
            raise ValueError("auth required_scopes contains duplicates")
        return self


class AuthApplicationSource(Record):
    token_env: EnvName
    scopes: tuple[Scope, ...]

    @model_validator(mode="after")
    def nonempty_unique_scopes(self):
        if not self.scopes or len(self.scopes) != len(set(self.scopes)):
            raise ValueError("application scopes must be a nonempty set")
        return self


class DatabaseConfig(Record):
    url_env: EnvName
    journal_path_env: EnvName
    allowed_dialects: tuple[Literal["sqlite", "postgresql"], ...]
    required_migration_revision: Name
    connect_timeout_ms: PositiveInt
    pool_size: PositiveInt

    @model_validator(mode="after")
    def dialects_unique(self):
        if not self.allowed_dialects or len(self.allowed_dialects) != len(set(self.allowed_dialects)):
            raise ValueError("database allowed_dialects must be a nonempty set")
        return self


class OutboxConfig(Record):
    delivery: Literal["at_least_once"]
    batch_size: PositiveInt
    lease_ms: PositiveInt
    max_delivery_attempts: PositiveInt
    retry_backoff_ms: PositiveInt
    max_pending_events: NonNegativeInt
    event_id_deduplication: Literal[True]


class EvaluatorConfig(Record):
    mode: Literal["deterministic_v0_only"]
    required_refs: tuple[Name, ...]
    timeout_ms: PositiveInt
    max_attempts: PositiveInt

    @model_validator(mode="after")
    def v0_has_no_remote_refs(self):
        if self.required_refs:
            raise ValueError("deterministic_v0_only cannot require remote evaluators")
        return self


class HealthConfig(Record):
    config_version: Name
    required_components: tuple[Name, ...]
    freshness_ms: PositiveInt
    check_timeout_ms: PositiveInt
    failure_window_ms: PositiveInt
    failure_threshold: PositiveInt
    cooldown_ms: PositiveInt
    half_open_max_probes: PositiveInt
    recovery_success_threshold: PositiveInt
    max_probes_per_run: PositiveInt
    probe_timeout_ms: PositiveInt
    live_probes_enabled: StrictBool
    paid_probes_enabled: StrictBool

    @model_validator(mode="after")
    def components_unique(self):
        if self.live_probes_enabled or self.paid_probes_enabled:
            raise ValueError('release probe scheduling is not supported')
        if not self.required_components or len(self.required_components) != len(set(self.required_components)):
            raise ValueError("health required_components must be a nonempty set")
        if self.paid_probes_enabled and not self.live_probes_enabled:
            raise ValueError("paid probes require live probes")
        if self.recovery_success_threshold > self.half_open_max_probes:
            raise ValueError("health recovery threshold exceeds half-open probes")
        return self


class RetentionConfig(Record):
    raw_prompt_storage: Literal[False]
    raw_response_storage: Literal[False]
    task_metadata_days: PositiveInt
    idempotency_days: PositiveInt
    outbox_days: PositiveInt
    budget_evidence: Literal["indefinite"]
    policy_and_pricing_evidence: Literal["indefinite"]
    automatic_destructive_pruning: Literal[False]


class LiveConfig(Record):
    provider: Literal["openai"]
    credential_env: EnvName
    service_tier: Literal["standard"]
    evidence: FileReference | None
    evidence_max_age_hours: PositiveInt
    classifier_config: FileReference | None
    classifier_input_overhead_tokens: NonNegativeInt


class ReleaseConfig(Record):
    schema_version: Literal[1]
    release_id: Name
    policy: PolicyReference
    operations: Operations
    limits: OperationalLimits
    auth: AuthConfig
    database: DatabaseConfig
    outbox: OutboxConfig
    evaluators: EvaluatorConfig
    health: HealthConfig
    retention: RetentionConfig
    live: LiveConfig

    @model_validator(mode="after")
    def cross_block_invariants(self):
        enabled_scopes = {
            name
            for name in ("route", "read", "execute", "health", "classify_route")
            if getattr(self.operations, name)
        }
        if not enabled_scopes.issubset(set(self.auth.required_scopes)):
            raise ValueError("auth scopes must cover every enabled operation")
        if self.operations.classify_route and self.limits.max_preview_records is None:
            raise ValueError("classify_route requires a finite preview record allocation")
        if self.operations.classify_route and self.database.required_migration_revision != "0004_routing_previews":
            raise ValueError("classify_route requires the preview migration")
        live_enabled = self.operations.live_provider or self.operations.live_classifier
        if live_enabled and self.live.evidence is None:
            raise ValueError("enabled live operations require immutable live evidence")
        if self.operations.live_classifier and self.live.classifier_config is None:
            raise ValueError("enabled live classifier requires immutable classifier config")
        if self.database.pool_size < self.limits.max_concurrent_tasks:
            raise ValueError("database pool must cover the process concurrency ceiling")
        if self.health.probe_timeout_ms > self.health.check_timeout_ms:
            raise ValueError("health probe timeout cannot exceed check timeout")
        return self


class LiveModelEvidence(Record):
    provider_model_id: Name
    access_verified: Literal[True]
    pricing_version: Name
    input_usd: PositiveMoney
    cached_input_usd: PositiveMoney
    output_usd: PositiveMoney
    cache_write_input_multiplier: PositiveMoney
    reasoning_efforts: tuple[Literal["none", "low", "medium", "high", "xhigh", "max"], ...]
    source_url: Name

    @model_validator(mode="after")
    def effort_set(self):
        if not self.reasoning_efforts or len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("live model reasoning efforts must be a nonempty set")
        return self


class LiveEvidenceDocument(Record):
    credential_sha256: Digest
    schema_version: Literal[1]
    evidence_id: Name
    provider: Literal["openai"]
    verified_at: datetime
    account_access_verified: Literal[True]
    pricing_verified: Literal[True]
    models: dict[Name, LiveModelEvidence]

    @model_validator(mode="after")
    def aware_and_nonempty(self):
        if self.verified_at.utcoffset() is None:
            raise ValueError("live evidence verified_at must include a timezone")
        if not self.models:
            raise ValueError("live evidence must contain at least one model")
        return self


class RuntimeEvidence(Record):
    database_reachable: StrictBool = False
    database_dialect: Literal["sqlite", "postgresql"] | None = None
    database_revision: StrictStr | None = None
    outbox_ready: StrictBool = False
    health_ready: StrictBool = False
    health_config_version: StrictStr | None = None
    health_observed_at: datetime | None = None
    healthy_components: tuple[Name, ...] = ()
    evaluator_refs: tuple[Name, ...] = ()


class ApplicationCredential(Record):
    application_id: Name
    credential_digest: Digest
    scopes: tuple[Scope, ...]


class PreflightCheck(Record):
    name: Name
    passed: StrictBool
    detail: Name


class PreflightReport(Record):
    release_id: Name
    release_sha256: Digest
    checked_at: datetime
    ready: StrictBool
    enabled_operations: tuple[Name, ...]
    checks: tuple[PreflightCheck, ...]
    blockers: tuple[Name, ...]


class ActivationReport(Record):
    paid_classifier_enabled: StrictBool | None = None
    activation_id: Name
    release_id: Name
    release_sha256: Digest
    activated_at: datetime
    enabled_operations: tuple[Name, ...]
    operation_scope: Name
    live_execution_enabled: StrictBool
    manifest: dict[str, Any]
    checks: tuple[PreflightCheck, ...]


__all__ = [
    "ApplicationCredential",
    "ActivationReport",
    "FileReference",
    "LiveEvidenceDocument",
    "PreflightCheck",
    "PreflightReport",
    "ReleaseConfig",
    "RuntimeEvidence",
]
