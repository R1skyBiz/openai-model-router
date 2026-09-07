"""Bounded, private and production-isolated synthetic shadow comparisons."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from hashlib import sha256
import json
from threading import RLock
from uuid import uuid4

from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import (Candidate, Context, EnvironmentSnapshot, FailureType,
    Request, RouteDecision, RouteRejection, ValidationRequirements)
from model_router.core.execution_contracts import (Attempt, AttemptStatus, BudgetAuthority, Clock,
    ExecutionControls, Failure, ShadowRun)
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult
from model_router.execution.accounting import provider_cost
from model_router.execution.provider import MockProvider, request_evidence
from model_router.policy.costs import estimate_cost
from model_router.router import route
from model_router.validation.v0 import V0Validator

ShadowCallback = Callable[[ShadowRun], None]
ZERO = Decimal('0')


class ShadowService:
    """Execute one configured generation and its mandatory bounded validation."""
    def __init__(self, bundle: PolicyBundle, provider: MockProvider, budget: BudgetAuthority,
                 clock: Clock, validator: object | None = None, *, semantic: object | None = None,
                 privacy_allowed: bool = False) -> None:
        self.bundle, self.provider, self.budget, self.clock = bundle, provider, budget, clock
        if validator is not None and callable(getattr(validator, 'plans', None)):
            self.v0, self.semantic = V0Validator(), validator if semantic is None else semantic
        else:
            self.v0, self.semantic = validator or V0Validator(), semantic
        self.validator = validator
        self.privacy_allowed = privacy_allowed is True
        self._lock = RLock()
        self._task_debits: dict[str, Decimal] = {}
        self._period_debit = ZERO

    def run(self, request: Request, production_attempt: Attempt, *, environment: EnvironmentSnapshot,
            controls: ExecutionControls, before_attempt: ShadowCallback | None = None,
            after_attempt: ShadowCallback | None = None) -> ShadowRun:
        settings = self.bundle.validation['shadow_evaluation']
        sampling = settings['sampling']
        base = dict(shadow_id=str(uuid4()), production_attempt_id=production_attempt.attempt_id,
            config_version=self.bundle.validation['version'], sampling_seed=sampling['seed'],
            sampling_rate=sampling['rate'], selected=False, status='skipped', reason='shadow_disabled')
        if settings['enabled'] is not True:
            return ShadowRun(**base)
        if not self._selected(request.task_id, sampling['seed'], sampling['rate']):
            return ShadowRun(**(base | {'reason': 'not_sampled'}))
        base['selected'] = True
        blocker = self._preflight(request, production_attempt, environment, controls)
        if blocker:
            return ShadowRun(**(base | {'reason': blocker}))
        production = production_attempt.decision
        assert isinstance(production, RouteDecision)
        comparison = next((item for item in settings['comparisons']
            if item['production']['model'] == production.selected_model_alias
            and item['production']['reasoning_effort'] == production.reasoning_effort), None)
        if comparison is None:
            return ShadowRun(**(base | {'reason': 'comparison_not_configured'}))
        task_cap = self._money(settings['budget']['task_cost_ceiling_usd'])
        period_cap = self._money(settings['budget']['period_spend_ceiling_usd'])
        if task_cap is None or period_cap is None:
            return ShadowRun(**(base | {'reason': 'shadow_budget_unconfigured'}))

        shadow_env = environment.model_copy(update={
            'remaining_usd': self._routing_balance(request, environment, task_cap)})
        wanted = comparison['shadow']
        decision = route(request, production.classification, shadow_env, self.bundle,
            recovery_candidates=(Candidate(model=wanted['model'], effort=wanted['reasoning_effort'],
                                           source='fallback'),))
        if isinstance(decision, RouteRejection):
            return ShadowRun(**(base | {'reason': 'shadow_route_rejected'}))
        if (decision.selected_model_alias, decision.reasoning_effort) != (
                wanted['model'], wanted['reasoning_effort']):
            return ShadowRun(**(base | {'reason': 'shadow_route_mismatch'}))
        readiness, plans = self._readiness(decision, environment, controls)
        if readiness:
            return ShadowRun(**(base | {'reason': readiness}))
        run_started = self.clock.now()
        runtime = self._runtime_readiness(environment, decision, run_started)
        if runtime:
            return ShadowRun(**(base | {'reason': runtime}))

        generation_bound = self._generation_bound(decision)
        v0_bound = self._v0_bound(controls)
        quotes = tuple(self._evaluation_quote(request, binding, environment) for binding in plans)
        if generation_bound is None:
            return ShadowRun(**(base | {'reason': 'shadow_price_unknown'}))
        if v0_bound is None:
            return ShadowRun(**(base | {'reason': 'shadow_validation_price_unknown'}))
        if any(quote.amount is None for quote in quotes):
            return ShadowRun(**(base | {'reason': 'shadow_evaluator_price_unknown'}))

        generation_id, v0_id = str(uuid4()), str(uuid4())
        evaluator_ids = tuple(str(uuid4()) for _ in plans)
        reservations = [(generation_id, generation_bound), (v0_id, v0_bound),
            *((identifier, quote.amount) for identifier, quote in zip(evaluator_ids, quotes))]
        reserved = []
        for action_id, amount in reservations:
            problem = self._reserve(request.task_id, action_id, amount, task_cap, period_cap)
            if problem:
                self._release(request.task_id, reserved)
                return ShadowRun(**(base | {'reason': problem}))
            reserved.append((action_id, amount))

        generation = Attempt(attempt_id=generation_id, task_id=request.task_id,
            trace_id=request.trace_id, sequence=1, role='shadow', decision=decision,
            status=AttemptStatus.STARTED, started_at=self.clock.now(),
            estimated_cost_usd=generation_bound, pricing_version=decision.pricing_version)
        if not self._callback(before_attempt, self._run(base, 'started', 'shadow_started', (generation,))):
            self._release(request.task_id, reserved)
            cancelled = self._cancel(generation, 'shadow_before_attempt_callback_failed')
            result = self._run(base, 'failed', 'before_attempt_callback_failed', (cancelled,))
            self._callback(after_attempt, result)
            return result
        runtime = self._runtime_readiness(environment, decision, run_started)
        if runtime:
            self._release(request.task_id, reserved)
            result = self._run(base, 'failed', runtime, (self._cancel(generation, runtime),))
            self._callback(after_attempt, result)
            return result

        provider_request = ProviderRequest(task_id=request.task_id, trace_id=request.trace_id,
            invocation_id=generation_id, policy_version=decision.policy_version,
            catalog_version=decision.catalog_version, model_alias=decision.selected_model_alias,
            provider_model_id=decision.provider_model_id, reasoning_effort=decision.reasoning_effort,
            input=request.input, output_type=controls.output_type,
            max_output_tokens=max(1, request.context.expected_output_tokens),
            timeout_ms=self._remaining_ms(decision, run_started))
        outcome = self._execute(self.provider, provider_request)
        generation_actual = provider_cost(request, outcome, self.bundle, environment)
        interim = generation.model_copy(update={'provider_outcome': outcome,
                                                'actual_cost_usd': generation_actual})
        evidence_saved = self._callback(after_attempt, self._run(base, 'started',
            'shadow_provider_observed', (interim,), generation_cost=generation_actual))
        settled = self._settle(request.task_id, generation_id, generation_actual, generation_bound)
        failure = self._provider_failure(outcome) if isinstance(outcome, ProviderFailure) else None
        reason = 'shadow_provider_failed' if failure else 'shadow_succeeded'
        if generation_actual is not None and generation_actual > generation_bound:
            failure, reason = self._failure('shadow_generation_cost_exceeded_reservation', 'admission'), 'shadow_generation_cost_exceeded_reservation'
        if not settled:
            failure, reason = self._failure('shadow_budget_settlement_failed', 'admission'), 'shadow_budget_settlement_failed'
        if not evidence_saved:
            failure, reason = self._failure('shadow_provider_evidence_callback_failed'), 'shadow_provider_evidence_callback_failed'
        post_runtime = self._runtime_readiness(environment, decision, run_started)
        if failure is None and post_runtime == 'shadow_deadline_exhausted':
            failure, reason = self._failure(post_runtime, 'admission'), post_runtime

        validations, validation_cost = (), ZERO
        if failure is None:
            validations, v0_actual, v0_reason = self._run_v0(
                request, outcome, controls, environment, decision, run_started)
            validation_cost = v0_actual
            if v0_actual is not None and v0_actual > v0_bound:
                v0_reason = 'shadow_validation_cost_exceeded_reservation'
            if not self._settle(request.task_id, v0_id, v0_actual, v0_bound):
                v0_reason = 'shadow_budget_settlement_failed'
            if v0_reason:
                runtime_reasons = {'shadow_deadline_exhausted', 'shadow_health_snapshot_stale',
                    'shadow_model_unavailable', 'shadow_deadline_unconfigured'}
                failure = (self._runtime_failure(v0_reason) if v0_reason in runtime_reasons
                           else self._failure(v0_reason, 'validation'))
                reason = v0_reason
        else:
            self._settle(request.task_id, v0_id, ZERO, v0_bound)
        completed = interim.model_copy(update={'status': AttemptStatus.FAILED if failure else AttemptStatus.SUCCEEDED,
            'completed_at': self.clock.now(), 'failure': failure, 'validations': validations})
        attempts = [completed]

        if failure is None:
            for index, (binding, quote, evaluator_id) in enumerate(zip(plans, quotes, evaluator_ids)):
                evaluation, actual, problem = self._run_evaluator(request, outcome, decision,
                    environment, run_started, completed, tuple(attempts), binding, quote,
                    evaluator_id, base, before_attempt, after_attempt)
                attempts.append(evaluation)
                validation_cost = self._add_cost(validation_cost, actual)
                if problem:
                    failure, reason = evaluation.failure or self._failure(problem, 'validation'), problem
                    self._release(request.task_id, [(eid, q.amount) for eid, q in
                        zip(evaluator_ids[index + 1:], quotes[index + 1:])])
                    break
        else:
            self._release(request.task_id, [(eid, q.amount) for eid, q in zip(evaluator_ids, quotes)])
        if failure is not None and len(attempts) == 1:
            attempts[0] = attempts[0].model_copy(update={'status': AttemptStatus.FAILED, 'failure': failure})
        result = self._run(base, 'failed' if failure else 'succeeded', reason, tuple(attempts),
            generation_cost=generation_actual, validation_cost=validation_cost)
        if not self._callback(after_attempt, result):
            return result.model_copy(update={'status': 'failed', 'reason': 'after_attempt_callback_failed'})
        return result

    def _readiness(self, decision, environment, controls):
        if 'V3' in decision.validation_requirements.profiles:
            return 'shadow_domain_validation_unsupported', ()
        try:
            v0_decision = decision.model_copy(update={'validation_level': 'V0'})
            if self.v0.readiness(v0_decision, controls):
                return 'shadow_required_v0_check_unavailable', ()
        except Exception:
            return 'shadow_v0_validator_unavailable', ()
        refs, plans = decision.validation_requirements.evaluator_refs, ()
        if refs:
            if self.semantic is None:
                return 'shadow_semantic_validator_required', ()
            if not isinstance(getattr(self.semantic, 'provider', None), MockProvider):
                return 'shadow_mock_evaluator_required', ()
            try:
                plans = tuple(self.semantic.plans(decision))
                unavailable = tuple(self.semantic.readiness(decision))
            except Exception:
                return 'shadow_semantic_validator_unavailable', ()
            if unavailable or tuple(item.ref for item in plans) != tuple(refs):
                return 'shadow_semantic_validator_unavailable', ()
            excluded = self.bundle.policy['health']['exclude_states']
            for binding in plans:
                health = environment.models.get(binding.model_alias)
                if (health is None or health.state in excluded or not health.usable
                        or health.account_access != 'verified'):
                    return 'shadow_required_evaluator_unavailable', ()
        discharged = {'recovery_unconfigured', 'period_budget_unverified'}
        if plans:
            discharged |= {'evaluator_unconfigured', 'required_evaluator_budget', 'required_evaluator'}
        blockers = [item for item in decision.readiness_blockers if item not in discharged]
        return (f'shadow_route_not_ready_{blockers[0]}', ()) if blockers else (None, plans)

    def _run_v0(self, request, outcome, controls, environment, decision, run_started):
        def before_check():
            reason = self._runtime_readiness(environment, decision, run_started)
            return None if reason is None else self._runtime_failure(reason)

        try:
            validations = self.v0.validate(request, outcome, controls, before_check=before_check)
            if not isinstance(validations, tuple):
                raise TypeError
            costs = [item.cost_usd for item in validations]
            actual = None if any(item is None for item in costs) else sum(costs, ZERO)
            runtime = self._runtime_readiness(environment, decision, run_started)
            if runtime is not None:
                return validations, actual, runtime
            failed = next((item for item in validations if item.status != 'passed'), None)
            if failed is not None:
                cause = failed.failure.cause_code if failed.failure is not None else None
                if cause in {'shadow_deadline_exhausted', 'shadow_health_snapshot_stale',
                             'shadow_model_unavailable', 'shadow_deadline_unconfigured'}:
                    return validations, actual, cause
                return validations, actual, 'shadow_v0_validation_failed'
            return validations, actual, None
        except Exception:
            return (), None, 'shadow_v0_validation_failed'

    def _run_evaluator(self, request, generation_outcome, decision, environment, run_started,
                       generation_attempt, prior_attempts, binding, quote, evaluator_id, base,
                       before_attempt, after_attempt):
        candidate = (generation_outcome.structured_output.model_dump(mode='json')
            if generation_outcome.structured_output is not None else generation_outcome.text)
        content = json.dumps({'task': request.input, 'candidate': candidate}, ensure_ascii=True)
        instructions = binding.rubric + f' Score scale: {binding.score_min} to {binding.score_max}.'
        if len((content + instructions).encode('utf-8')) > binding.max_input_tokens:
            self._settle(request.task_id, evaluator_id, ZERO, quote.amount)
            return self._cancel_evaluator(request, decision, generation_attempt, binding, quote,
                evaluator_id, 'shadow_evaluator_input_bound_exceeded', len(prior_attempts) + 1), ZERO, 'shadow_evaluator_input_bound_exceeded'
        started = Attempt(attempt_id=evaluator_id, task_id=request.task_id, trace_id=request.trace_id,
            sequence=len(prior_attempts) + 1, purpose='evaluation', role='shadow',
            evaluator_ref=binding.ref, rubric_version=binding.rubric_version,
            phase4_version=self.semantic.config.version, parent_attempt_id=generation_attempt.attempt_id,
            decision=decision, status=AttemptStatus.STARTED, started_at=self.clock.now(),
            estimated_cost_usd=quote.amount, pricing_version=quote.pricing_version)
        if not self._callback(before_attempt, self._run(base, 'started', 'shadow_evaluator_started',
                                                        (*prior_attempts, started))):
            self._settle(request.task_id, evaluator_id, ZERO, quote.amount)
            return self._cancel(started, 'shadow_before_attempt_callback_failed'), ZERO, 'before_attempt_callback_failed'
        runtime = self._runtime_readiness(environment, decision, run_started)
        if runtime:
            self._settle(request.task_id, evaluator_id, ZERO, quote.amount)
            return self._cancel(started, runtime), ZERO, runtime
        model = self.bundle.catalog['models'][binding.model_alias]
        provider_request = ProviderRequest(task_id=request.task_id, trace_id=request.trace_id,
            invocation_id=evaluator_id, policy_version=decision.policy_version,
            catalog_version=decision.catalog_version, model_alias=binding.model_alias,
            provider_model_id=model['provider_model_id'], reasoning_effort=binding.reasoning_effort,
            input=content, instructions=instructions, max_output_tokens=binding.max_output_tokens,
            timeout_ms=min(binding.timeout_ms, self._remaining_ms(decision, run_started)), purpose='evaluation')
        try:
            evaluator_outcome, validation = self.semantic.evaluate(binding, provider_request)
        except Exception:
            evaluator_outcome = self._contract_failure(provider_request, 'shadow_evaluator_contract_error')
            validation = None
        actual = provider_cost(request, evaluator_outcome, self.bundle, environment)
        interim = started.model_copy(update={'provider_outcome': evaluator_outcome,
                                             'actual_cost_usd': actual})
        evidence_saved = self._callback(after_attempt, self._run(base, 'started',
            'shadow_evaluator_observed', (*prior_attempts, interim), validation_cost=actual))
        settled = self._settle(request.task_id, evaluator_id, actual, quote.amount)
        if validation is not None:
            # Provider usage is charged by the evaluator Attempt. The outcome's
            # own cost remains zero so aggregation cannot count it twice.
            validation = validation.model_copy(update={'evaluator_attempt_id': evaluator_id,
                'target_attempt_id': generation_attempt.attempt_id, 'cost_usd': ZERO})
        failure = validation.failure if validation is not None else self._failure('shadow_evaluator_contract_error', 'validation')
        reason = 'shadow_semantic_validation_failed' if failure else None
        if actual is not None and actual > quote.amount:
            failure, reason = self._failure('shadow_evaluator_cost_exceeded_reservation', 'admission'), 'shadow_evaluator_cost_exceeded_reservation'
        if not settled:
            failure, reason = self._failure('shadow_budget_settlement_failed', 'admission'), 'shadow_budget_settlement_failed'
        if not evidence_saved:
            failure, reason = self._failure('shadow_provider_evidence_callback_failed'), 'shadow_provider_evidence_callback_failed'
        post_runtime = self._runtime_readiness(environment, decision, run_started)
        if failure is None and post_runtime is not None:
            failure, reason = self._runtime_failure(post_runtime), post_runtime
        completed = interim.model_copy(update={'status': AttemptStatus.FAILED if failure else AttemptStatus.SUCCEEDED,
            'completed_at': self.clock.now(), 'failure': failure,
            'validations': (validation,) if validation is not None else ()})
        self._callback(after_attempt, self._run(base, 'started',
            reason or 'shadow_evaluator_completed', (*prior_attempts, completed), validation_cost=actual))
        return completed, actual, reason

    def _preflight(self, request, production_attempt, environment, controls):
        if self.privacy_allowed is not True: return 'shadow_privacy_not_allowed'
        if not isinstance(self.provider, MockProvider): return 'shadow_mock_provider_required'
        if environment.synthetic is not True: return 'shadow_synthetic_environment_required'
        if request.side_effecting_tool or controls.tool_calls: return 'shadow_tools_not_allowed'
        if production_attempt.status != AttemptStatus.SUCCEEDED: return 'production_attempt_not_succeeded'
        if not isinstance(production_attempt.decision, RouteDecision): return 'production_decision_required'
        if production_attempt.task_id != request.task_id or production_attempt.trace_id != request.trace_id:
            return 'production_attempt_correlation_mismatch'
        return None

    def _runtime_readiness(self, environment, decision, started_at):
        now = self.clock.now()
        deadline = decision.effective_limits.task_deadline_ms
        if deadline is None:
            return 'shadow_deadline_unconfigured'
        if (now - started_at).total_seconds() * 1000 >= deadline:
            return 'shadow_deadline_exhausted'
        if (environment.health_snapshot_id is None or environment.health_observed_at is None
                or environment.health_valid_until is None or environment.health_observed_at > now
                or environment.health_valid_until <= now or environment.clock > now):
            return 'shadow_health_snapshot_stale'
        health = environment.models.get(decision.selected_model_alias)
        excluded = self.bundle.policy['health']['exclude_states']
        if health is None or health.state in excluded or not health.usable or health.account_access != 'verified':
            return 'shadow_model_unavailable'
        return None

    def _remaining_ms(self, decision, started_at):
        elapsed = int((self.clock.now() - started_at).total_seconds() * 1000)
        return max(1, decision.effective_limits.task_deadline_ms - elapsed)

    def _runtime_failure(self, reason):
        source = 'admission' if reason in {'shadow_deadline_exhausted', 'shadow_deadline_unconfigured'} else 'orchestrator'
        return self._failure(reason, source)

    def _v0_bound(self, controls):
        try: return self.v0.upper_bound(controls)
        except Exception: return None

    def _evaluation_quote(self, request, binding, environment):
        bounded = request.model_copy(update={'side_effecting_tool': False,
            'context': Context(input_tokens=binding.max_input_tokens,
                               expected_output_tokens=binding.max_output_tokens)})
        checks = ValidationRequirements(level='V0', profiles=('V0',), checks=(),
                                        evidence='shadow_evaluator_bound')
        return estimate_cost(bounded, self.bundle.catalog['models'][binding.model_alias],
            environment.model_copy(update={'required_tool_charge': False}), checks,
            currency=self.bundle.catalog['currency'])

    @staticmethod
    def _generation_bound(decision):
        unknown = set(decision.estimated_cost.unknown_charges)
        if unknown.intersection({'uncached_input', 'cache_read_input', 'cache_write_input',
                'long_context_cache_read', 'long_context_cache_write', 'output'}): return None
        bound = decision.estimated_cost.generation_subtotal
        miss = decision.rationale_details.get('cache_miss_budget_estimates', {}).get(decision.selected_model_alias)
        if miss is not None:
            if miss.get('generation_subtotal') is None: return None
            bound = max(bound, Decimal(miss['generation_subtotal']))
        return bound

    @staticmethod
    def _selected(task_id, seed, rate):
        if rate <= 0: return False
        if rate >= 1: return True
        digest = sha256(f'{seed}:{task_id}'.encode()).digest()
        return int.from_bytes(digest, 'big') / (1 << (8 * len(digest))) < rate

    @staticmethod
    def _money(value):
        if not isinstance(value, (str, Decimal)): return None
        try: amount = Decimal(value)
        except Exception: return None
        return amount if amount.is_finite() and amount >= ZERO else None

    def _routing_balance(self, request, environment, task_cap):
        values = [task_cap]
        for value in (environment.budget.task_cost_ceiling_usd,
                      request.constraints.task_cost_ceiling_usd,
                      self.bundle.budgets['defaults']['task_cost_ceiling_usd']):
            amount = self._money(value)
            if amount is not None: values.append(amount)
        return max(values)

    def _reserve(self, task_id, action_id, amount, task_cap, period_cap):
        task_scope, period_scope = f'{task_id}:shadow', f"shadow-period:{self.bundle.validation['version']}"
        with self._lock:
            if self._task_debits.get(task_id, ZERO) + amount > task_cap: return 'shadow_task_budget_exhausted'
            if self._period_debit + amount > period_cap: return 'shadow_period_budget_exhausted'
            try:
                if amount > self.budget.remaining(task_scope): return 'shadow_task_budget_exhausted'
                if amount > self.budget.remaining(period_scope): return 'shadow_period_budget_exhausted'
                if not self.budget.reserve(task_scope, action_id, amount): return 'shadow_task_budget_reservation_refused'
            except Exception: return 'shadow_budget_authority_unavailable'
            try: period_reserved = self.budget.reserve(period_scope, action_id, amount)
            except Exception: period_reserved = False
            if not period_reserved:
                try: self.budget.settle(task_scope, action_id, ZERO)
                except Exception: return 'shadow_budget_authority_unavailable'
                return 'shadow_period_budget_reservation_refused'
            self._task_debits[task_id] = self._task_debits.get(task_id, ZERO) + amount
            self._period_debit += amount
        return None

    def _settle(self, task_id, action_id, actual, reserved):
        settled = True
        for scope in (f'{task_id}:shadow', f"shadow-period:{self.bundle.validation['version']}"):
            try: self.budget.settle(scope, action_id, actual)
            except Exception: settled = False
        if actual is not None:
            with self._lock:
                self._task_debits[task_id] += actual - reserved
                self._period_debit += actual - reserved
        return settled

    def _release(self, task_id, reservations):
        for action_id, amount in reservations: self._settle(task_id, action_id, ZERO, amount)

    @staticmethod
    def _add_cost(current, actual): return None if current is None or actual is None else current + actual

    @staticmethod
    def _run(base, status, reason, attempts, *, generation_cost=ZERO, validation_cost=ZERO):
        del generation_cost, validation_cost

        def incurred(attempt):
            if attempt.provider_outcome is None:
                return 'unstarted', ZERO
            return 'known' if attempt.actual_cost_usd is not None else 'unknown', attempt.actual_cost_usd

        generation_values, validation_values = [], []
        for attempt in attempts:
            state, amount = incurred(attempt)
            if attempt.purpose == 'generation':
                if state != 'unstarted': generation_values.append((state, amount))
                for outcome in attempt.validations:
                    validation_values.append(('unknown', None) if outcome.cost_usd is None
                                             else ('known', outcome.cost_usd))
            elif state != 'unstarted':
                validation_values.append((state, amount))

        def total(values):
            if any(state == 'unknown' for state, _ in values): return None
            return sum((amount for _, amount in values), ZERO)

        return ShadowRun(**(base | {'status': status, 'reason': reason}), attempts=attempts,
            generation_cost_usd=total(generation_values), validation_cost_usd=total(validation_values))

    def _cancel(self, attempt, cause):
        return attempt.model_copy(update={'status': AttemptStatus.CANCELLED,
            'completed_at': self.clock.now(), 'actual_cost_usd': ZERO, 'failure': self._failure(cause)})

    def _cancel_evaluator(self, request, decision, generation, binding, quote, identifier, cause, sequence):
        started = Attempt(attempt_id=identifier, task_id=request.task_id, trace_id=request.trace_id,
            sequence=sequence, purpose='evaluation', role='shadow', evaluator_ref=binding.ref,
            rubric_version=binding.rubric_version, phase4_version=self.semantic.config.version,
            parent_attempt_id=generation.attempt_id, decision=decision, status=AttemptStatus.STARTED,
            started_at=self.clock.now(), estimated_cost_usd=quote.amount, pricing_version=quote.pricing_version)
        return self._cancel(started, cause)

    def _execute(self, provider, request):
        try:
            outcome = provider.execute(request)
            fields = ('task_id', 'trace_id', 'invocation_id', 'policy_version', 'catalog_version',
                      'model_alias', 'provider_model_id', 'reasoning_effort', 'purpose')
            if not isinstance(outcome, (ProviderResult, ProviderFailure)) or any(
                    getattr(outcome, field) != getattr(request, field) for field in fields): raise ValueError
            return outcome
        except Exception: return self._contract_failure(request, 'shadow_provider_contract_error')

    @staticmethod
    def _contract_failure(request, cause):
        return ProviderFailure(**request_evidence(request), failure_type=FailureType.UNKNOWN_FAILURE,
            source='adapter', stage='invocation', cause_code=cause)

    @staticmethod
    def _provider_failure(outcome):
        return Failure(failure_type=outcome.failure_type, source=outcome.source, stage=outcome.stage,
            cause_code=outcome.cause_code, retryable=False, retry_after_ms=outcome.retry_after_ms)

    @staticmethod
    def _failure(cause, source='orchestrator'):
        kind = FailureType.BUDGET_FAILURE if source == 'admission' else (
            FailureType.VALIDATION_FAILURE if source == 'validation' else FailureType.UNKNOWN_FAILURE)
        return Failure(failure_type=kind, source=source, stage='shadow', cause_code=cause, retryable=False)

    @staticmethod
    def _callback(callback, run):
        if callback is None: return True
        try: callback(run); return True
        except Exception: return False


__all__ = ['ShadowService']
