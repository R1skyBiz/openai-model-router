"""Strict wire projections and consuming-application configuration."""
from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (BaseModel, ConfigDict, Field, SecretStr, StrictBool,
                      StrictStr, field_validator, model_validator)

from model_router.core.contracts import Money, Name, Record, FailureType
from model_router.core.execution_contracts import TaskResult
from model_router.core.phase4_contracts import HealthObservation


class ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, validate_default=True)
    base_url: str = "http://127.0.0.1:8000"
    token: SecretStr = Field(repr=False)
    mode: Literal["shadow", "mock", "live"] = "shadow"
    connect_timeout_s: Annotated[float, Field(gt=0, le=60, allow_inf_nan=False)] = 2
    request_timeout_s: Annotated[float, Field(gt=0, le=600, allow_inf_nan=False)] = 30
    default_budget_usd: Money = "0.01"
    safe_retries: Annotated[int, Field(strict=True, ge=0, le=3)] = 1
    allow_paid_classifier: StrictBool = False

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("base URL must be an HTTP(S) origin without credentials")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote router requires HTTPS")
        return value.rstrip("/")

    @field_validator("token")
    @classmethod
    def safe_token(cls, value):
        raw = value.get_secret_value()
        if not raw or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in raw):
            raise ValueError("a nonempty ASCII bearer credential is required")
        return value

    @model_validator(mode="after")
    def paid_mode(self):
        if self.allow_paid_classifier and self.mode != "live":
            raise ValueError("paid classification requires explicit live client mode")
        return self

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None):
        env = os.environ if environment is None else environment
        try:
            paid = env.get("MODEL_ROUTER_ALLOW_PAID_CLASSIFIER", "false")
            if paid not in {"true", "false"}:
                raise ValueError()
            return cls(
                base_url=env.get("MODEL_ROUTER_URL", "http://127.0.0.1:8000"),
                token=env["MODEL_ROUTER_APP_TOKEN"],
                mode=env.get("MODEL_ROUTER_MODE", "shadow"),
                connect_timeout_s=float(env.get("MODEL_ROUTER_CONNECT_TIMEOUT_S", "2")),
                request_timeout_s=float(env.get("MODEL_ROUTER_REQUEST_TIMEOUT_S", "30")),
                default_budget_usd=env.get("MODEL_ROUTER_DEFAULT_BUDGET_USD", "0.01"),
                safe_retries=int(env.get("MODEL_ROUTER_SAFE_RETRIES", "1")),
                allow_paid_classifier=paid == "true",
            )
        except (KeyError, ValueError):
            raise ValueError("Invalid Model Router client environment configuration") from None


class ExecutionResult(TaskResult):
    # Wire JSON may contain a dictionary; the core keeps a provider-owned model.
    structured_output: dict | None = Field(default=None, exclude=True, repr=False)

    @property
    def selected_route(self):
        return self.decisions[-1] if self.decisions else self.initial_decision

    @property
    def latency_ms(self) -> float:
        return (self.updated_at - self.created_at).total_seconds() * 1000

    @model_validator(mode="after")
    def correlated(self):
        if (self.created_at.utcoffset() is None or self.updated_at.utcoffset() is None
                or self.updated_at < self.created_at):
            raise ValueError("invalid task timestamps")
        for item in (*self.decisions, *self.attempts, *self.evaluator_attempts,
                     *((self.initial_decision,) if self.initial_decision else ())):
            if item.task_id != self.task_id or item.trace_id != self.trace_id:
                raise ValueError("inconsistent task correlation")
        for attempt in (*self.attempts, *self.evaluator_attempts):
            for evidence in (attempt.decision, attempt.provider_outcome):
                if evidence and (evidence.task_id != self.task_id or evidence.trace_id != self.trace_id):
                    raise ValueError("inconsistent attempt correlation")
        return self


class Liveness(Record):
    live: StrictBool
    state: Literal["HEALTHY"] | None = None


class Readiness(Record):
    ready: StrictBool
    state: Literal["HEALTHY", "DEGRADED", "UNHEALTHY"]
    blockers: tuple[Name, ...] = ()
    snapshot_id: Name | None = None
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    enabled_operations: tuple[Name, ...] | None = None
    components: tuple[Name, ...] | None = None
    checked_at: datetime | None = None
    live_execution_enabled: StrictBool | None = None
    paid_classifier_enabled: StrictBool | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.ready and (self.state == "UNHEALTHY" or self.blockers):
            raise ValueError("inconsistent readiness")
        return self


class ComponentHealth(Record):
    snapshot_id: Name | None
    config_version: Name | None
    synthetic: StrictBool
    components: tuple[HealthObservation, ...]
    blockers: tuple[Name, ...] = ()
    observed_at: datetime | None = None
    valid_until: datetime | None = None


class RouterErrorBody(Record):
    code: Name
    retryable: StrictBool
    message: StrictStr | None = Field(default=None, repr=False)
    task_id: Name | None = None
    trace_id: Name | None = None
    failure_type: FailureType | None = None
    violated_constraints: tuple[Name, ...] = ()
    policy_version: Name | None = None
