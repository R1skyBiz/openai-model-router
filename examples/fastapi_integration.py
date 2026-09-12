"""Generic consuming app. Preview-only shadow mode is the default.

Run: uvicorn examples.fastapi_integration:app --port 8001
The host application must add its own end-user authentication and authorization.
"""
from contextlib import asynccontextmanager
import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from model_router.client import (
    RouterClient, ClientConfig, Request, Classification, ClientError, RouterFailure,
    AuthenticationFailure, RouterTimeout, TransportFailure, MalformedResponse,
    ClientPolicyError,
)

logger = logging.getLogger("example.router")


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Request
    classification: Classification


class ExecuteInput(PreviewInput):
    # The explicit execution action should retain these values on the app's job.
    confirm_execution: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=256, repr=False)


def create_app(config: ClientConfig | None = None, *, transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        async with RouterClient(config or ClientConfig.from_env(), transport=transport) as client:
            app.state.router = client
            yield

    app = FastAPI(title="Generic router integration", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, _error):
        return JSONResponse(status_code=422, content={"code": "invalid_application_request"})

    @app.exception_handler(ClientError)
    async def router_error(_request, error):
        if isinstance(error, AuthenticationFailure):
            status, code = 503, "router_credentials_unavailable"
        elif isinstance(error, RouterTimeout):
            status, code = 504, "router_timeout_reconcile_before_resubmitting"
        elif isinstance(error, (TransportFailure, MalformedResponse)):
            status, code = 502, "router_result_unavailable_reconcile_before_resubmitting"
        elif isinstance(error, ClientPolicyError):
            status, code = 409, error.code
        elif isinstance(error, RouterFailure) and error.failure_type == "BUDGET_FAILURE":
            status, code = 422, "budget_rejected"
        else:
            status, code = 503, "router_unavailable"
        # Only fixed client codes and locally supplied opaque identifiers.
        logger.info("router_error code=%s task_id=%s trace_id=%s", code, error.task_id, error.trace_id)
        return JSONResponse(status_code=status, content={"code": code,
            "task_id": error.task_id, "trace_id": error.trace_id})

    @app.get("/router/readiness")
    async def readiness():
        ready = await app.state.router.readiness()
        mode = await app.state.router.integration_status()
        return {"readiness": ready.model_dump(mode="json"), "service": mode.model_dump(mode="json"),
                "client_mode": app.state.router.config.mode}

    @app.post("/preview")
    async def preview(body: PreviewInput):
        ready = await app.state.router.readiness()
        if not ready.ready:
            raise HTTPException(503, "Router is not ready")
        proposed = await app.state.router.route_preview(body.request, body.classification)
        logger.info("router_preview task_id=%s trace_id=%s decision_id=%s",
                    proposed.task_id, proposed.trace_id, proposed.decision_id)
        # The UI displays this proposal. Preview never calls execute.
        return {"task_id": proposed.task_id, "trace_id": proposed.trace_id,
                "model": proposed.selected_model_alias, "effort": proposed.reasoning_effort,
                "validation_version": proposed.validation_version,
                "rationale": proposed.rationale_codes, "estimated_cost": proposed.estimated_cost,
                "constraints": proposed.effective_limits, "executable": proposed.executable}

    @app.post("/execute")
    async def execute(body: ExecuteInput):
        ready = await app.state.router.readiness()
        if not ready.ready:
            raise HTTPException(503, "Router is not ready")
        result = await app.state.router.execute(body.request, classification=body.classification,
                                               idempotency_key=body.idempotency_key)
        logger.info("router_execution task_id=%s trace_id=%s status=%s",
                    result.task_id, result.trace_id, result.status)
        failure = result.failure.failure_type if result.failure else None
        response_status, outcome = {
            "QUALITY_FAILURE": (422, "validation_failed"),
            "VALIDATION_FAILURE": (422, "validation_failed"),
            "MALFORMED_OUTPUT": (422, "validation_failed"),
            "BUDGET_FAILURE": (422, "budget_rejected"),
            "TIMEOUT": (504, "execution_timeout"),
            "PROVIDER_FAILURE": (503, "provider_unavailable"),
        }.get(failure, (200, "succeeded") if result.status == "succeeded" else (409, "execution_not_successful"))
        if (result.failure and result.failure.cause_code == "recovery_attempts_exhausted"
                and any(v.failure and v.failure.failure_type == "QUALITY_FAILURE"
                        for a in result.attempts for v in a.validations)):
            response_status, outcome = 422, "validation_failed"
        content = {"outcome": outcome, "task_id": result.task_id, "trace_id": result.trace_id,
                   "status": result.status, "cost_usd": str(result.total_cost_usd) if result.total_cost_usd is not None else None,
                   "latency_ms": result.latency_ms,
                   "failure": result.failure.model_dump(mode="json") if result.failure else None,
                   "validations": [v.model_dump(mode="json") for a in result.attempts for v in a.validations],
                   "recovery_actions": [item.model_dump(mode="json") for item in result.recovery_actions]}
        if result.status == "succeeded":
            content["output"] = result.output
        return JSONResponse(status_code=response_status, content=content)

    return app


app = create_app()
