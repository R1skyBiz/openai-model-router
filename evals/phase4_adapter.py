"""Execute the authored evaluator-infrastructure case through Phase 4.

Scenario events are inputs only.  The adapter never reads the independent
expected envelope, which remains solely the grader's concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.phase1_adapter import project as project_route
from evals.phase3_adapter import DEFERRED_CASE, _inputs, _limits, _success, _trace
from evals.schema import Observation
from model_router.core.contracts import FailureType, RouteDecision
from model_router.core.execution_contracts import ExecutionControls, TaskResult
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.execution.admission import MemoryBudgetAuthority
from model_router.execution.clock import MockClock
from model_router.execution.orchestrator import ExecutionDependencies, execute
from model_router.execution.provider import MockProvider, request_evidence
from model_router.policy.loader import PolicyBundle
from model_router.policy.phase4 import load_phase4
from model_router.storage import SQLiteTaskRepository, create_schema
from model_router.validation import EvaluatorScore, MockEvaluator, V0Validator, ValidationService


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Phase4ScenarioExecution:
    task: TaskResult
    provider_requests: tuple[dict[str, object], ...]
    evaluator_requests: tuple[dict[str, object], ...]
    sleep_calls: tuple[int, ...]


def _known_usage(input_tokens: int = 4, output_tokens: int = 1) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )


def _evaluator_timeout(request):
    return ProviderFailure(
        **request_evidence(request),
        failure_type=FailureType.TIMEOUT,
        source="provider",
        stage="invocation",
        cause_code="provider_timeout",
        retryable=True,
        usage=_known_usage(0, 0),
    )


def _evaluator_pass(request):
    return ProviderResult(
        **request_evidence(request),
        response_status="completed",
        structured_output=EvaluatorScore(score=0.9),
        usage=_known_usage(),
    )


def execute_case(
    case, bundle: PolicyBundle, directory: str | Path | None = None
) -> Phase4ScenarioExecution:
    if case.id != DEFERRED_CASE:
        raise ValueError("Phase 4 adapter only owns evaluator_infrastructure")
    if case.scenario is None or tuple(case.scenario.events) != ("evaluator_timeout",):
        raise ValueError("unsupported Phase 4 evaluator scenario")

    request, classification, environment = _inputs(case)
    limits = _limits(case, environment)
    clock = MockClock(environment.clock)
    provider = MockProvider([_success(case)])
    evaluator = MockEvaluator([_evaluator_timeout, _evaluator_pass])
    phase4 = load_phase4(ROOT / "config/phase4.yaml", bundle)
    semantic = ValidationService(phase4, evaluator, bundle)
    balance = (
        environment.remaining_usd
        if environment.remaining_usd is not None
        else limits.task_cost_ceiling_usd
    )
    authority = MemoryBudgetAuthority({request.task_id: balance})

    def run_at(root: Path) -> TaskResult:
        repository = SQLiteTaskRepository(
            f"sqlite:///{root / 'phase4-evaluator.sqlite3'}",
            journal_path=root / "phase4-evaluator-pending.jsonl",
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
                semantic=semantic,
            ),
            supplied_classification=classification,
        )

    if directory is None:
        with TemporaryDirectory(prefix="model-router-phase4-") as temporary:
            task = run_at(Path(temporary))
    else:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        task = run_at(target)
    return Phase4ScenarioExecution(
        task=task,
        provider_requests=tuple(provider.requests),
        evaluator_requests=tuple(evaluator.requests),
        sleep_calls=tuple(clock.sleep_calls),
    )


def project(case, execution: Phase4ScenarioExecution) -> Observation:
    task = execution.task
    if not isinstance(task.initial_decision, RouteDecision):
        raise ValueError("execution lacks a valid initial route")
    base = project_route(case.id, task.initial_decision)
    retries = tuple(
        action for action in task.recovery_actions if action.action == "retry_evaluator"
    )
    evaluator_failure = next(
        (
            attempt.failure
            for attempt in task.evaluator_attempts
            if attempt.failure is not None
        ),
        None,
    )
    rationale = list(base.rationale_codes)
    for action in retries:
        rationale.extend(code for code in action.rationale_codes if code not in rationale)
    facts = dict(base.facts)
    facts.update(
        task_status=task.status.value,
        generation_attempts=task.counters.generation_attempts,
        provider_dispatches=len(execution.provider_requests),
        evaluator_dispatches=len(execution.evaluator_requests),
        evaluator_attempts=len(task.evaluator_attempts),
        evaluator_backoff_ms=sum(execution.sleep_calls),
        failure_source=None if evaluator_failure is None else evaluator_failure.source,
        production_generation_cost_usd=(
            None
            if task.production_generation_cost_usd is None
            else str(task.production_generation_cost_usd)
        ),
        production_validation_cost_usd=(
            None
            if task.production_validation_cost_usd is None
            else str(task.production_validation_cost_usd)
        ),
    )
    return base.model_copy(
        update={
            "rationale_codes": rationale,
            "execution_readiness": "ready" if task.attempts else "blocked",
            "recovery": [_trace(action) for action in retries],
            "facts": facts,
        }
    )


def observe(case, bundle: PolicyBundle, directory: str | Path | None = None):
    execution = execute_case(case, bundle, directory)
    return project(case, execution), execution


__all__ = ["Phase4ScenarioExecution", "execute_case", "observe", "project"]
