"""Typed FastAPI adapters for read-only Phase 5 telemetry queries."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from model_router.core.execution_contracts import RepositoryUnavailable
from model_router.execution.orchestrator import ExecutionDependencies
from model_router.telemetry.query import TelemetryQuery
from model_router.telemetry.schemas import (
    Efficacy,
    Health,
    Policies,
    Routing,
    Spend,
    Summary,
    TaskDetail,
    TaskList,
)


def _filters(
    start: Annotated[str | None, Query(description="Inclusive aware UTC instant")] = None,
    end: Annotated[str | None, Query(description="Exclusive aware UTC instant")] = None,
    application: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    task_family: str | None = None,
    policy_version: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "application": application,
        "model": model,
        "effort": effort,
        "task_family": task_family,
        "policy_version": policy_version,
        "status": status,
    }


FilterDependency = Annotated[dict[str, Any], Depends(_filters)]


def register_telemetry(
    app: FastAPI,
    dependencies: ExecutionDependencies | None = None,
    *,
    query: TelemetryQuery | None = None,
) -> TelemetryQuery:
    """Register telemetry reads from execution dependencies or an explicit query."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")
    if (dependencies is None) == (query is None):
        raise ValueError("provide exactly one of dependencies or query")
    if query is None:
        if not isinstance(dependencies, ExecutionDependencies):
            raise TypeError("dependencies must be an ExecutionDependencies instance")
        source = dependencies.environment
        scope = (
            (lambda: source().trusted_application_id)
            if callable(source)
            else source.trusted_application_id
        )
        query = TelemetryQuery(
            dependencies.repository,
            now=dependencies.clock.now,
            application_scope=scope,
            synthetic=False,
        )
    elif not isinstance(query, TelemetryQuery):
        raise TypeError("query must be a TelemetryQuery instance")

    app.state.telemetry_query = query
    app.add_exception_handler(RequestValidationError, _invalid_request)

    @app.get("/v1/telemetry/summary", response_model=Summary)
    def summary(filters: FilterDependency):
        return _read(query.summary, filters)

    @app.get("/v1/telemetry/spend", response_model=Spend)
    def spend(filters: FilterDependency):
        return _read(query.spend, filters)

    @app.get("/v1/telemetry/routing", response_model=Routing)
    def routing(filters: FilterDependency):
        return _read(query.routing, filters)

    @app.get("/v1/telemetry/efficacy", response_model=Efficacy)
    def efficacy(filters: FilterDependency):
        return _read(query.efficacy, filters)

    @app.get("/v1/telemetry/health", response_model=Health)
    def health(filters: FilterDependency):
        return _read(query.health, filters)

    @app.get("/v1/telemetry/models", response_model=Efficacy)
    def models(filters: FilterDependency):
        return _read(query.models, filters)

    @app.get("/v1/telemetry/task-families", response_model=Efficacy)
    def task_families(filters: FilterDependency):
        return _read(query.task_families, filters)

    @app.get("/v1/telemetry/policies", response_model=Policies)
    def policies(filters: FilterDependency):
        return _read(query.policies, filters)

    @app.get("/v1/tasks", response_model=TaskList)
    def tasks(
        filters: FilterDependency,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ):
        return _read(query.tasks, filters, offset=offset, limit=limit)

    if not any(getattr(route, "path", None) == "/v1/tasks/{task_id}" for route in app.routes):

        @app.get("/v1/tasks/{task_id}", response_model=TaskDetail)
        def task_detail(
            task_id: str,
            filters: FilterDependency,
            view: str = "timeline",
            offset: Annotated[int, Query(ge=0)] = 0,
            limit: Annotated[int, Query(ge=1, le=500)] = 100,
        ):
            if view != "timeline":
                return _error(422, "invalid_view", "Only the timeline task view is supported.")
            result = _read(query.task_detail, task_id, filters, offset=offset, limit=limit)
            if result is None:
                return _error(404, "task_not_found", "The requested task was not found.", task_id=task_id)
            return result

    return query


def _read(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ValueError:
        return _error(422, "invalid_filter", "The telemetry query is not valid.")
    except RepositoryUnavailable:
        return _error(503, "dependency_unavailable", "Telemetry storage is unavailable.")


async def _invalid_request(_request, _exception):
    return _error(422, "invalid_request", "Request validation failed.")


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": status_code >= 500,
    }
    if task_id is not None:
        body["task_id"] = task_id
    return JSONResponse(status_code=status_code, content=body)


__all__ = ["register_telemetry"]
