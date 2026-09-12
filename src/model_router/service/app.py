"""Thin FastAPI adapters; routing and execution policy remain in shared engines."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request as HTTPRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from model_router.core.contracts import (
    Classification,
    ConfigurationError,
    InputError,
    Request,
    RouteRejection,
)
from model_router.core.execution_contracts import (
    IdempotencyConflict,
    RepositoryUnavailable,
    TaskResult,
    TaskStatus,
)
from model_router.execution.orchestrator import ExecutionDependencies, execute
from model_router.execution.provider import MockProvider
from model_router.router import route


from model_router.http_contracts import (
    RouteBody, ExecuteBody, ClassifyRouteBody, IntegrationStatus,
)


def create_app(
    dependencies: ExecutionDependencies,
    *,
    trusted_application_id: str | None = None,
    preview=None,
) -> FastAPI:
    """Create an HTTP adapter around one explicit dependency composition."""

    if not isinstance(dependencies, ExecutionDependencies):
        raise TypeError("dependencies must be an ExecutionDependencies instance")
    if trusted_application_id is not None and not trusted_application_id:
        raise ValueError("trusted_application_id must be non-empty")

    app = FastAPI(title="OpenAI Model Router", version="1")

    @app.post("/v1/classify-route")
    def preview_request(body: ClassifyRouteBody):
        from model_router.execution.preview import classify_route, PreviewUnavailable
        from model_router.core.preview_contracts import PreviewCapacityExceeded
        if trusted_application_id is None:
            return _error_response(401, "authentication_required", "Authentication is required.")
        request = _trusted_request(body.request, trusted_application_id)
        if request is None:
            return _error_response(422, "caller_application_id_forbidden",
                "Application identity is resolved from the authenticated credential.")
        if preview is None:
            return _error_response(503, "preview_disabled", "Paid routing preview is unavailable.")
        if request.policy_version not in (None, preview.bundle.policy['version']):
            return _error_response(422, "policy_version_mismatch", "The requested policy is not active.")
        try:
            value = classify_route(request, body.idempotency_key, preview)
        except IdempotencyConflict:
            return _error_response(409, "idempotency_conflict", "The preview key or task already exists.")
        except PreviewCapacityExceeded:
            return _error_response(429, "preview_capacity_exhausted", "The preview evidence allocation is exhausted.")
        except (PreviewUnavailable, RepositoryUnavailable):
            return _error_response(503, "preview_unavailable", "Paid routing preview is unavailable.")
        status = 200 if value.status == 'completed' else 409 if value.status in {
            'claimed', 'started', 'accounted', 'uncertain'} else 422
        return JSONResponse(status_code=status, content=value.model_dump(mode='json'))

    @app.get("/v1/previews/{preview_id}")
    def get_preview(preview_id: str):
        if trusted_application_id is None:
            return _error_response(401, "authentication_required", "Authentication is required.")
        value = preview.repository.get(preview_id, trusted_application_id) if preview else None
        if value is None:
            return _error_response(404, "preview_not_found", "The preview was not found.")
        return value.model_dump(mode='json')

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        # FastAPI's default includes rejected input values. Never echo them.
        return _error_response(422, "invalid_request", "Request validation failed.")

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _error):
        return _error_response(500, "internal_error", "The request could not be completed.")

    @app.get("/health/live")
    def health_live():
        # Process liveness deliberately performs no dependency or provider I/O.
        return {"live": True, "state": "HEALTHY"}

    @app.get("/health/integration", response_model=IntegrationStatus)
    def integration_status():
        # Composition facts, not health probes or authorization for a future call.
        environment = _environment(dependencies)
        live = dependencies.live is not None
        shadow = dependencies.shadow is not None
        synthetic = environment.synthetic and isinstance(dependencies.provider, MockProvider)
        mode = ("live" if live and not environment.synthetic else
                "shadow" if synthetic and shadow else "mock" if synthetic else
                "route_only" if not dependencies.controls.authorized else "unknown")
        return IntegrationStatus(
            mode=mode,
            execution_enabled=dependencies.controls.authorized,
            live_execution_enabled=live,
            paid_classifier_enabled=preview is not None,
            shadow_enabled=shadow,
        )

    @app.get("/health/ready")
    def health_ready():
        if dependencies.release_readiness is not None:
            try:
                result = dependencies.release_readiness()
                return JSONResponse(status_code=200 if result['ready'] else 503, content=result)
            except Exception:
                return JSONResponse(status_code=503,content={'ready':False,'state':'UNHEALTHY'})
        health = dependencies.health
        if health is None:
            return JSONResponse(
                status_code=503,
                content={
                    "ready": False,
                    "state": "UNHEALTHY",
                    "blockers": ["health_service_unconfigured"],
                    "snapshot_id": None,
                },
            )
        try:
            snapshot = health.snapshot()
            environment = _environment(dependencies, health_snapshot=snapshot)
            status = health.operation_readiness(
                environment,
                execution_authorized=dependencies.controls.authorized,
                finite_limits=dependencies.limits is not None,
                synthetic_provider=isinstance(dependencies.provider, MockProvider),
                snapshot=snapshot,
            )
        except (ConfigurationError, RepositoryUnavailable):
            return JSONResponse(
                status_code=503,
                content={
                    "ready": False,
                    "state": "UNHEALTHY",
                    "blockers": ["dependency_environment_unavailable"],
                    "snapshot_id": None,
                },
            )
        return JSONResponse(
            status_code=200 if status.ready else 503,
            content={
                "ready": status.ready,
                "state": status.state,
                "blockers": list(status.blockers),
                "snapshot_id": snapshot.snapshot_id,
                "observed_at": snapshot.observed_at.isoformat(),
                "valid_until": snapshot.valid_until.isoformat(),
            },
        )

    @app.get("/health/components")
    def health_components():
        if dependencies.release_readiness is not None:
            try:
                result = dependencies.release_readiness()
                return JSONResponse(status_code=200 if result['ready'] else 503,content=result)
            except Exception:
                return JSONResponse(status_code=503,content={'ready':False,'state':'UNHEALTHY'})
        health = dependencies.health
        if health is None:
            return JSONResponse(
                status_code=503,
                content={
                    "snapshot_id": None,
                    "config_version": None,
                    "synthetic": True,
                    "components": [],
                    "blockers": ["health_service_unconfigured"],
                },
            )
        snapshot = health.snapshot()
        return {
            "snapshot_id": snapshot.snapshot_id,
            "config_version": snapshot.config_version,
            "observed_at": snapshot.observed_at.isoformat(),
            "valid_until": snapshot.valid_until.isoformat(),
            "synthetic": snapshot.synthetic,
            "components": [
                item.model_dump(mode="json") for item in snapshot.observations
            ],
        }

    @app.post("/v1/route")
    def route_request(body: RouteBody):
        request = _trusted_request(body.request, trusted_application_id)
        if request is None:
            return _error_response(
                422,
                "caller_application_id_forbidden",
                "Application identity is resolved from the authenticated credential.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        try:
            environment = _environment(dependencies, required_capabilities=request.requirements)
            outcome = route(
                request,
                body.classification,
                environment,
                dependencies.bundle,
            )
        except InputError:
            return _error_response(
                422,
                "invalid_request",
                "The normalized request is not valid for this policy.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        except (ConfigurationError, RepositoryUnavailable):
            return _error_response(
                503,
                "dependency_unavailable",
                "A required routing dependency is unavailable.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )

        if isinstance(outcome, RouteRejection):
            return JSONResponse(status_code=422, content=_route_rejection(outcome))
        return outcome.model_dump(mode="json")

    @app.post("/v1/execute")
    def execute_request(body: ExecuteBody, http_request: HTTPRequest):
        expected_mode = http_request.headers.get("x-model-router-expected-mode")
        if expected_mode is not None:
            status = integration_status()
            if (expected_mode not in {"mock", "live"} or status.mode != expected_mode
                    or not status.execution_enabled
                    or status.live_execution_enabled != (expected_mode == "live")
                    or (expected_mode == "mock" and (status.shadow_enabled or status.paid_classifier_enabled))):
                return _error_response(409, "execution_mode_mismatch",
                    "The requested execution mode is unavailable.",
                    task_id=body.request.task_id, trace_id=body.request.trace_id)
        request = _trusted_request(body.request, trusted_application_id)
        if request is None:
            return _error_response(
                422,
                "caller_application_id_forbidden",
                "Application identity is resolved from the authenticated credential.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        try:
            controls = dependencies.controls
            if body.idempotency_key is not None:
                if (
                    controls.idempotency_key is not None
                    and controls.idempotency_key != body.idempotency_key
                ):
                    return _error_response(
                        422,
                        "idempotency_scope_conflict",
                        "The idempotency key conflicts with trusted execution controls.",
                        task_id=body.request.task_id,
                        trace_id=body.request.trace_id,
                    )
                controls = controls.model_copy(
                    update={"idempotency_key": body.idempotency_key}
                )
            task = execute(
                request,
                replace(dependencies, controls=controls),
                supplied_classification=body.classification,
            )
        except IdempotencyConflict:
            return _error_response(
                409,
                "idempotency_conflict",
                "The idempotency key is already associated with another request.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        except InputError:
            return _error_response(
                422,
                "invalid_request",
                "The normalized request is not valid for this policy.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        except (ConfigurationError, RepositoryUnavailable):
            return _error_response(
                503,
                "dependency_unavailable",
                "A required execution dependency is unavailable.",
                task_id=body.request.task_id,
                trace_id=body.request.trace_id,
            )
        return _task_projection(task, include_output=task.status == TaskStatus.SUCCEEDED)

    @app.get("/v1/tasks/{task_id}")
    def task_request(
        task_id: str,
        view: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        start: str | None = None,
        end: str | None = None,
        application: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        task_family: str | None = None,
        policy_version: str | None = None,
        status: str | None = None,
    ):
        if view is not None:
            if view != "timeline":
                return _error_response(
                    422,
                    "invalid_view",
                    "Only the timeline task view is supported.",
                    task_id=task_id,
                )
            try:
                detail = app.state.telemetry_query.task_detail(
                    task_id,
                    {
                        "start": start,
                        "end": end,
                        "application": application,
                        "model": model,
                        "effort": effort,
                        "task_family": task_family,
                        "policy_version": policy_version,
                        "status": status,
                    },
                    offset=offset,
                    limit=limit,
                )
            except ValueError:
                return _error_response(
                    422,
                    "invalid_filter",
                    "The telemetry query is not valid.",
                    task_id=task_id,
                )
            except RepositoryUnavailable:
                return _error_response(
                    503,
                    "dependency_unavailable",
                    "Telemetry storage is unavailable.",
                    task_id=task_id,
                )
            if detail is None:
                return _error_response(
                    404,
                    "task_not_found",
                    "The requested task was not found.",
                    task_id=task_id,
                )
            return detail
        try:
            task = dependencies.repository.get(task_id)
        except RepositoryUnavailable:
            return _error_response(
                503,
                "dependency_unavailable",
                "Task storage is unavailable.",
                task_id=task_id,
            )
        if task is None or task.application_id != _environment(dependencies).trusted_application_id:
            return _error_response(
                404,
                "task_not_found",
                "The requested task was not found.",
                task_id=task_id,
            )
        return _task_projection(task, include_output=False)

    from model_router.service.telemetry import register_telemetry

    register_telemetry(app, dependencies)
    return app


def _trusted_request(
    request: Request,
    trusted_application_id: str | None,
) -> Request | None:
    if trusted_application_id is None:
        return request
    if request.application_id is not None:
        return None
    return request.model_copy(update={"application_id": trusted_application_id})


def _environment(
    dependencies: ExecutionDependencies,
    *,
    required_capabilities: tuple[str, ...] = (),
    health_snapshot=None,
):
    source = dependencies.environment
    environment = source() if callable(source) else source
    environment = environment.model_copy(update={"clock": dependencies.clock.now()})
    if dependencies.health is not None:
        snapshot = health_snapshot or dependencies.health.snapshot()
        environment = dependencies.health.apply(
            environment,
            required_capabilities=required_capabilities,
            snapshot=snapshot,
        )
    return environment


def _task_projection(task: TaskResult, *, include_output: bool) -> dict[str, Any]:
    payload = task.model_dump(mode="json")
    if include_output:
        payload["output"] = task.output
        payload["structured_output"] = (
            task.structured_output.model_dump(mode="json")
            if task.structured_output is not None
            else None
        )
    return payload


def _route_rejection(rejection: RouteRejection) -> dict[str, Any]:
    return {
        "task_id": rejection.task_id,
        "trace_id": rejection.trace_id,
        "code": "route_rejected",
        "failure_type": rejection.failure_type.value,
        "message": "No route satisfies the supplied constraints.",
        "retryable": rejection.retryable,
        "violated_constraints": list(rejection.violated_constraints),
        "policy_version": rejection.policy_version,
    }


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    trace_id: str | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": status_code >= 500,
    }
    if task_id is not None:
        body["task_id"] = task_id
    if trace_id is not None:
        body["trace_id"] = trace_id
    return JSONResponse(status_code=status_code, content=body)


__all__ = ["ExecuteBody", "RouteBody", "create_app"]
