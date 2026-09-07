"""Thin FastAPI adapters; routing and execution policy remain in shared engines."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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
from model_router.router import route


class RouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: Request
    classification: Classification


class ExecuteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: Request
    classification: Classification | None = None
    idempotency_key: Annotated[str, Field(min_length=1)] | None = None


def create_app(dependencies: ExecutionDependencies) -> FastAPI:
    """Create an HTTP adapter around one explicit dependency composition."""

    if not isinstance(dependencies, ExecutionDependencies):
        raise TypeError("dependencies must be an ExecutionDependencies instance")

    app = FastAPI(title="OpenAI Model Router", version="1")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        # FastAPI's default includes rejected input values. Never echo them.
        return _error_response(422, "invalid_request", "Request validation failed.")

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _error):
        return _error_response(500, "internal_error", "The request could not be completed.")

    @app.post("/v1/route")
    def route_request(body: RouteBody):
        try:
            environment = _environment(dependencies)
            outcome = route(
                body.request,
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
    def execute_request(body: ExecuteBody):
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
                body.request,
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
    def task_request(task_id: str):
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

    return app


def _environment(dependencies: ExecutionDependencies):
    source = dependencies.environment
    environment = source() if callable(source) else source
    return environment.model_copy(update={"clock": dependencies.clock.now()})


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
