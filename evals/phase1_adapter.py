"""Translate fixture facts and real route evidence; never read expected envelopes."""

from copy import deepcopy
import json
from pathlib import Path

from model_router.core.contracts import Classification, EnvironmentSnapshot, Request, RouteDecision
from model_router.router import route

from evals.schema import Observation


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def merge_fixture(base, patch):
    """Fixture composition only; production limits merge inside the policy core."""
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_fixture(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def skip_reason(case):
    if case.classification is None:
        return "Phase 2: no supplied classification; requires a classifier adapter."
    if case.scenario is not None:
        return "Phase 3: requires execution of a scripted recovery trace."
    return None


def adapt_inputs(case):
    if skip_reason(case):
        raise ValueError("case is outside Phase 1 routing scope")
    baseline = json.loads((FIXTURES / "environment.json").read_text())
    if case.environment.snapshot != baseline["id"]:
        raise ValueError("unknown fixture snapshot")
    fixture = merge_fixture(baseline, case.environment.overrides)
    source = case.request.model_dump()
    request = Request(**source, task_id=case.id, trace_id=f"eval:{case.id}")
    classification = Classification(**case.classification.model_dump())
    health, budget = fixture["health"], fixture["budget"]
    validation, recovery = fixture["validation"], fixture["recovery"]
    pricing = fixture.get("pricing", {})
    latency = fixture.get("latency", {})
    # These are readiness facts only; no recovery script is executed.
    bounded = all(type(value) is int and value >= 0 for value in recovery.values())
    bounded = bounded and recovery["max_total_generation_attempts"] > 0 and recovery["max_elapsed_ms"] > 0
    environment = EnvironmentSnapshot(
        snapshot_id=fixture["id"], synthetic=fixture["synthetic"], clock=fixture["clock"],
        pricing_version=fixture["pricing_snapshot"], health_snapshot_id=health["snapshot_id"],
        health_observed_at=health["observed_at"], health_valid_until=health["valid_until"], models=health["models"],
        budget={key: budget[key] for key in ("task_cost_ceiling_usd", "task_deadline_ms", "live_execution_enabled")},
        remaining_usd=budget["remaining_usd"],
        application_overlay=case.environment.application_overlay.model_dump() if case.environment.application_overlay else None,
        application_overlay_version=case.environment.application_overlay_version,
        validation={key: value for key, value in validation.items() if key in ("V0", "V1", "V2", "V3")},
        requested_validation=validation.get("requested_profile"),
        required_evaluator_cost_usd=validation.get("required_evaluator_cost_usd"),
        required_tool_charge="required_tool_charge_usd" in pricing,
        required_tool_charge_usd=pricing.get("required_tool_charge_usd"),
        minimum_next_action_ms=latency.get("minimum_next_action_ms"), latency_source=latency.get("source"),
        recovery_bounded=bounded, durable_retention=fixture["telemetry"]["durable_retention"],
    )
    return request, classification, environment


def decision_metadata(result):
    """An actual allowlisted preview projection, not a telemetry transport.

    No arbitrary request fields, content, provider bodies or credential fields
    are accepted. This says nothing about a future transport's secret handling.
    """
    return {key: value for key, value in result.model_dump(mode="json").items() if key in {
        "task_id", "trace_id", "decision_id", "policy_version", "catalog_version", "pricing_version",
        "budget_version", "validation_version", "application_overlay_version", "effective_configuration_hash",
        "complexity_score", "selected_model_alias", "model_tier", "reasoning_effort", "validation_level",
        "rationale_codes", "executable", "routing_result", "failure_type",
        "environment_snapshot_id", "synthetic",
    }}


def project(case_id, result):
    """Project only runtime decision/rejection evidence into the independent schema."""
    details = result.model_dump(mode="json")["rationale_details"]
    cl = result.classification
    metadata = decision_metadata(result)
    sensitive_fields = {"input", "raw_prompt", "raw_response", "api_key", "credentials", "secret", "authorization"}
    facts = {
        "complexity_score": result.complexity_score,
        "required_capabilities": details["required_capabilities"],
        "floor_waiver_rules": details["floor_waiver_rules"],
        "floor_waiver_constraints": details["floor_waiver_constraints"],
        "blockers": list(result.readiness_blockers),
        "effective_limits": result.effective_limits.model_dump(mode="json"),
        "telemetry_fields": list(metadata),
        "secret_redacted": not bool(sensitive_fields & metadata.keys()),
    }
    common = dict(schema_version=1, case_id=case_id, routing_result=result.routing_result,
                  policy_version=result.policy_version, rationale_codes=list(result.rationale_codes),
                  execution_readiness="ready" if result.executable else "blocked",
                  classification=dict(task_family=cl.task_family, components=cl.components.model_dump(),
                                      confidence=cl.confidence, flags=dict(cl.flags), provenance=cl.provenance))
    if isinstance(result, RouteDecision):
        facts.update(unknown_charges=list(result.estimated_cost.unknown_charges),
                     cache_read_tokens=result.estimated_cost.cache_read_tokens,
                     known_cost_subtotal=str(result.estimated_cost.known_subtotal),
                     approval_required=result.validation_requirements.approval_required,
                     execution_restrictions=list(result.validation_requirements.execution_restrictions))
        return Observation(**common, selected_model_alias=result.selected_model_alias,
                           model_tier=result.model_tier, reasoning_effort=result.reasoning_effort.value,
                           validation_level=result.validation_level.value,
                           estimated_cost=dict(status=result.estimated_cost.status,
                                               amount=format(result.estimated_cost.amount, "f") if result.estimated_cost.amount is not None else None,
                                               currency=result.estimated_cost.currency), facts=facts)
    facts.update(violated_constraints=list(result.violated_constraints), retryable=result.retryable)
    return Observation(**common, failure_type=result.failure_type.value, facts=facts)


def observe(case, bundle):
    request, classification, environment = adapt_inputs(case)
    return project(case.id, route(request, classification, environment, bundle))
