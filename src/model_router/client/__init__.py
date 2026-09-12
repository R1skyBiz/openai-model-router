"""Stable application-facing client; importing it performs no I/O."""
from .client import (
    RouterClient, ClientError, TransportFailure, RouterTimeout, MalformedResponse,
    RouterFailure, AuthenticationFailure, ClientPolicyError,
)
from .models import ClientConfig, ExecutionResult, Liveness, Readiness, ComponentHealth
from model_router.core.contracts import Request, Classification, Context, Limits, RouteDecision
from model_router.core.preview_contracts import RoutingPreview
from model_router.http_contracts import IntegrationStatus

__all__ = [
    "RouterClient", "ClientConfig", "ExecutionResult", "Request", "Classification",
    "Context", "Limits", "RouteDecision", "RoutingPreview", "IntegrationStatus",
    "Liveness", "Readiness", "ComponentHealth", "ClientError", "TransportFailure",
    "RouterTimeout", "MalformedResponse", "RouterFailure", "AuthenticationFailure",
    "ClientPolicyError",
]
