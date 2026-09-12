"""Shared HTTP request envelopes; independent of FastAPI and HTTP transports."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from model_router.core.contracts import Classification, Request, Record


class RouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Request
    classification: Classification


class ExecuteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Request
    classification: Classification | None = None
    idempotency_key: Annotated[str, Field(min_length=1)] | None = None


class ClassifyRouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Request
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]


class IntegrationStatus(Record):
    schema_version: Literal[1] = 1
    mode: Literal["mock", "shadow", "live", "route_only", "unknown"]
    execution_enabled: StrictBool
    live_execution_enabled: StrictBool
    paid_classifier_enabled: StrictBool
    shadow_enabled: StrictBool
