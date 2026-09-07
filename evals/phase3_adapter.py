"""Execute authored recovery scripts through the real offline orchestrator.

Scenario events are adapter inputs.  Expected envelopes are deliberately never
read here; the independent grader remains the only consumer of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from evals.phase1_adapter import FIXTURES, adapt_inputs, project as project_route
from evals.schema import Observation, TraceStep
from model_router.core.contracts import EnvironmentSnapshot, FailureType, RouteDecision
from model_router.core.execution_contracts import (
    ExecutionControls,
    ExecutionLimits,
    Failure,
    TaskResult,
    ToolCall,
    ToolOutcome,
    ValidationOutcome,
)
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.execution.admission import MemoryBudgetAuthority
from model_router.execution.clock import MockClock
from model_router.execution.orchestrator import ExecutionDependencies, execute
from model_router.execution.provider import MockProvider, request_evidence
from model_router.execution.tools import MockToolExecutor
from model_router.policy.loader import PolicyBundle
from model_router.router import route
from model_router.storage import SQLiteTaskRepository, create_schema
from model_router.validation.v0 import DeterministicCheck, V0Validator


DEFERRED_CASE = "evaluator_infrastructure"
DEFERRED_REASON = (
    "Phase 4: V1 evaluator execution is unavailable; stronger validation blocks before generation."
)
_ACTION_EVENTS = frozenset(
    {
        "confirmed_quality_failure",
        "validated_success",
        "provider_timeout",
        "rate_limit_retry_after_500ms",
        "provider_failure",
        "tool_timeout",
        "tool_success",
        "tool_api_failure",
        "side_effect_timeout_no_idempotency",
        "malformed_structured_output",
        "validation_check_failed_unknown_cause",
        "unknown_failure",
        "budget_failure",
        "capability_failure",
    }
)


@dataclass(frozen=True)
class ScenarioExecution:
    task: TaskResult
    provider_requests: tuple[dict[str, object], ...]
    tool_calls: tuple[dict[str, object], ...]
    sleep_calls: tuple[int, ...]
    projection_horizon: int


def skip_reason(case) -> str | None:
    if case.scenario is None:
        return "Phase 3 adapter requires an authored recovery scenario."
    if case.id == DEFERRED_CASE:
        return DEFERRED_REASON
    return None


def _inputs(case):
    """Reuse Phase 1 fact translation after removing only the scenario marker."""

    if case.scenario is None:
        raise ValueError("case is outside Phase 3 recovery scope")
    routing_case = case.model_copy(update={"scenario": None})
    return adapt_inputs(routing_case)


def _limits(case, environment: EnvironmentSnapshot) -> ExecutionLimits:
    supplied = case.scenario.limits
    recovery_fixture = json.loads((FIXTURES / "environment.json").read_text())["recovery"]
    baseline = environment.budget
    if baseline.task_cost_ceiling_usd is None:
        raise ValueError("recovery fixture requires a finite task cost ceiling")
    return ExecutionLimits(
        max_total_generation_attempts=supplied["max_total_generation_attempts"],
        max_quality_escalations=supplied["max_quality_escalations"],
        max_infrastructure_retries=supplied["max_infrastructure_retries"],
        max_tool_recoveries=supplied["max_tool_recoveries"],
        max_elapsed_ms=supplied["max_elapsed_ms"],
        initial_backoff_ms=recovery_fixture["initial_backoff_ms"],
        max_backoff_ms=recovery_fixture["max_backoff_ms"],
        task_cost_ceiling_usd=baseline.task_cost_ceiling_usd,
    )


def _usage(case) -> ProviderUsage:
    context = case.request.context
    return ProviderUsage(
        input_tokens=context.input_tokens,
        cached_input_tokens=context.cached_input_tokens,
        cache_write_input_tokens=context.cache_write_tokens,
        output_tokens=context.expected_output_tokens,
        reasoning_tokens=0,
        total_tokens=context.input_tokens + context.expected_output_tokens,
    )


def _success(case):
    usage = _usage(case)

    def result(request):
        return ProviderResult(
            **request_evidence(request),
            response_status="completed",
            text="synthetic-success",
            usage=usage,
        )

    return result


def _provider_failure(
    kind: FailureType,
    cause: str,
    *,
    retryable: bool = False,
    retry_after_ms: int | None = None,
    before_return=None,
):
    def result(request):
        if before_return is not None:
            before_return()
        return ProviderFailure(
            **request_evidence(request),
            failure_type=kind,
            source="provider",
            stage="invocation",
            cause_code=cause,
            retryable=retryable,
            retry_after_ms=retry_after_ms,
            usage=ProviderUsage(
                input_tokens=0,
                cached_input_tokens=0,
                cache_write_input_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                total_tokens=0,
            ),
        )

    return result


def _validation_outcome(check: str, kind: FailureType | None) -> ValidationOutcome:
    return ValidationOutcome(
        evaluation_id=str(uuid4()),
        check=check,
        status="passed" if kind is None else "failed",
        failure=(
            None
            if kind is None
            else Failure(
                failure_type=kind,
                source="validation",
                stage="validation",
                cause_code="scripted_validation_failure",
            )
        ),
        evidence_code="scripted_deterministic_evidence" if kind == FailureType.QUALITY_FAILURE else None,
    )


def _scenario_parts(case, environment_state):
    events = tuple(case.scenario.events)
    success = _success(case)
    check_failures: list[FailureType | None] = []
    provider_outcomes = []
    tool_outcomes = []
    tool_call = None
    authorized_tools: tuple[str, ...] = ()

    quality_count = events.count("confirmed_quality_failure")
    if quality_count:
        check_failures.extend([FailureType.QUALITY_FAILURE] * quality_count)
        if "validated_success" in events:
            check_failures.append(None)
        provider_outcomes.extend([success] * len(check_failures))
    elif "malformed_structured_output" in events:
        check_failures.append(FailureType.MALFORMED_OUTPUT)
        provider_outcomes.append(success)
    elif "validation_check_failed_unknown_cause" in events:
        check_failures.append(FailureType.VALIDATION_FAILURE)
        provider_outcomes.append(success)
    elif "provider_timeout" in events:
        provider_outcomes.extend(
            [
                _provider_failure(FailureType.TIMEOUT, "provider_timeout", retryable=True),
                success,
            ]
        )
    elif "rate_limit_retry_after_500ms" in events:
        provider_outcomes.extend(
            [
                _provider_failure(
                    FailureType.RATE_LIMIT,
                    "rate_limited",
                    retryable=True,
                    retry_after_ms=500,
                ),
                success,
            ]
        )
    elif "provider_failure" in events:
        def change_health():
            current = environment_state["snapshot"]
            requested = case.environment.overrides.get("health", {}).get("on_event", {})
            models = dict(current.models)
            for alias, state in requested.items():
                models[alias] = models[alias].model_copy(update={"state": state})
            environment_state["snapshot"] = current.model_copy(update={"models": models})

        provider_outcomes.append(
            _provider_failure(
                FailureType.PROVIDER_FAILURE,
                "provider_unavailable",
                retryable=True,
                before_return=change_health,
            )
        )
        # Outage-fallback scenarios intentionally stop their authored projection
        # at the recovery choice, but the real orchestrator still dispatches the
        # proposed route and completes its bounded execution.
        if case.id == "provider_outage_fallback":
            provider_outcomes.append(success)
    elif "unknown_failure" in events:
        provider_outcomes.append(
            _provider_failure(FailureType.UNKNOWN_FAILURE, "unknown_failure")
        )
    elif "budget_failure" in events:
        provider_outcomes.append(
            _provider_failure(FailureType.BUDGET_FAILURE, "budget_failure")
        )
    elif "capability_failure" in events:
        provider_outcomes.append(
            _provider_failure(FailureType.CAPABILITY_FAILURE, "capability_failure")
        )
    elif any(event.startswith("tool_") or event.startswith("side_effect_") for event in events):
        provider_outcomes.append(success)
        if "tool_timeout" in events:
            tool_call = ToolCall(
                tool="primary_reader", operation="read", cost_upper_bound_usd="0"
            )
            tool_outcomes.extend(
                [
                    ToolOutcome(
                        tool_event_id="scripted",
                        tool="primary_reader",
                        operation="read",
                        status="failed",
                        failure=Failure(
                            failure_type=FailureType.TOOL_FAILURE,
                            source="tool",
                            stage="execution",
                            cause_code="timeout",
                            retryable=True,
                        ),
                    ),
                    ToolOutcome(
                        tool_event_id="scripted",
                        tool="primary_reader",
                        operation="read",
                        status="succeeded",
                        cost_usd="0",
                    ),
                ]
            )
        elif "authorized_read_only_alternate" in events:
            tool_call = ToolCall(
                tool="primary_reader",
                operation="read",
                alternate_tool="backup_reader",
                cost_upper_bound_usd="0",
            )
            authorized_tools = ("backup_reader",)
            tool_outcomes.extend(
                [
                    ToolOutcome(
                        tool_event_id="scripted",
                        tool="primary_reader",
                        operation="read",
                        status="failed",
                        failure=Failure(
                            failure_type=FailureType.TOOL_FAILURE,
                            source="tool",
                            stage="execution",
                            cause_code="api_failure",
                        ),
                    ),
                    ToolOutcome(
                        tool_event_id="scripted",
                        tool="backup_reader",
                        operation="read",
                        status="succeeded",
                        cost_usd="0",
                    ),
                ]
            )
        elif "side_effect_timeout_no_idempotency" in events:
            tool_call = ToolCall(
                tool="writer",
                operation="create",
                side_effecting=True,
                cost_upper_bound_usd="0",
            )
            tool_outcomes.append(
                ToolOutcome(
                    tool_event_id="scripted",
                    tool="writer",
                    operation="create",
                    status="failed",
                    failure=Failure(
                        failure_type=FailureType.TOOL_FAILURE,
                        source="tool",
                        stage="execution",
                        cause_code="timeout",
                        retryable=True,
                    ),
                )
            )
        else:
            tool_call = ToolCall(
                tool="primary_reader", operation="read", cost_upper_bound_usd="0"
            )
            tool_outcomes.append(
                ToolOutcome(
                    tool_event_id="scripted",
                    tool="primary_reader",
                    operation="read",
                    status="failed",
                    failure=Failure(
                        failure_type=FailureType.TOOL_FAILURE,
                        source="tool",
                        stage="execution",
                        cause_code="api_failure",
                    ),
                )
            )
    else:
        raise ValueError(f"unsupported Phase 3 scenario events: {events}")

    check_name = "scenario_check"
    checks = {}
    if check_failures:
        failures = iter(check_failures)

        def run_check(request, result):
            return _validation_outcome(check_name, next(failures))

        checks[check_name] = DeterministicCheck(run_check)
    controls = ExecutionControls(
        authorized=True,
        authorized_tools=(
            authorized_tools
            if tool_call is None
            else tuple(dict.fromkeys((tool_call.tool, *authorized_tools)))
        ),
        side_effects_authorized=bool(tool_call and tool_call.side_effecting),
        tool_calls=() if tool_call is None else (tool_call,),
        required_checks=() if not checks else (check_name,),
    )
    return provider_outcomes, tool_outcomes, controls, V0Validator(checks)


def _projection_horizon(events) -> int:
    return sum(event in _ACTION_EVENTS for event in events)


def execute_case(case, bundle: PolicyBundle, directory: str | Path | None = None) -> ScenarioExecution:
    reason = skip_reason(case)
    if reason:
        raise ValueError(reason)
    request, classification, environment = _inputs(case)
    if any(
        event.startswith("tool_") or event.startswith("side_effect_")
        for event in case.scenario.events
    ):
        environment = environment.model_copy(
            update={
                "required_tool_charge": True,
                "required_tool_charge_usd": Decimal("0"),
            }
        )
    limits = _limits(case, environment)
    environment_state = {"snapshot": environment}
    provider_outcomes, tool_outcomes, controls, validator = _scenario_parts(
        case, environment_state
    )
    clock = MockClock(environment.clock)
    provider = MockProvider(provider_outcomes)
    tools = MockToolExecutor(tool_outcomes) if controls.tool_calls else None

    initial = route(request, classification, environment, bundle)
    if not isinstance(initial, RouteDecision):
        raise ValueError("recovery scenario initial route was rejected")
    balance = (environment.remaining_usd if environment.remaining_usd is not None else limits.task_cost_ceiling_usd)
    if "remaining_budget_zero" in case.scenario.events:
        balance = initial.estimated_cost.generation_subtotal
    authority = MemoryBudgetAuthority({request.task_id: balance})

    def run_at(root: Path) -> TaskResult:
        database = root / f"{case.id}.sqlite3"
        repository = SQLiteTaskRepository(
            f"sqlite:///{database}", journal_path=root / f"{case.id}-pending.jsonl"
        )
        create_schema(repository.engine)
        dependencies = ExecutionDependencies(
            bundle=bundle,
            environment=lambda: environment_state["snapshot"],
            provider=provider,
            repository=repository,
            budget=authority,
            clock=clock,
            limits=limits,
            controls=controls,
            validator=validator,
            tools=tools,
        )
        return execute(request, dependencies, supplied_classification=classification)

    if directory is None:
        with TemporaryDirectory(prefix="model-router-phase3-") as temporary:
            task = run_at(Path(temporary))
    else:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        task = run_at(root)
    return ScenarioExecution(
        task=task,
        provider_requests=tuple(provider.requests),
        tool_calls=() if tools is None else tuple(tools.calls),
        sleep_calls=tuple(clock.sleep_calls),
        projection_horizon=_projection_horizon(case.scenario.events),
    )


def _trace(action) -> TraceStep:
    return TraceStep(
        failure=None if action.failure is None else action.failure.value,
        action=action.action,
        route=(
            None
            if action.route is None
            else {"model": action.route.model, "effort": action.route.effort.value}
        ),
        validated=action.validated,
        original_failure=(
            None if action.original_failure is None else action.original_failure.value
        ),
    )


def project(case, execution: ScenarioExecution) -> Observation:
    task = execution.task
    if not isinstance(task.initial_decision, RouteDecision):
        raise ValueError("execution lacks a valid initial route")
    base = project_route(case.id, task.initial_decision)
    actions = task.recovery_actions[: execution.projection_horizon]
    rationale = list(base.rationale_codes)
    for action in actions:
        rationale.extend(code for code in action.rationale_codes if code not in rationale)
    attempt_failure = next(
        (attempt.failure for attempt in reversed(task.attempts) if attempt.failure is not None),
        None,
    )
    tool_failure = next(
        (event.failure for event in reversed(task.tool_events) if event.failure is not None),
        None,
    )
    facts = dict(base.facts)
    facts.update(
        task_status=task.status.value,
        generation_attempts=task.counters.generation_attempts,
        provider_dispatches=len(execution.provider_requests),
        tool_dispatches=len(execution.tool_calls),
        projection_horizon=execution.projection_horizon,
        recorded_recovery_actions=len(task.recovery_actions),
        backoff_ms=max((action.backoff_ms for action in actions), default=0),
        failure_source=(tool_failure or attempt_failure).source if (tool_failure or attempt_failure) else None,
    )
    return base.model_copy(
        update={
            "rationale_codes": rationale,
            # An actual generation attempt proves admission even when the Phase
            # 1 preview retains a side-effect placeholder blocker.
            "execution_readiness": "ready" if task.attempts else "blocked",
            "recovery": [_trace(action) for action in actions],
            "facts": facts,
        }
    )


def observe(case, bundle: PolicyBundle, directory: str | Path | None = None):
    execution = execute_case(case, bundle, directory)
    return project(case, execution), execution


def observe_deferred(case, bundle: PolicyBundle, directory: str | Path | None = None):
    """Prove the deferred V1 scenario blocks before provider generation."""

    if case.id != DEFERRED_CASE:
        raise ValueError("only evaluator_infrastructure is deferred")
    request, classification, environment = _inputs(case)
    limits = _limits(case, environment)
    clock = MockClock(environment.clock)
    provider = MockProvider([_success(case)])
    authority = MemoryBudgetAuthority(
        {request.task_id: (environment.remaining_usd if environment.remaining_usd is not None else limits.task_cost_ceiling_usd)}
    )

    def run_at(root: Path):
        repository = SQLiteTaskRepository(
            f"sqlite:///{root / 'evaluator.sqlite3'}",
            journal_path=root / "evaluator-pending.jsonl",
        )
        create_schema(repository.engine)
        return execute(
            request,
            ExecutionDependencies(
                bundle=bundle,
                environment=environment,
                provider=provider,
                repository=repository,
                budget=authority,
                clock=clock,
                limits=limits,
                controls=ExecutionControls(authorized=True),
                validator=V0Validator(),
            ),
            supplied_classification=classification,
        )

    if directory is None:
        with TemporaryDirectory(prefix="model-router-phase3-deferred-") as temporary:
            task = run_at(Path(temporary))
    else:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        task = run_at(root)
    return task, provider
