"""Phase 4 orchestration hooks. Provider calls remain single-invocation ports."""
import json
from decimal import Decimal
from uuid import uuid4

from model_router.core.contracts import Context, ValidationRequirements, FailureType
from model_router.core.execution_contracts import Attempt, AttemptStatus, Failure, RecoveryAction, RepositoryUnavailable
from model_router.core.provider_contracts import ProviderRequest, ProviderFailure
from model_router.execution.accounting import provider_cost
from model_router.execution.arithmetic import money_sum
from model_router.execution.lifecycle import finish_attempt
from model_router.policy.costs import estimate_cost


class VerificationMixin:
    def evaluation_quote(self, binding, environment):
        model = self.d.bundle.catalog['models'][binding.model_alias]
        bounded = self.request.model_copy(update={'side_effecting_tool': False, 'context': Context(
            input_tokens=binding.max_input_tokens, expected_output_tokens=binding.max_output_tokens)})
        quote = estimate_cost(bounded, model, environment.model_copy(update={'required_tool_charge': False}),
            ValidationRequirements(level='V0', profiles=('V0',), checks=(), evidence='evaluator_bound'),
            currency=self.d.bundle.catalog['currency'])
        return quote

    def semantic_bound(self, decision):
        if self.d.semantic is None:
            return Decimal('0')
        costs = [self.evaluation_quote(b, self.environment()).amount for b in self.d.semantic.plans(decision)]
        if 'V3' in decision.validation_requirements.profiles:
            costs.append(self.d.semantic.domain_bound)
        return None if any(c is None for c in costs) else money_sum(costs)

    def phase4_readiness(self, decision):
        if self.d.semantic is None:
            return ()
        from model_router.execution.provider import MockProvider
        blockers = list(self.d.semantic.readiness(decision))
        if not isinstance(self.d.semantic.provider, MockProvider):
            blockers.append('mock_evaluator_required')
        environment = self.environment()
        for binding in self.d.semantic.plans(decision):
            model = environment.models.get(binding.model_alias)
            if model is None or not model.usable or model.state == 'UNHEALTHY' or model.account_access != 'verified':
                blockers.append('required_evaluator_unavailable')
            if self.d.health is not None and not self.d.health.available('evaluator', model=binding.model_alias):
                blockers.append('required_evaluator_unavailable')
        return tuple(blockers)

    def verify_semantic(self, decision, generation):
        if self.d.semantic is None:
            return (), None
        outcomes = []
        for binding in self.d.semantic.plans(decision):
            for retry in range(binding.max_retries + 1):
                failure = self.validation_checkpoint()
                if failure:
                    return tuple(outcomes), failure
                if self.phase4_readiness(decision):
                    return tuple(outcomes), self.failure(FailureType.PROVIDER_FAILURE,
                        'required_evaluator_unavailable', 'evaluator')
                env = self.environment()
                quote = self.evaluation_quote(binding, env)
                estimate = quote.amount
                if estimate is None or estimate > self.remaining():
                    return tuple(outcomes), self.failure(FailureType.BUDGET_FAILURE, 'evaluator_budget_unavailable')
                candidate = generation.structured_output.model_dump(mode='json') if generation.structured_output else generation.text
                content = json.dumps({'task': self.request.input, 'candidate': candidate}, ensure_ascii=True)
                instructions = binding.rubric + f' Score scale: {binding.score_min} to {binding.score_max}.'
                # UTF-8 bytes conservatively bound text tokens without an external tokenizer.
                if len((content + instructions).encode('utf-8')) > binding.max_input_tokens:
                    return tuple(outcomes), self.failure(FailureType.CAPABILITY_FAILURE, 'evaluator_input_bound_exceeded', 'evaluator')
                invocation_id = str(uuid4())
                if not self.reserve(invocation_id, estimate):
                    return tuple(outcomes), self.failure(FailureType.BUDGET_FAILURE, 'evaluator_reservation_refused')
                started = Attempt(attempt_id=invocation_id, task_id=self.task.task_id, trace_id=self.task.trace_id,
                    sequence=len(self.task.evaluator_attempts) + 1, purpose='evaluation',
                    parent_attempt_id=generation.invocation_id, decision=decision, status=AttemptStatus.STARTED,
                    started_at=self.d.clock.now(), estimated_cost_usd=estimate, pricing_version=quote.pricing_version,
                    evaluator_ref=binding.ref, rubric_version=binding.rubric_version,
                    phase4_version=self.d.semantic.config.version)
                self.task = self.task.model_copy(update={'evaluator_attempts': (*self.task.evaluator_attempts, started)})
                self.save(self.event('ATTEMPT_STARTED', attempt_id=invocation_id, decision_id=decision.decision_id))
                failure = self.validation_checkpoint()
                if failure is None and self.phase4_readiness(decision):
                    failure = self.failure(FailureType.PROVIDER_FAILURE, 'required_evaluator_unavailable', 'evaluator')
                if failure:
                    self.charge(invocation_id, Decimal('0'), estimate)
                    completed = finish_attempt(started, started.model_copy(update={'status': AttemptStatus.CANCELLED,
                        'completed_at': self.d.clock.now(), 'actual_cost_usd': Decimal('0'), 'failure': failure}))
                    self.task = self.task.model_copy(update={'evaluator_attempts': (*self.task.evaluator_attempts[:-1], completed)})
                    self.save(self.event('ATTEMPT_COMPLETED', attempt_id=invocation_id, failure=failure.failure_type))
                    return tuple(outcomes), failure
                model = self.d.bundle.catalog['models'][binding.model_alias]
                provider_request = ProviderRequest(task_id=self.task.task_id, trace_id=self.task.trace_id,
                    invocation_id=invocation_id, policy_version=decision.policy_version, catalog_version=decision.catalog_version,
                    model_alias=binding.model_alias, provider_model_id=model['provider_model_id'],
                    reasoning_effort=binding.reasoning_effort, input=content, instructions=instructions,
                    max_output_tokens=binding.max_output_tokens,
                    timeout_ms=min(binding.timeout_ms, self.limits.max_elapsed_ms - self.elapsed()), purpose='evaluation')
                result, validation = self.d.semantic.evaluate(binding, provider_request)
                validation = validation.model_copy(update={'evaluator_attempt_id': invocation_id,
                    'target_attempt_id': generation.invocation_id, 'cost_usd': Decimal('0')})
                actual = provider_cost(self.request, result, self.d.bundle, env)
                interim = started.model_copy(update={'provider_outcome': result, 'actual_cost_usd': actual})
                self.task = self.task.model_copy(update={'evaluator_attempts': (*self.task.evaluator_attempts[:-1], interim)})
                self.save()  # Preserve usage before settlement can fail.
                self.charge(invocation_id, actual, estimate)
                self.add_cost('production_validation_cost_usd', actual)
                completed = finish_attempt(started, interim.model_copy(update={
                    'status': AttemptStatus.FAILED if validation.failure else AttemptStatus.SUCCEEDED,
                    'completed_at': self.d.clock.now(), 'validations': (validation,), 'failure': validation.failure}))
                self.task = self.task.model_copy(update={'evaluator_attempts': (*self.task.evaluator_attempts[:-1], completed)})
                self.save(self.event('ATTEMPT_COMPLETED', attempt_id=invocation_id,
                              failure=validation.failure.failure_type if validation.failure else None),
                          self.event('VALIDATION_COMPLETED', attempt_id=invocation_id, evaluation_id=validation.evaluation_id,
                              failure=validation.failure.failure_type if validation.failure else None))
                if self.d.health is not None:
                    infra = result.failure_type if isinstance(result, ProviderFailure) else None
                    self.d.health.observe('evaluator', model=binding.model_alias, failure=infra,
                        success=not isinstance(result, ProviderFailure))
                failure = self.validation_checkpoint()
                if failure:
                    return (*outcomes, validation), failure
                if validation.status == 'passed':
                    outcomes.append(validation)
                    break
                # Historical failed evaluator calls live on their own attempts.
                # Only a final applicable result governs generation acceptance.
                retryable = validation.failure and validation.failure.source == 'evaluator' and (
                    validation.failure.failure_type in {FailureType.TIMEOUT, FailureType.RATE_LIMIT, FailureType.PROVIDER_FAILURE}) and validation.failure.retryable
                if not retryable or retry >= binding.max_retries:
                    return (*outcomes, validation), validation.failure
                delay = max(binding.backoff_ms, validation.failure.retry_after_ms or 0)
                if self.elapsed() + delay >= self.limits.max_elapsed_ms:
                    return (*outcomes, validation), self.failure(FailureType.BUDGET_FAILURE, 'evaluator_deadline_exceeded')
                action = RecoveryAction(action='retry_evaluator', failure=validation.failure.failure_type,
                    original_failure=validation.failure.failure_type, validated=False, backoff_ms=delay,
                    reason='evaluator_infrastructure_retry')
                self.task = self.task.model_copy(update={'recovery_actions': (*self.task.recovery_actions, action)})
                self.save(self.event('RECOVERY_SELECTED', attempt_id=invocation_id,
                    failure=validation.failure.failure_type, action='retry_evaluator'))
                self.d.clock.sleep(delay)
        if 'V3' in decision.validation_requirements.profiles:
            failure = self.validation_checkpoint()
            if failure:
                return tuple(outcomes), failure
            bound = self.d.semantic.domain_bound
            action_id = str(uuid4())
            if bound is None or bound > self.remaining() or not self.reserve(action_id, bound):
                return tuple(outcomes), self.failure(FailureType.BUDGET_FAILURE, 'domain_budget_unavailable')
            self.save()
            failure = self.validation_checkpoint()
            if failure:
                self.charge(action_id, Decimal('0'), bound)
                return tuple(outcomes), failure
            validation = self.d.semantic.validate_domain(self.request, generation).model_copy(update={
                'target_attempt_id': generation.invocation_id})
            self.task = self.task.model_copy(update={'domain_validations': (*self.task.domain_validations, validation)})
            self.charge(action_id, validation.cost_usd, bound)
            self.add_cost('production_validation_cost_usd', validation.cost_usd)
            self.save(self.event('VALIDATION_COMPLETED', attempt_id=generation.invocation_id,
                evaluation_id=validation.evaluation_id, failure=validation.failure.failure_type if validation.failure else None))
            outcomes.append(validation)
            if validation.failure:
                return tuple(outcomes), validation.failure
        return tuple(outcomes), None

    def add_cost(self, field, actual):
        previous = getattr(self.task, field)
        self.task = self.task.model_copy(update={field: None if previous is None or actual is None else money_sum((previous, actual))})

    def run_shadow(self):
        if self.d.shadow is None:
            return
        # The isolated service must never reserve from the production authority.
        if self.d.shadow.budget is self.d.budget:
            return
        def persist(shadow):
            if self.shadow_retention_failed:
                raise RepositoryUnavailable('execution evidence retention unavailable')
            existing = self.task.shadow_runs
            replacing = bool(existing and existing[-1].shadow_id == shadow.shadow_id)
            if replacing and existing[-1].status != 'started':
                return  # Final shadow evidence cannot be rewritten by callback diagnostics.
            self.task = self.task.model_copy(update={'shadow_runs': (*existing[:-1], shadow) if replacing else (*existing, shadow)})
            attempts = shadow.attempts
            events = () if not attempts else (self.event('ATTEMPT_STARTED' if attempts[-1].status == AttemptStatus.STARTED else 'ATTEMPT_COMPLETED',
                attempt_id=attempts[-1].attempt_id),)
            if self.shadow_retention_deferred:
                self.save(*events)
                raise _ShadowEvidenceDeferred()
            try:
                self.save(*events)
            except RepositoryUnavailable as error:
                # save() already retained this exact revision before raising.
                # Continue only through the durable journal; no more shadow calls.
                if str(error) != 'execution evidence retained for reconciliation':
                    self.shadow_retention_failed = True
                    raise
                self.shadow_retention_deferred = True
                raise _ShadowEvidenceDeferred() from None
        try:
            result = self.d.shadow.run(self.request, self.task.attempts[-1], environment=self.environment(),
                controls=self.d.controls, before_attempt=persist, after_attempt=persist)
            if not self.task.shadow_runs or self.task.shadow_runs[-1] != result:
                persist(result)
        except RepositoryUnavailable:
            raise
        except Exception:
            # Started intent remains durable if the optional experiment aborts.
            # No shadow failure may replace production result or consume retries.
            pass
        if self.shadow_retention_failed:
            raise RepositoryUnavailable('execution evidence retention unavailable')


class _ShadowEvidenceDeferred(RuntimeError):
    pass
