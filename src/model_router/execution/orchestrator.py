"""Bounded synchronous execution, shared by embedded and HTTP adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from decimal import Decimal, localcontext, Context as DecimalContext, MAX_EMAX, MIN_EMIN
from uuid import uuid4
import json

from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import (Request, Classification, Candidate, EnvironmentSnapshot,
    RouteDecision, RouteRejection, FailureType, ValidationLevel, thaw, freeze)
from model_router.core.classifier_contracts import Classifier, ClassificationFailure
from model_router.core.provider_contracts import ModelProvider, ProviderRequest, ProviderResult, ProviderFailure
from model_router.core.execution_contracts import (TaskResult, TaskStatus, Attempt, AttemptStatus,
    ExecutionControls, ExecutionLimits, ExecutionEvent, TaskRepository, BudgetAuthority, Clock,
    ToolExecutor, ToolOutcome, RecoveryContext, RecoveryAction, RouteTarget, Failure,
    RepositoryUnavailable, ConcurrentUpdate)
from model_router.router import route
from model_router.policy.budgets import resolve_limits
from model_router.execution.lifecycle import transition, finish_attempt
from model_router.execution.accounting import provider_cost
from model_router.execution.arithmetic import money_sum, money_difference
from model_router.execution.admission import check_admission
from model_router.execution.safety import request_digest, scoped_key_digest
from model_router.escalation import choose_recovery
from model_router.validation.v0 import V0Validator
from model_router.execution.verification import VerificationMixin

@dataclass(frozen=True)
class ExecutionDependencies:
    bundle: PolicyBundle
    environment: EnvironmentSnapshot | Callable[[], EnvironmentSnapshot]
    provider: ModelProvider
    repository: TaskRepository
    budget: BudgetAuthority
    clock: Clock
    limits: ExecutionLimits | None
    controls: ExecutionControls = field(default_factory=ExecutionControls)
    classifier: Classifier | None = None
    validator: V0Validator = field(default_factory=V0Validator)
    tools: ToolExecutor | None = None
    semantic: object | None = None
    health: object | None = None
    shadow: object | None = None
    cancelled: Callable[[], bool] = field(default=lambda: False)


def execute(request: Request, dependencies: ExecutionDependencies, *,
            supplied_classification: Classification | None = None) -> TaskResult:
    """Execute only explicitly authorized synthetic work with finite bounds.

    Production stays disabled in Phase 3. Duplicate keys return stored metadata;
    output is intentionally unavailable after restart. Storage failures raise a
    sanitized RepositoryUnavailable after attempting durable journal retention.
    """
    # Do not inherit a caller's Decimal rounding/traps for aggregate accounting.
    with localcontext(DecimalContext(prec=80, Emax=MAX_EMAX, Emin=MIN_EMIN)):
        execution = _Execution(request, dependencies, supplied_classification)
        try:
            return execution.run()
        except _EnvironmentChanged:
            return execution.stop(execution.failure(FailureType.CAPABILITY_FAILURE,
                'trusted_execution_environment_changed'), status=TaskStatus.BLOCKED)


class _EnvironmentChanged(RuntimeError):
    pass


class _Execution(VerificationMixin):
    def __init__(self, request, deps, classification):
        self.request, self.d, self.classification = request, deps, classification
        now = deps.clock.now()
        self.task = TaskResult(task_id=request.task_id, trace_id=request.trace_id,
            status=TaskStatus.CREATED, policy_version=deps.bundle.policy['version'],
            created_at=now, updated_at=now)
        self.limits = deps.limits
        self.cost_violation = False
        self.budget_unavailable = False
        self.shadow_retention_deferred = False
        self.shadow_retention_failed = False
        self.initial_environment = None
        self.semantic_config = deps.semantic.config if deps.semantic else None
        self.health_config = deps.health.config if deps.health else None

    def environment(self):
        if self.d.semantic is not None and self.d.semantic.config != self.semantic_config:
            raise _EnvironmentChanged()
        if self.d.health is not None and self.d.health.config != self.health_config:
            raise _EnvironmentChanged()
        source = self.d.environment
        env = source() if callable(source) else source
        if self.initial_environment is None:
            self.initial_environment = env
        else:
            mutable = {'snapshot_id', 'clock', 'models', 'health_snapshot_id',
                       'health_observed_at', 'health_valid_until', 'remaining_usd',
                       'minimum_next_action_ms', 'latency_source'}
            pinned = set(type(env).model_fields) - mutable
            if any(getattr(env, key) != getattr(self.initial_environment, key) for key in pinned):
                raise _EnvironmentChanged()
        env = env.model_copy(update={'clock': self.d.clock.now()})
        if self.d.semantic is not None and env.synthetic:
            from model_router.policy.validation import determine_validation
            requirements = determine_validation(self.request, env, self.d.bundle)
            bindings = {b.ref: b for b in self.d.semantic.config.evaluators}
            configured = dict(env.validation)
            for level, profile in self.d.bundle.validation['profiles'].items():
                if profile.get('evaluator_ref') in bindings:
                    configured[ValidationLevel(level)] = 'configured_mock'
                if level == 'V3' and self.d.semantic.config.domain_validator_ref is not None:
                    configured[ValidationLevel(level)] = 'configured_mock'
            costs = [self.evaluation_quote(bindings[ref], env).amount for ref in requirements.evaluator_refs if ref in bindings]
            env = env.model_copy(update={'validation': configured,
                'required_evaluator_cost_usd': None if any(x is None for x in costs) else money_sum(costs),
                'required_domain_validator_cost_usd': self.d.semantic.domain_bound})
        if self.d.health is not None:
            snapshot = self.d.health.snapshot()
            env = self.d.health.apply(env, required_capabilities=self.request.requirements, snapshot=snapshot)
            if all(s.snapshot_id != snapshot.snapshot_id for s in self.task.health_snapshots):
                self.task = self.task.model_copy(update={'health_snapshots': (*self.task.health_snapshots, snapshot)})
        return env

    def elapsed(self):
        return max(0, int((self.d.clock.now() - self.task.created_at).total_seconds() * 1000))

    def remaining(self):
        if self.limits is None:
            return Decimal('0')
        try:
            available = self.d.budget.remaining(self.task.task_id)
        except Exception:
            self.budget_unavailable = True
            return Decimal('0')
        return max(Decimal('0'), min(available,
            money_difference(self.limits.task_cost_ceiling_usd, self.task.known_cost_usd, self.task.reserved_cost_usd)))

    def event(self, kind, *, attempt_id=None, decision_id=None, failure=None, action=None, tool_event_id=None, evaluation_id=None):
        return ExecutionEvent(event_id=str(uuid4()), task_id=self.task.task_id, trace_id=self.task.trace_id,
            kind=kind, occurred_at=self.d.clock.now(), policy_version=self.task.policy_version,
            attempt_id=attempt_id, decision_id=decision_id, failure_type=failure, action=action,
            tool_event_id=tool_event_id, evaluation_id=evaluation_id)

    def save(self, *events):
        prior = self.task.revision
        self.task = self.task.model_copy(update={'revision': prior + 1, 'updated_at': self.d.clock.now()})
        if self.shadow_retention_deferred:
            self.d.repository.retain_pending(self.task, tuple(events))
            return
        try:
            self.d.repository.save(self.task, tuple(events), expected_revision=prior)
        except RepositoryUnavailable:
            try:
                self.d.repository.retain_pending(self.task, tuple(events))
            except Exception:
                raise RepositoryUnavailable('execution evidence retention unavailable') from None
            raise RepositoryUnavailable('execution evidence retained for reconciliation') from None

    def stop(self, failure, *, status=TaskStatus.FAILED):
        self.task = transition(self.task, status, now=self.d.clock.now(), failure=failure)
        self.save(self.event({TaskStatus.FAILED: 'TASK_FAILED', TaskStatus.BLOCKED: 'TASK_BLOCKED',
                             TaskStatus.CANCELLED: 'TASK_CANCELLED'}[status], failure=failure.failure_type))
        return self.task

    def failure(self, kind, cause, source='admission'):
        return Failure(failure_type=kind, source=source, stage='execution', cause_code=cause)

    def checkpoint(self):
        self.environment()  # Recheck trusted prerequisites at every action boundary.
        if self.d.health is not None and not self.d.health.dependency_readiness().ready:
            return self.failure(FailureType.PROVIDER_FAILURE, 'required_health_unavailable')
        if self.budget_unavailable:
            return self.failure(FailureType.BUDGET_FAILURE, 'budget_authority_unavailable')
        if self.cost_violation:
            return self.failure(FailureType.BUDGET_FAILURE, "actual_cost_exceeded_reservation")
        if self.d.cancelled():
            return self.failure(FailureType.UNKNOWN_FAILURE, 'cancelled')
        if self.limits is not None and self.elapsed() >= self.limits.max_elapsed_ms:
            return self.failure(FailureType.BUDGET_FAILURE, 'deadline_exceeded')
        return None

    def validation_checkpoint(self):
        try:
            return self.checkpoint()
        except _EnvironmentChanged:
            # Return through the validator so already-incurred check evidence
            # is accounted and persisted before the task is blocked.
            return self.failure(FailureType.CAPABILITY_FAILURE, 'trusted_execution_environment_changed')

    def run(self):
        env = self.environment()
        scope = env.trusted_application_id or 'embedded'
        self.task = self.task.model_copy(update={'application_id': env.trusted_application_id})
        if self.d.semantic is not None or self.d.health is not None:
            operational = {}
            if self.d.semantic is not None:
                operational['validation'] = self.d.semantic.config.model_dump(mode='json')
            if self.d.health is not None:
                operational['health'] = self.d.health.config.model_dump(mode='json')
            import hashlib
            version = hashlib.sha256(json.dumps(operational, sort_keys=True).encode()).hexdigest()
            self.task = self.task.model_copy(update={'phase4_version': 'verification-' + version,
                'phase4_config': freeze(operational)})
        key = self.d.controls.idempotency_key
        existing = self.d.repository.create(self.task, self.event('TASK_CREATED'), scope=scope,
            key_digest=scoped_key_digest(scope, key) if key else None,
            request_digest=request_digest(self.request, self.d.controls, self.classification))
        if existing is not None:
            return existing
        snapshot = lambda value: json.loads(json.dumps(thaw(value), default=str))
        try:
            self.d.repository.pin_versions(policy_version=self.task.policy_version,
                policy_snapshot=snapshot({'policy': self.d.bundle.policy, 'budgets': self.d.bundle.budgets,
                    'validation': self.d.bundle.validation, 'content_hash': self.d.bundle.content_hash}),
                catalog_version=self.d.bundle.catalog['catalog_version'], catalog_snapshot=snapshot(self.d.bundle.catalog))
        except ConcurrentUpdate:
            return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, 'configuration_snapshot_conflict', 'storage'),
                             status=TaskStatus.BLOCKED)
        except RepositoryUnavailable:
            return self.stop(self.failure(FailureType.PROVIDER_FAILURE, 'configuration_snapshot_unavailable', 'storage'),
                             status=TaskStatus.BLOCKED)
        if not env.synthetic:
            return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, 'production_execution_disabled'), status=TaskStatus.BLOCKED)
        from model_router.execution.provider import MockProvider
        if not isinstance(self.d.provider, MockProvider):
            return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, 'mock_provider_required'), status=TaskStatus.BLOCKED)
        if self.limits is None:
            return self.stop(self.failure(FailureType.BUDGET_FAILURE, 'finite_execution_limits_required'), status=TaskStatus.BLOCKED)
        resolved = resolve_limits(self.request, env, self.d.bundle)
        if resolved.task_cost_ceiling_usd is None or resolved.task_deadline_ms is None:
            return self.stop(self.failure(FailureType.BUDGET_FAILURE, 'finite_execution_limits_required'), status=TaskStatus.BLOCKED)
        self.limits = self.limits.model_copy(update={
            'task_cost_ceiling_usd': min(self.limits.task_cost_ceiling_usd, resolved.task_cost_ceiling_usd),
            'max_elapsed_ms': min(self.limits.max_elapsed_ms, resolved.task_deadline_ms)})
        self.task = self.task.model_copy(update={'execution_limits': self.limits})
        if not self.d.controls.authorized:
            return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, 'approval_required'), status=TaskStatus.BLOCKED)
        failure = self.checkpoint()
        if failure:
            return self.stop(failure, status=TaskStatus.CANCELLED if failure.cause_code == 'cancelled' else TaskStatus.FAILED)
        if self.classification is None:
            # Phase 2 MockClassifier is a deterministic operation, no model call.
            # Paid classification needs an invocation-level reservation wrapper;
            # this phase does not permit bypassing that through Classifier.classify.
            from model_router.classification import MockClassifier
            if not isinstance(self.d.classifier, MockClassifier):
                return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, 'admitted_mock_classifier_required'), status=TaskStatus.BLOCKED)
            check = check_admission(self.request, self.d.controls, self.limits, self.task.counters,
                self.elapsed(), self.remaining(), Decimal('0'), action='classification')
            if check:
                return self.stop(check, status=TaskStatus.BLOCKED)
            classified = self.d.classifier.classify(self.request)
            if isinstance(classified, ClassificationFailure):
                return self.stop(self.failure(classified.failure_type, classified.cause_code, 'classifier'))
            self.classification = classified.classification
        self.task = transition(self.task, TaskStatus.CLASSIFIED, now=self.d.clock.now(), classification=self.classification)
        self.save(self.event('TASK_CLASSIFIED'))
        decision = self.select()
        if isinstance(decision, RouteRejection):
            return self.stop(self.failure(decision.failure_type, 'initial_route_rejected'))
        while True:
            failure = self.checkpoint()
            if failure:
                return self.stop(failure, status=TaskStatus.CANCELLED if failure.cause_code == 'cancelled' else TaskStatus.FAILED)
            blockers = self.readiness(decision)
            if blockers:
                return self.stop(self.failure(FailureType.CAPABILITY_FAILURE, blockers[0]), status=TaskStatus.BLOCKED)
            failure, validated, original = self.generate(decision)
            if failure is None:
                tool_failure = self.run_tools(decision)
                if tool_failure is not None:
                    return self.stop(tool_failure, status=TaskStatus.CANCELLED if tool_failure.cause_code == 'cancelled' else TaskStatus.BLOCKED if tool_failure.cause_code in {'unsafe_side_effect_replay', 'approval_required'} else TaskStatus.FAILED)
                failure = self.checkpoint()
                if failure:
                    return self.stop(failure, status=TaskStatus.CANCELLED if failure.cause_code == 'cancelled' else TaskStatus.FAILED)
                self.run_shadow()
                final = self.task.attempts[-1].provider_outcome
                action = RecoveryAction(action='stop_success', route=self.target(decision), validated=True, reason='validated_success')
                self.task = self.task.model_copy(update={'recovery_actions': (*self.task.recovery_actions, action)})
                self.task = transition(self.task, TaskStatus.SUCCEEDED, now=self.d.clock.now(),
                    output=final.text, structured_output=final.structured_output)
                self.save(self.event('TASK_SUCCEEDED'))
                return self.task
            if failure.source == 'evaluator':
                return self.stop(failure)
            if self.budget_unavailable:
                return self.stop(self.failure(FailureType.BUDGET_FAILURE, 'budget_authority_unavailable'))
            if failure.cause_code == 'trusted_execution_environment_changed':
                return self.stop(failure, status=TaskStatus.BLOCKED)
            if failure.cause_code == 'cancelled':
                return self.stop(failure, status=TaskStatus.CANCELLED)
            if self.task.status in {TaskStatus.ROUTED, TaskStatus.ADMITTED}:
                return self.stop(failure, status=TaskStatus.BLOCKED)
            self.task = transition(self.task, TaskStatus.RECOVERING, now=self.d.clock.now())
            context = RecoveryContext(decision=decision, failure=failure, counters=self.task.counters,
                limits=self.limits, environment=self.environment(), remaining_usd=self.remaining(),
                elapsed_ms=self.elapsed(), validated=validated, original_failure=original)
            action = (RecoveryAction(action='diagnose', failure=failure.failure_type,
                route=self.target(decision), original_failure=original, reason='quality_confirmation_required')
                if failure.failure_type == FailureType.QUALITY_FAILURE and not validated
                else choose_recovery(context, self.d.bundle))
            if action.action in {'increase_effort', 'increase_tier', 'retry_backoff', 'health_aware_fallback'}:
                if action.backoff_ms:
                    if self.elapsed() + action.backoff_ms >= self.limits.max_elapsed_ms:
                        action = RecoveryAction(action='stop_deadline', failure=FailureType.BUDGET_FAILURE,
                            original_failure=failure.failure_type, validated=validated, reason='deadline_exceeded')
                    else:
                        self.d.clock.sleep(action.backoff_ms)
                if action.route is not None:
                    next_decision = self.select(action.route, persist=False)
                    if isinstance(next_decision, RouteRejection) or self.readiness(next_decision):
                        action = RecoveryAction(action='stop_budget' if isinstance(next_decision, RouteRejection) and
                            next_decision.failure_type == FailureType.BUDGET_FAILURE else 'recoverable_failure',
                            failure=next_decision.failure_type if isinstance(next_decision, RouteRejection) else failure.failure_type,
                            original_failure=failure.failure_type, validated=validated,
                            rationale_codes=action.rationale_codes, reason='recovery_route_unavailable')
            self.task = self.task.model_copy(update={'recovery_actions': (*self.task.recovery_actions, action)})
            self.save(self.event('RECOVERY_SELECTED', failure=action.failure, action=action.action))
            if action.action not in {'increase_effort', 'increase_tier', 'retry_backoff', 'health_aware_fallback'}:
                terminal = self.failure(action.failure or failure.failure_type, action.reason, failure.source)
                return self.stop(terminal)
            field = 'quality_escalations' if action.action.startswith('increase_') else 'infrastructure_retries'
            self.task = self.task.model_copy(update={'counters': self.task.counters.model_copy(update={field: getattr(self.task.counters, field) + 1})})
            decision = self.select(action.route)
            if isinstance(decision, RouteRejection):
                return self.stop(self.failure(decision.failure_type, 'recovery_route_rejected'))

    def target(self, decision):
        return RouteTarget(model=decision.selected_model_alias, effort=decision.reasoning_effort)

    def select(self, target=None, *, persist=True):
        env = self.environment().model_copy(update={'remaining_usd': self.remaining()})
        kwargs = {'recovery_candidates': (Candidate(model=target.model, effort=target.effort, source='fallback'),)} if target else {}
        decision = route(self.request, self.classification, env, self.d.bundle, **kwargs)
        if persist:
            self.task = transition(self.task, TaskStatus.ROUTED, now=self.d.clock.now(),
                initial_decision=self.task.initial_decision or decision,
                decisions=(*self.task.decisions, decision))
            self.save(self.event('ROUTE_SELECTED', decision_id=decision.decision_id))
        return decision

    def readiness(self, decision):
        if isinstance(decision, RouteRejection):
            return ('route_rejected',)
        blockers = list(decision.readiness_blockers)
        # Phase 1's placeholder blocker is discharged only by explicit scoped
        # Phase 3 tool authorization, never by forging a route-only preview.
        if 'side_effect_execution_unconfigured' in blockers and self.d.controls.side_effects_authorized and self.d.tools and self.d.controls.tool_calls:
            blockers.remove('side_effect_execution_unconfigured')
        v0_decision = decision.model_copy(update={'validation_level': 'V0'}) if self.d.semantic is not None else decision
        v0_blockers = self.d.validator.readiness(v0_decision, self.d.controls)
        if self.d.semantic is not None:
            blockers.extend(self.phase4_readiness(decision))
        blockers.extend(v0_blockers)
        if self.request.context.expected_output_tokens <= 0:
            blockers.append('positive_output_bound_required')
        if self.d.controls.tool_calls and self.d.tools is None:
            blockers.append('tool_executor_unavailable')
        if self.d.health is not None:
            for call in self.d.controls.tool_calls:
                if not self.d.health.available('tool', capability=call.tool):
                    blockers.append('required_tool_unavailable')
        if self.request.side_effecting_tool and not any(t.side_effecting for t in self.d.controls.tool_calls):
            blockers.append('side_effect_scope_missing')
        return tuple(blockers)

    def charge(self, action_id, actual, estimate):
        if actual is not None and actual > estimate:
            self.cost_violation = True
        settled = True
        try:
            self.d.budget.settle(self.task.task_id, action_id, actual)
        except Exception:
            settled = False
            self.budget_unavailable = True
        self.task = self.task.model_copy(update={
            'known_cost_usd': money_sum((self.task.known_cost_usd, actual if actual is not None else Decimal('0'))),
            'reserved_cost_usd': money_difference(self.task.reserved_cost_usd, estimate if actual is not None and settled else Decimal('0')),
            'total_cost_usd': None if actual is None or self.task.total_cost_usd is None else money_sum((self.task.total_cost_usd, actual))})

    def reserve(self, action_id, amount):
        try:
            reserved = self.d.budget.reserve(self.task.task_id, action_id, amount)
        except Exception:
            self.budget_unavailable = True
            return False
        if not reserved:
            return False
        self.task = self.task.model_copy(update={'reserved_cost_usd': money_sum((self.task.reserved_cost_usd, amount))})
        return True

    def generate(self, decision):
        env = self.environment()
        quote = decision.estimated_cost
        miss = decision.rationale_details.get('cache_miss_budget_estimates', {}).get(decision.selected_model_alias)
        estimate = max(quote.generation_subtotal, Decimal(miss['generation_subtotal'])) if miss else quote.generation_subtotal
        check_cost = quote.amount
        validation_bound = self.d.validator.upper_bound(self.d.controls)
        semantic_bound = self.semantic_bound(decision)
        tool_bounds = [call.cost_upper_bound_usd for call in self.d.controls.tool_calls]
        if check_cost is None or validation_bound is None or semantic_bound is None or any(x is None for x in tool_bounds):
            check_cost = None
        else:
            # The future required work must fit now, and is checked again just
            # before dispatch. Expected cache hits never reduce the reserve.
            check_cost = max(check_cost, money_sum((estimate, validation_bound, semantic_bound, *tool_bounds)))
        failure = check_admission(self.request, self.d.controls, self.limits, self.task.counters,
            self.elapsed(), self.remaining(), check_cost, action='generation')
        if failure:
            return failure, False, None
        attempt_id = str(uuid4())
        if not self.reserve(attempt_id, estimate):
            return self.failure(FailureType.BUDGET_FAILURE, 'budget_reservation_refused'), False, None
        self.task = transition(self.task, TaskStatus.ADMITTED, now=self.d.clock.now())
        counters = self.task.counters.model_copy(update={'generation_attempts': self.task.counters.generation_attempts + 1})
        started = Attempt(attempt_id=attempt_id, task_id=self.task.task_id, trace_id=self.task.trace_id,
            sequence=len(self.task.attempts) + 1, parent_attempt_id=self.task.attempts[-1].attempt_id if self.task.attempts else None,
            decision=decision, status=AttemptStatus.STARTED, started_at=self.d.clock.now(),
            estimated_cost_usd=estimate, pricing_version=decision.pricing_version)
        self.task = transition(self.task, TaskStatus.RUNNING, now=self.d.clock.now(),
            attempts=(*self.task.attempts, started), counters=counters)
        self.save(self.event('ATTEMPT_STARTED', attempt_id=attempt_id, decision_id=decision.decision_id))
        failure = self.checkpoint()
        if failure is None:
            refreshed_env = self.environment().model_copy(update={'remaining_usd': money_sum((self.remaining(), estimate))})
            refreshed = route(self.request, self.classification, refreshed_env, self.d.bundle,
                recovery_candidates=(Candidate(model=decision.selected_model_alias, effort=decision.reasoning_effort, source='fallback'),))
            if isinstance(refreshed, RouteRejection) or self.readiness(refreshed):
                failure = self.failure(refreshed.failure_type if isinstance(refreshed, RouteRejection) else FailureType.CAPABILITY_FAILURE,
                    'dispatch_readiness_changed')
        if failure is not None:
            self.charge(attempt_id, Decimal('0'), estimate)
            completed = finish_attempt(started, started.model_copy(update={
                'status': AttemptStatus.CANCELLED, 'completed_at': self.d.clock.now(),
                'actual_cost_usd': Decimal('0'), 'failure': failure}))
            self.task = self.task.model_copy(update={'attempts': (*self.task.attempts[:-1], completed)})
            self.save(self.event('ATTEMPT_COMPLETED', attempt_id=attempt_id, failure=failure.failure_type))
            return failure, False, None
        request = ProviderRequest(task_id=self.task.task_id, trace_id=self.task.trace_id, invocation_id=attempt_id,
            policy_version=decision.policy_version, catalog_version=decision.catalog_version,
            model_alias=decision.selected_model_alias, provider_model_id=decision.provider_model_id,
            reasoning_effort=decision.reasoning_effort, input=self.request.input,
            output_type=self.d.controls.output_type, max_output_tokens=max(1, self.request.context.expected_output_tokens),
            timeout_ms=max(1, self.limits.max_elapsed_ms - self.elapsed()))
        try:
            outcome = self.d.provider.execute(request)
            if not isinstance(outcome, (ProviderResult, ProviderFailure)) or any(
                getattr(outcome, a) != getattr(request, a) for a in ('task_id', 'trace_id', 'invocation_id',
                    'policy_version', 'catalog_version', 'model_alias', 'provider_model_id', 'reasoning_effort', 'purpose')):
                raise ValueError('provider correlation mismatch')
        except Exception:
            from model_router.execution.provider import request_evidence
            outcome = ProviderFailure(**request_evidence(request), failure_type=FailureType.UNKNOWN_FAILURE,
                source='adapter', stage='invocation', cause_code='provider_contract_error')
        actual = provider_cost(self.request, outcome, self.d.bundle, env)
        interim = started.model_copy(update={'provider_outcome': outcome, 'actual_cost_usd': actual})
        self.task = self.task.model_copy(update={'attempts': (*self.task.attempts[:-1], interim)})
        self.save()  # Provider evidence survives even a failed ledger settlement.
        self.charge(attempt_id, actual, estimate)
        self.add_cost('production_generation_cost_usd', actual)
        if self.d.health is not None:
            self.d.health.observe('provider', model=decision.selected_model_alias,
                failure=outcome.failure_type if isinstance(outcome, ProviderFailure) else None,
                success=not isinstance(outcome, ProviderFailure))
        original, validated, validations = None, False, ()
        failure = Failure(failure_type=outcome.failure_type, source=outcome.source, stage=outcome.stage,
            cause_code=outcome.cause_code, retryable=outcome.retryable, retry_after_ms=outcome.retry_after_ms) if isinstance(outcome, ProviderFailure) else None
        interim = started.model_copy(update={'provider_outcome': outcome, 'actual_cost_usd': actual})
        self.task = self.task.model_copy(update={'attempts': (*self.task.attempts[:-1], interim)})
        if failure is None:
            self.task = transition(self.task, TaskStatus.VALIDATING, now=self.d.clock.now())
            self.save()
            failure = self.checkpoint()
            if failure is None:
                failure = check_admission(self.request, self.d.controls, self.limits, self.task.counters,
                    self.elapsed(), self.remaining(), validation_bound, action='validation')
            validation_id = str(uuid4())
            if failure is None and not self.reserve(validation_id, validation_bound):
                failure = self.failure(FailureType.BUDGET_FAILURE, 'validation_reservation_refused')
            if failure is None:
                # Reservation retained in durable task before executing hooks.
                self.save()
                validations = self.d.validator.validate(self.request, outcome, self.d.controls, before_check=self.validation_checkpoint)
                costs = [v.cost_usd for v in validations]
                validation_cost = None if any(x is None for x in costs) else money_sum(costs)
                self.charge(validation_id, validation_cost, validation_bound)
                self.add_cost('production_validation_cost_usd', validation_cost)
                problem = next((v for v in validations if v.failure and v.failure.failure_type == FailureType.BUDGET_FAILURE),
                    next((v for v in validations if v.failure is not None), None))
                validated = all(v.status == 'passed' for v in validations)
                if problem:
                    failure = problem.failure
                    validated = (failure.failure_type == FailureType.QUALITY_FAILURE and
                        problem.status == 'failed' and failure.source == 'validation' and bool(problem.evidence_code))
                    if problem.diagnosed_failure is not None:
                        original = failure.failure_type
                        failure = failure.model_copy(update={'failure_type': problem.diagnosed_failure})
                        validated = failure.failure_type == FailureType.QUALITY_FAILURE
        if failure is None and self.d.semantic is not None:
            semantic_results, failure = self.verify_semantic(decision, outcome)
            # Evaluation results are stored with evaluator attempts, not duplicated
            # in the generation row. This keeps both evidence streams immutable.
            validated = failure is None or (failure.failure_type == FailureType.QUALITY_FAILURE and
                any(v.status == 'failed' and v.evidence_code for v in semantic_results))
        failure = failure or self.validation_checkpoint()
        completed = finish_attempt(started, interim.model_copy(update={
            'status': AttemptStatus.FAILED if failure else AttemptStatus.SUCCEEDED,
            'completed_at': self.d.clock.now(), 'failure':
                (next((v.failure for v in validations if v.failure), None) if original else failure),
            'validations': validations}))
        self.task = self.task.model_copy(update={'attempts': (*self.task.attempts[:-1], completed)})
        events = [self.event('ATTEMPT_COMPLETED', attempt_id=attempt_id, failure=failure.failure_type if failure else None)]
        events.extend(self.event('VALIDATION_COMPLETED', attempt_id=attempt_id, evaluation_id=v.evaluation_id,
            failure=v.failure.failure_type if v.failure else None) for v in validations)
        self.save(*events)
        return failure, validated, original

    def run_tools(self, decision):
        for initial_call in self.d.controls.tool_calls:
            call, replay = initial_call, False
            while True:
                self.environment()  # Recheck pinned authorization/readiness before each tool action.
                failure = self.checkpoint() or check_admission(self.request, self.d.controls, self.limits,
                    self.task.counters, self.elapsed(), self.remaining(), call.cost_upper_bound_usd,
                    action='tool', replay=replay, tool_call=call)
                if failure:
                    return failure
                if self.d.health is not None and not self.d.health.available('tool', capability=call.tool):
                    return self.failure(FailureType.TOOL_FAILURE, 'required_tool_unavailable', 'tool')
                event_id = str(uuid4())
                if not self.reserve(event_id, call.cost_upper_bound_usd):
                    return self.failure(FailureType.BUDGET_FAILURE, 'tool_reservation_refused')
                started = ToolOutcome(tool_event_id=event_id, tool=call.tool, operation=call.operation,
                    status='started', side_effecting=call.side_effecting,
                    estimated_cost_usd=call.cost_upper_bound_usd, parent_attempt_id=self.task.attempts[-1].attempt_id,
                    replay_safe=bool(call.idempotency_key or call.reconciliation_evidence))
                self.task = self.task.model_copy(update={'tool_events': (*self.task.tool_events, started)})
                self.save(self.event('TOOL_STARTED', tool_event_id=event_id, attempt_id=started.parent_attempt_id))
                pre_dispatch = self.checkpoint()
                if pre_dispatch is None and self.d.health is not None and not self.d.health.available('tool', capability=call.tool):
                    pre_dispatch = self.failure(FailureType.TOOL_FAILURE, 'required_tool_unavailable', 'tool')
                if pre_dispatch:
                    outcome = started.model_copy(update={'status': 'failed', 'failure': pre_dispatch, 'cost_usd': Decimal('0')})
                    self.charge(event_id, Decimal('0'), call.cost_upper_bound_usd)
                    self.task = self.task.model_copy(update={'tool_events': (*self.task.tool_events[:-1], outcome)})
                    self.save(self.event('TOOL_COMPLETED', tool_event_id=event_id, attempt_id=started.parent_attempt_id, failure=pre_dispatch.failure_type))
                    return pre_dispatch
                try:
                    outcome = self.d.tools.execute(call, task_id=self.task.task_id, trace_id=self.task.trace_id, event_id=event_id)
                    if not isinstance(outcome, ToolOutcome) or outcome.tool_event_id != event_id or outcome.tool != call.tool or outcome.operation != call.operation:
                        raise ValueError('tool correlation mismatch')
                    if outcome.status not in {'succeeded', 'failed'} or (outcome.status == 'failed') != (outcome.failure is not None):
                        raise ValueError('tool outcome invalid')
                    if outcome.failure and (outcome.failure.failure_type != FailureType.TOOL_FAILURE or outcome.failure.source != 'tool'):
                        raise ValueError('tool failure taxonomy invalid')
                except Exception:
                    outcome = started.model_copy(update={'status': 'unknown', 'failure': self.failure(
                        FailureType.TOOL_FAILURE, 'tool_contract_error', 'tool')})
                outcome = outcome.model_copy(update={'estimated_cost_usd': started.estimated_cost_usd, 'parent_attempt_id': started.parent_attempt_id,
                    'side_effecting': started.side_effecting, 'replay_safe': started.replay_safe})
                if self.d.health is not None:
                    self.d.health.observe('tool', capability=call.tool,
                        failure=outcome.failure.failure_type if outcome.failure else None, success=outcome.failure is None)
                self.charge(event_id, outcome.cost_usd, call.cost_upper_bound_usd)
                self.task = self.task.model_copy(update={'tool_events': (*self.task.tool_events[:-1], outcome)})
                self.save(self.event('TOOL_COMPLETED', tool_event_id=event_id, attempt_id=started.parent_attempt_id, failure=outcome.failure.failure_type if outcome.failure else None))
                if outcome.failure is None:
                    break
                self.task = transition(self.task, TaskStatus.RECOVERING, now=self.d.clock.now())
                action = choose_recovery(RecoveryContext(decision=decision, failure=outcome.failure,
                    counters=self.task.counters, limits=self.limits, environment=self.environment(),
                    remaining_usd=self.remaining(), elapsed_ms=self.elapsed(), tool_call=call,
                    tool_retryable=outcome.failure.retryable,
                    alternate_authorized=call.alternate_tool in self.d.controls.authorized_tools if call.alternate_tool else False), self.d.bundle)
                self.task = self.task.model_copy(update={'recovery_actions': (*self.task.recovery_actions, action)})
                self.save(self.event('RECOVERY_SELECTED', failure=action.failure, action=action.action))
                if action.action not in {'retry_tool', 'alternate_tool'}:
                    return self.failure(action.failure or FailureType.TOOL_FAILURE,
                        'unsafe_side_effect_replay' if action.action == 'stop_reconcile' else action.reason, 'tool')
                self.task = self.task.model_copy(update={'counters': self.task.counters.model_copy(update={
                    'tool_recoveries': self.task.counters.tool_recoveries + 1})})
                if action.action == 'alternate_tool':
                    call = call.model_copy(update={'tool': call.alternate_tool, 'alternate_tool': None})
                replay = True
                self.task = transition(self.task, TaskStatus.VALIDATING, now=self.d.clock.now())
        return None
