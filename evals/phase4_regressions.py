"""Independent declarative Phase 4 operational regression runner."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import yaml

from model_router.core.configuration import bundle_from_documents
from model_router.core.contracts import (
    Classification,
    EnvironmentSnapshot,
    FailureType,
    Request,
)
from model_router.core.execution_contracts import (
    Attempt,
    AttemptStatus,
    ExecutionControls,
    ExecutionLimits,
    ValidationOutcome,
)
from model_router.core.provider_contracts import (
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    ProviderUsage,
)
from model_router.execution.admission import MemoryBudgetAuthority
from model_router.execution.clock import MockClock
from model_router.execution.orchestrator import ExecutionDependencies, execute
from model_router.execution.provider import MockProvider, request_evidence
from model_router.health import HealthService, SyntheticHealthSource
from model_router.policy.loader import load_bundle
from model_router.policy.phase4 import load_phase4
from model_router.router import route
from model_router.shadow import ShadowService
from model_router.storage import SQLiteTaskRepository, create_schema
from model_router.validation import (
    EvaluatorScore,
    MockDomainValidator,
    MockEvaluator,
    V0Validator,
    ValidationService,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evals/phase4_data/regressions.json"
NOW = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)


def load_regressions() -> list[dict]:
    records = json.loads(DATA.read_text())
    if len(records) != 22 or len({record["id"] for record in records}) != 22:
        raise ValueError("Phase 4 regressions require 22 unique cases")
    return records


def _request(*, consequence="low", task_id="phase4-regression", side_effect=False):
    return Request(
        task_id=task_id,
        trace_id=f"trace:{task_id}",
        input="private regression prompt",
        requirements=("text_input", "text_output"),
        consequence=consequence,
        context={"input_tokens": 100, "expected_output_tokens": 100},
        approval_evidence=consequence in {"high", "critical"},
        domain_clearance_evidence=consequence == "critical",
        side_effecting_tool=side_effect,
    )


def _classification(*, simple=False):
    values = (1, 1, 1, 1, 1, 0, 1) if simple else (12, 11, 7, 11, 5, 0, 3)
    return Classification(
        task_family="analysis",
        confidence=1.0,
        provenance="phase4-regression",
        components=dict(
            zip(
                (
                    "reasoning_depth",
                    "step_dependency",
                    "context_synthesis",
                    "technical_precision",
                    "ambiguity",
                    "tool_orchestration",
                    "reliability_requirement",
                ),
                values,
            )
        ),
    )


def _environment(bundle):
    return EnvironmentSnapshot(
        snapshot_id="phase4-regression",
        synthetic=True,
        clock=NOW,
        pricing_version="synthetic",
        health_snapshot_id="health",
        health_observed_at="2026-09-06T19:59:00Z",
        health_valid_until="2026-09-06T21:00:00Z",
        models={
            alias: {"state": "HEALTHY", "account_access": "verified"}
            for alias in bundle.catalog["models"]
        },
        budget={
            "task_cost_ceiling_usd": "10",
            "task_deadline_ms": 30_000,
            "live_execution_enabled": True,
        },
        remaining_usd="10",
        validation={"V0": "configured_mock"},
        recovery_bounded=True,
        durable_retention=True,
    )


def _usage(input_tokens=4, output_tokens=1):
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )


def _generation_success(request):
    return ProviderResult(
        **request_evidence(request),
        response_status="completed",
        text="private production output",
        usage=_usage(10, 10),
    )


def _score(value):
    def result(request):
        return ProviderResult(
            **request_evidence(request),
            response_status="completed",
            structured_output=EvaluatorScore(score=value),
            usage=_usage(),
        )

    return result


def _timeout(request):
    return ProviderFailure(
        **request_evidence(request),
        failure_type=FailureType.TIMEOUT,
        source="provider",
        stage="invocation",
        cause_code="provider_timeout",
        retryable=True,
        usage=_usage(0, 0),
    )


def _provider_request(binding):
    return ProviderRequest(
        task_id="regression",
        trace_id="trace:regression",
        invocation_id="evaluation",
        policy_version="router-v1.0.0",
        catalog_version="models-v1.0.0",
        model_alias=binding.model_alias,
        provider_model_id="configured-by-service",
        reasoning_effort=binding.reasoning_effort,
        input="private task plus candidate",
        max_output_tokens=1,
        timeout_ms=1,
    )


def _semantic_case(case_id):
    bundle = load_bundle(ROOT / "config")
    config = load_phase4(ROOT / "config/phase4.yaml", bundle)
    ref = "strong_independent" if case_id.startswith("v2") else "lightweight"
    binding = next(item for item in config.evaluators if item.ref == ref)
    if case_id == "required_evaluator_unavailable":
        service = ValidationService(
            config.model_copy(update={"evaluators": ()}), MockEvaluator([]), bundle
        )
        decision = SimpleNamespace(
            validation_requirements=SimpleNamespace(
                evaluator_refs=("lightweight",), profiles=("V0", "V1")
            )
        )
        return {"blockers": list(service.readiness(decision))}
    scripted = {
        "v1_pass": _score(1.0),
        "v1_quality_fail": _score(0.1),
        "v1_timeout": _timeout,
        "v2_independent_pass": _score(1.0),
        "v2_failure": _timeout,
    }[case_id]
    service = ValidationService(config, MockEvaluator([scripted]), bundle)
    result, outcome = service.evaluate(binding, _provider_request(binding))
    return {
        "status": outcome.status,
        "failure_type": None if outcome.failure is None else outcome.failure.failure_type.value,
        "failure_source": None if outcome.failure is None else outcome.failure.source,
        "model_alias": result.model_alias,
        "purpose": result.purpose,
    }


def _domain_case(case_id):
    bundle = load_bundle(ROOT / "config")
    config = load_phase4(ROOT / "config/phase4.yaml", bundle).model_copy(
        update={"domain_validator_ref": "mock-domain"}
    )
    domain = MockDomainValidator(
        [ValidationOutcome(evaluation_id="domain", check="mock-domain", status="passed")]
    )
    registry = {"mock-domain": domain} if case_id == "v3_mock_pass" else None
    service = ValidationService(config, MockEvaluator([]), bundle, registry)
    decision = SimpleNamespace(
        validation_requirements=SimpleNamespace(evaluator_refs=(), profiles=("V0", "V3"))
    )
    if case_id == "v3_missing":
        return {"blockers": list(service.readiness(decision))}
    generation_request = _provider_request(config.evaluators[0]).model_copy(
        update={"purpose": "generation"}
    )
    outcome = service.validate_domain(
        _request(consequence="critical"), _generation_success(generation_request)
    )
    return {"status": outcome.status, "domain_calls": domain.call_count}


def _execution_case():
    bundle = load_bundle(ROOT / "config")
    request = _request(consequence="high", task_id="high-simple")
    classification = _classification(simple=True)
    environment = _environment(bundle)
    config = load_phase4(ROOT / "config/phase4.yaml", bundle)
    semantic = ValidationService(config, MockEvaluator([_score(1.0)]), bundle)
    with TemporaryDirectory(prefix="phase4-regression-") as temporary:
        repository = SQLiteTaskRepository(
            f"sqlite:///{Path(temporary) / 'state.sqlite3'}",
            journal_path=Path(temporary) / "pending.jsonl",
        )
        create_schema(repository.engine)
        task = execute(
            request,
            ExecutionDependencies(
                bundle=bundle,
                environment=environment,
                provider=MockProvider([_generation_success]),
                repository=repository,
                budget=MemoryBudgetAuthority(default_ceiling="10"),
                clock=MockClock(NOW),
                limits=ExecutionLimits(
                    max_total_generation_attempts=3,
                    max_quality_escalations=2,
                    max_infrastructure_retries=1,
                    max_tool_recoveries=1,
                    max_elapsed_ms=30_000,
                    initial_backoff_ms=100,
                    max_backoff_ms=1_000,
                    task_cost_ceiling_usd="10",
                ),
                controls=ExecutionControls(authorized=True),
                validator=V0Validator(),
                semantic=semantic,
            ),
            supplied_classification=classification,
        )
    return {
        "status": task.status.value,
        "validation_level": task.initial_decision.validation_level.value,
        "selected_model": task.initial_decision.selected_model_alias,
    }


def _health_service(*, threshold=3):
    bundle = load_bundle(ROOT / "config")
    config = load_phase4(ROOT / "config/phase4.yaml", bundle).health.model_copy(
        update={"failure_threshold": threshold, "freshness_ms": 1_000, "cooldown_ms": 200}
    )
    clock = MockClock(NOW)
    health = HealthService(clock, config)
    SyntheticHealthSource(health).seed(models=bundle.catalog["models"])
    return bundle, clock, health


def _health_row(health, component, *, model=None):
    return next(
        item
        for item in health.snapshot().observations
        if item.component == component and item.model == model
    )


def _health_case(case_id):
    threshold = 1 if case_id in {"half_open_recovery", "unhealthy_excluded"} else 3
    bundle, clock, health = _health_service(threshold=threshold)
    if case_id == "stale_health":
        clock.advance(1_000)
        status = health.readiness()
        return {"ready": status.ready, "check_status": _health_row(health, "configuration").check_status}
    if case_id == "circuit_opens_infra":
        for _ in range(3):
            health.observe("provider", model="luna", failure=FailureType.TIMEOUT)
        row = _health_row(health, "provider", model="luna")
        return {"available": health.available("provider", model="luna"), "circuit_state": row.circuit_state}
    if case_id == "quality_no_circuit":
        health.observe("provider", model="luna", success=True)
        health.observe("provider", model="luna", failure=FailureType.QUALITY_FAILURE)
        row = _health_row(health, "provider", model="luna")
        return {"available": health.available("provider", model="luna"), "circuit_state": row.circuit_state}
    if case_id == "half_open_recovery":
        health.observe("provider", model="luna", failure=FailureType.TIMEOUT)
        clock.advance(200)
        health.admit_probe("provider", model="luna")
        health.observe("provider", model="luna", success=True)
        row = _health_row(health, "provider", model="luna")
        return {"available": health.available("provider", model="luna"), "circuit_state": row.circuit_state}
    if case_id == "degraded_usable":
        health.observe("telemetry", state="DEGRADED")
        status = health.readiness()
        return {"ready": status.ready, "state": status.state}
    if case_id == "unhealthy_excluded":
        health.observe("provider", model="luna", failure=FailureType.TIMEOUT)
        projected = health.apply(_environment(bundle))
        return {"model_state": projected.models["luna"].state}
    if case_id == "all_permitted_unavailable":
        for alias in bundle.catalog["models"]:
            for _ in range(3):
                health.observe("provider", model=alias, failure=FailureType.TIMEOUT)
        request = _request()
        result = route(request, _classification(), health.apply(_environment(bundle)), bundle)
        return {
            "routing_result": result.routing_result,
            "failure_type": result.failure_type.value,
        }
    raise ValueError(f"unknown health regression {case_id}")


def _enabled_shadow_bundle(*, rate=1.0, task_cap="1", period_cap="10"):
    documents = {}
    for name, filename in {
        "policy": "routing-policy.yaml",
        "catalog": "models.yaml",
        "budgets": "budgets.yaml",
        "validation": "validation.yaml",
    }.items():
        documents[name] = yaml.safe_load((ROOT / "config" / filename).read_text())
    documents["validation"]["version"] = "validation-shadow-regression-v1"
    documents["policy"]["version"] = "routing-shadow-regression-v1"
    documents["policy"]["validation_version"] = documents["validation"]["version"]
    shadow = documents["validation"]["shadow_evaluation"]
    shadow["enabled"] = True
    shadow["sampling"]["rate"] = rate
    shadow["budget"]["task_cost_ceiling_usd"] = task_cap
    shadow["budget"]["period_spend_ceiling_usd"] = period_cap
    return bundle_from_documents(**documents)


def _shadow_case(case_id):
    rate = 0.0 if case_id == "shadow_not_selected" else 1.0
    task_cap = "0" if case_id == "shadow_budget_exhausted" else "1"
    bundle = _enabled_shadow_bundle(rate=rate, task_cap=task_cap)
    request = _request(side_effect=case_id == "side_effects_forbidden")
    environment = _environment(bundle)
    decision = route(request.model_copy(update={"side_effecting_tool": False}), _classification(), environment, bundle)
    production = Attempt(
        attempt_id="production",
        task_id=request.task_id,
        trace_id=request.trace_id,
        sequence=1,
        status=AttemptStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW,
        decision=decision,
        pricing_version=decision.pricing_version,
        provider_outcome=ProviderResult(
            task_id=request.task_id,
            trace_id=request.trace_id,
            invocation_id="production",
            policy_version=decision.policy_version,
            catalog_version=decision.catalog_version,
            model_alias=decision.selected_model_alias,
            provider_model_id=decision.provider_model_id,
            reasoning_effort=decision.reasoning_effort,
            purpose="generation",
            latency_ms=0,
            response_status="completed",
            text="private production output",
            usage=_usage(10, 10),
        ),
    )

    def shadow_success(provider_request):
        return ProviderResult(
            **request_evidence(provider_request),
            response_status="completed",
            text="private shadow output sentinel",
            usage=_usage(10, 10),
        )

    def shadow_failure(provider_request):
        return ProviderFailure(
            **request_evidence(provider_request),
            failure_type=FailureType.PROVIDER_FAILURE,
            source="provider",
            stage="invocation",
            cause_code="synthetic_shadow_failure",
            usage=_usage(0, 0),
        )

    scripted = shadow_failure if case_id == "shadow_failure_production_success" else shadow_success
    provider = MockProvider([scripted])
    service = ShadowService(
        bundle,
        provider,
        MemoryBudgetAuthority(default_ceiling="10"),
        MockClock(NOW),
        privacy_allowed=True,
    )
    if case_id in {'shadow_output_hidden', 'shadow_failure_production_success'}:
        with TemporaryDirectory(prefix='phase4-shadow-regression-') as temporary:
            repository = SQLiteTaskRepository(f"sqlite:///{Path(temporary) / 'state.sqlite3'}",
                journal_path=Path(temporary) / 'pending.jsonl')
            create_schema(repository.engine)
            task = execute(request, ExecutionDependencies(bundle=bundle, environment=environment,
                provider=MockProvider([_generation_success]), repository=repository,
                budget=MemoryBudgetAuthority(default_ceiling='10'), clock=service.clock,
                limits=ExecutionLimits(max_total_generation_attempts=3,max_quality_escalations=2,
                    max_infrastructure_retries=1,max_tool_recoveries=1,max_elapsed_ms=30000,
                    initial_backoff_ms=100,max_backoff_ms=1000,task_cost_ceiling_usd='10'),
                controls=ExecutionControls(authorized=True), shadow=service),
                supplied_classification=_classification())
        run = task.shadow_runs[0]
        return {'selected':run.selected,'status':run.status,'reason':run.reason,
            'dispatches':provider.call_count, 'production_status':task.status.value,
            'output_hidden':task.output == 'private production output' and
                'private shadow output sentinel' not in task.model_dump_json()}
    run = service.run(request, production, environment=environment, controls=ExecutionControls())
    serialized = run.model_dump_json()
    return {
        "selected": run.selected,
        "status": run.status,
        "reason": run.reason,
        "dispatches": provider.call_count,
        "output_hidden": "private shadow output sentinel" not in serialized,
        "production_status": production.status.value,
    }


def execute_regression(record: dict) -> dict:
    case_id, kind = record["id"], record["kind"]
    if kind == "evaluator":
        return _semantic_case(case_id)
    if kind == "domain":
        return _domain_case(case_id)
    if kind == "execution":
        return _execution_case()
    if kind == "health":
        return _health_case(case_id)
    if kind == "shadow":
        return _shadow_case(case_id)
    raise ValueError(f"unknown Phase 4 regression kind {kind}")


def run_regressions():
    results, failures = [], {}
    for record in load_regressions():
        try:
            facts = execute_regression(record)
            errors = [
                f"{key}: expected {expected!r}, observed {facts.get(key)!r}"
                for key, expected in record["checks"].items()
                if facts.get(key) != expected
            ]
        except Exception as error:
            facts = {}
            errors = [f"runtime error: {type(error).__name__}: {error}"]
        results.append({"case_id": record["id"], "facts": facts})
        if errors:
            failures[record["id"]] = errors
    return {
        "total": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }, results


__all__ = ["execute_regression", "load_regressions", "run_regressions"]
