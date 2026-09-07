"""Only applicable deterministic V0 validation; no semantic evaluators."""
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping
from decimal import Decimal
from uuid import uuid4
from pydantic import ValidationError
from model_router.core.contracts import Request, FailureType
from model_router.execution.arithmetic import money_sum
from model_router.core.provider_contracts import ProviderResult
from model_router.core.execution_contracts import ExecutionControls, ValidationOutcome, Failure

@dataclass(frozen=True)
class DeterministicCheck:
    run: Callable[[Request, ProviderResult], ValidationOutcome]
    cost_upper_bound_usd: Decimal | None = Decimal('0')

@dataclass(frozen=True)
class V0Validator:
    checks: Mapping[str, DeterministicCheck] = field(default_factory=dict)

    def readiness(self, decision, controls: ExecutionControls) -> tuple[str, ...]:
        if decision.validation_level != 'V0':
            return ('stronger_validation_unavailable',)
        return tuple('required_check_unavailable' for name in controls.required_checks if name not in self.checks)

    def upper_bound(self, controls: ExecutionControls) -> Decimal | None:
        bounds = [self.checks[name].cost_upper_bound_usd for name in controls.required_checks if name in self.checks]
        if len(bounds) != len(controls.required_checks) or any(x is None for x in bounds):
            return None
        return money_sum(bounds)

    def validate(self, request: Request, result: ProviderResult, controls: ExecutionControls, *, before_check=None) -> tuple[ValidationOutcome, ...]:
        def outcome(check, status, failure=None):
            return ValidationOutcome(evaluation_id=str(uuid4()), check=check, status=status, failure=failure)
        def failed(check, kind, cause, source='validation'):
            return outcome(check, 'failed', Failure(failure_type=kind, source=source, stage='validation', cause_code=cause))
        if result.response_status != 'completed' or result.refused or result.incomplete_reason:
            return (failed('provider_success', FailureType.VALIDATION_FAILURE, 'provider_not_completed'),)
        results = [outcome('provider_success', 'passed')]
        if controls.output_type is not None:
            try:
                if result.structured_output is None:
                    raise ValueError('missing structured output')
                controls.output_type.model_validate(result.structured_output.model_dump())
            except (ValidationError, ValueError, TypeError):
                return (*results, failed('json_schema', FailureType.MALFORMED_OUTPUT, 'structured_schema_invalid'))
            results.append(outcome('json_schema', 'passed'))
        if controls.expected_fields:
            values = result.structured_output.model_dump() if result.structured_output else {}
            if any(name not in values for name in controls.expected_fields):
                return (*results, failed('expected_fields', FailureType.MALFORMED_OUTPUT, 'expected_fields_missing'))
            results.append(outcome('expected_fields', 'passed'))
        for name in controls.required_checks:
            if before_check is not None:
                stopped = before_check()
                if stopped is not None:
                    results.append(outcome(name, 'error', stopped))
                    break
            checked = None
            try:
                checked = self.checks[name].run(request, result)
                if not isinstance(checked, ValidationOutcome):
                    raise TypeError('invalid check result')
                if checked.check != name:
                    raise ValueError('mismatched check')
                # Provider/tool/validator infrastructure can never diagnose quality.
                if checked.diagnosed_failure == FailureType.QUALITY_FAILURE and (
                    checked.status != 'failed' or checked.failure is None or
                    checked.failure.source != 'validation' or checked.failure.failure_type not in {
                        FailureType.VALIDATION_FAILURE, FailureType.MALFORMED_OUTPUT, FailureType.QUALITY_FAILURE}
                    or not checked.evidence_code):
                    raise ValueError('unsupported quality diagnosis')
                if checked.status in {'failed', 'error'} and checked.failure is None:
                    raise ValueError('missing failure evidence')
                if checked.status == 'skipped' or not checked.applicable:
                    raise ValueError('required check cannot be skipped')
                if checked.failure and checked.failure.failure_type == FailureType.QUALITY_FAILURE and (
                    checked.status != 'failed' or checked.failure.source != 'validation' or not checked.evidence_code):
                    # Retain the observation but reject it as quality evidence.
                    checked = checked.model_copy(update={'diagnosed_failure': None, 'evidence_code': None})
                results.append(checked)
                bound = self.checks[name].cost_upper_bound_usd
                if checked.cost_usd is not None and bound is not None and checked.cost_usd > bound:
                    results.append(outcome('validation_budget', 'error', Failure(
                        failure_type=FailureType.BUDGET_FAILURE, source='admission', stage='validation',
                        cause_code='validation_cost_exceeded_reservation')))
                    break
                if checked.status == 'error':
                    break
            except Exception:
                error = outcome(name, 'error', Failure(failure_type=FailureType.VALIDATION_FAILURE,
                    source='validation', stage='validation', cause_code='deterministic_check_error'))
                results.append(error.model_copy(update={'cost_usd': checked.cost_usd if isinstance(checked, ValidationOutcome) else None}))
                break
        return tuple(results)
