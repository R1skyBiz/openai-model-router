from dataclasses import replace
from decimal import Decimal
from uuid import uuid4
import pytest
from pydantic import BaseModel
from phase3_support import setup, success
from model_router.core.contracts import FailureType, Candidate, Limits, ValidationLevel
from model_router.core.execution_contracts import (TaskStatus, ExecutionControls, Failure,
    ValidationOutcome, ToolCall, ToolOutcome, IdempotencyConflict, RepositoryUnavailable)
from model_router.core.provider_contracts import ProviderFailure, ProviderResult
from model_router.execution.provider import request_evidence, MockProvider
from model_router.execution.orchestrator import execute
from model_router.execution.lifecycle import transition
from model_router.validation.v0 import V0Validator, DeterministicCheck
from model_router.execution.tools import MockToolExecutor
from model_router.router import route


def quality_check(*_):
    return ValidationOutcome(evaluation_id=str(uuid4()), check='quality', status='failed',
        failure=Failure(failure_type='QUALITY_FAILURE', source='validation', stage='validation', cause_code='invariant_failed'),
        evidence_code='explicit_invariant')


def test_success_privacy_and_restart(tmp_path):
    req, cl, deps = setup(tmp_path)
    result = execute(req, deps, supplied_classification=cl)
    assert result.status == TaskStatus.SUCCEEDED
    assert result.output == 'private output'
    persisted = deps.repository.get(req.task_id)
    assert persisted.output is None
    assert persisted.total_cost_usd == Decimal('.00014')
    assert 'private prompt' not in (tmp_path/'state.db').read_bytes().decode('latin1')
    assert 'private output' not in (tmp_path/'state.db').read_bytes().decode('latin1')
    assert len(deps.repository.pending_outbox()) >= 7


def test_quality_canonical_chain_and_prior_attempt_immutability(tmp_path):
    req, cl, deps = setup(tmp_path, [success, success, success])
    count = 0
    def check(*args):
        nonlocal count
        count += 1
        return quality_check() if count < 3 else ValidationOutcome(evaluation_id=str(uuid4()), check='quality', status='passed')
    deps = replace(deps, controls=ExecutionControls(authorized=True, required_checks=('quality',)),
        validator=V0Validator({'quality': DeterministicCheck(check)}))
    result = execute(req, deps, supplied_classification=cl)
    assert result.status == TaskStatus.SUCCEEDED
    assert [(a.decision.selected_model_alias, a.decision.reasoning_effort) for a in result.attempts] == [
        ('terra','medium'), ('terra','high'), ('sol','medium')]
    assert result.attempts[0].failure.failure_type == FailureType.QUALITY_FAILURE
    assert len({a.attempt_id for a in result.attempts}) == 3
    assert result.initial_decision == result.attempts[0].decision
    assert result.total_cost_usd == sum(a.actual_cost_usd for a in result.attempts)


def test_timeout_retry_preserves_original_and_unknown_cost(tmp_path):
    def timeout(req):
        return ProviderFailure(**request_evidence(req), failure_type='TIMEOUT', source='provider',
            stage='invocation', cause_code='timeout', retryable=True, retry_after_ms=500)
    req, cl, deps = setup(tmp_path,[timeout, success])
    result = execute(req, deps, supplied_classification=cl)
    assert result.status == 'succeeded'
    assert result.attempts[0].failure.failure_type == 'TIMEOUT'
    assert result.attempts[1].decision.selected_model_alias == result.attempts[0].decision.selected_model_alias
    assert result.total_cost_usd is None and result.known_cost_usd > 0 and result.reserved_cost_usd > 0
    assert deps.clock.sleeps == [500]


def test_idempotency_does_not_repeat_and_conflicting_input_rejected(tmp_path):
    req, cl, deps = setup(tmp_path, controls=ExecutionControls(authorized=True, idempotency_key='logical'))
    first = execute(req,deps,supplied_classification=cl)
    second = execute(req.model_copy(update={'task_id':'other','trace_id':'different'}),deps,supplied_classification=cl)
    assert second.task_id == first.task_id and deps.provider.call_count == 1
    with pytest.raises(IdempotencyConflict):
        execute(req.model_copy(update={'input':'changed'}),deps,supplied_classification=cl)


@pytest.mark.parametrize('kind', ['V1', 'V2', 'V3'])
def test_stronger_validation_is_blocked_without_generation(tmp_path,kind):
    req, cl, deps = setup(tmp_path)
    req = req.model_copy(update={'requested_validation':ValidationLevel(kind)})
    result = execute(req,deps,supplied_classification=cl)
    assert result.status == 'blocked' and deps.provider.call_count == 0


def test_null_limits_and_production_blocked(tmp_path):
    req, cl, deps = setup(tmp_path)
    result = execute(req,replace(deps,limits=None),supplied_classification=cl)
    assert result.status == 'blocked' and not result.attempts
    req = req.model_copy(update={'task_id':'second'})
    env = deps.environment.model_copy(update={'synthetic':False})
    result = execute(req,replace(deps,environment=env),supplied_classification=cl)
    assert result.failure.cause_code == 'production_execution_disabled'
    assert deps.provider.call_count == 0


def test_generation_cannot_run_after_deadline(tmp_path):
    req, cl, deps = setup(tmp_path)
    def slow(req):
        deps.clock.advance(30000)
        return success(req)
    deps = replace(deps,provider=MockProvider([slow,success]))
    result = execute(req,deps,supplied_classification=cl)
    assert result.status != 'succeeded' and deps.provider.call_count == 1
    assert result.attempts[0].provider_outcome.response_status == 'completed'


def test_cache_miss_bound_checked_before_provider(tmp_path):
    req, cl, deps = setup(tmp_path)
    req = req.model_copy(update={'context':req.context.model_copy(update={'cached_input_tokens':100,'cache_evidence':True})})
    req = req.model_copy(update={'constraints':Limits(model_tier_floor=1,model_tier_ceiling=1)})
    decision = route(req,cl,deps.environment,deps.bundle)
    expected = decision.estimated_cost.amount
    miss = Decimal(decision.rationale_details['cache_miss_budget_estimates']['terra']['amount'])
    assert miss > expected
    deps.budget.set_balance(req.task_id,str((expected+miss)/2))
    result = execute(req,deps,supplied_classification=cl)
    assert result.status != 'succeeded' and deps.provider.call_count == 0


def test_unknown_required_tool_cost_blocks_before_generation(tmp_path):
    req, cl, deps = setup(tmp_path,controls=ExecutionControls(authorized=True,authorized_tools=('lookup',),
        tool_calls=(ToolCall(tool='lookup',operation='read'),)),tools=MockToolExecutor([]))
    result = execute(req,deps,supplied_classification=cl)
    assert result.status == 'blocked' and deps.provider.call_count == 0


def test_unsafe_tool_replay_stops_without_generation_escalation(tmp_path):
    call = ToolCall(tool='write', operation='save', side_effecting=True,cost_upper_bound_usd='0')
    tools = MockToolExecutor([ToolOutcome(tool_event_id='x',tool='write',operation='save',status='failed',cost_usd='0',
        failure=Failure(failure_type='TOOL_FAILURE',source='tool',stage='execution',cause_code='timeout',retryable=True))])
    req, cl, deps = setup(tmp_path,controls=ExecutionControls(authorized=True,authorized_tools=('write',),
        side_effects_authorized=True,tool_calls=(call,)),tools=tools)
    result = execute(req,deps,supplied_classification=cl)
    assert result.status == 'blocked' and tools.call_count == 1 and deps.provider.call_count == 1
    assert result.recovery_actions[-1].action == 'stop_reconcile'


def test_diagnostic_preserves_original_validation_evidence(tmp_path):
    def diagnosis(*_):
        return ValidationOutcome(evaluation_id=str(uuid4()),check='diagnostic',status='failed',
            failure=Failure(failure_type='MALFORMED_OUTPUT',source='validation',stage='validation',cause_code='bad_shape'),
            diagnosed_failure='QUALITY_FAILURE', evidence_code='invariant_proves_quality')
    req, cl, deps = setup(tmp_path,[success]*3,controls=ExecutionControls(authorized=True,required_checks=('diagnostic',)),
        validator=V0Validator({'diagnostic':DeterministicCheck(diagnosis)}))
    result = execute(req,deps,supplied_classification=cl)
    assert result.attempts[0].failure.failure_type == 'MALFORMED_OUTPUT'
    assert result.attempts[0].validations[-1].diagnosed_failure == 'QUALITY_FAILURE'
    assert result.recovery_actions[0].original_failure == 'MALFORMED_OUTPUT'
    assert len(result.attempts) == 3


def test_invalid_transition_loud(tmp_path):
    req,cl,deps=setup(tmp_path)
    result=execute(req,deps,supplied_classification=cl)
    with pytest.raises(ValueError):
        transition(result,TaskStatus.RUNNING,now=deps.clock.now())


def test_recovery_route_cannot_bypass_hard_floor(tmp_path):
    req,cl,deps=setup(tmp_path)
    cl=cl.model_copy(update={'task_family':'coding','flags':{'substantive_implementation':True}})
    decision=route(req,cl,deps.environment,deps.bundle,recovery_candidates=(Candidate(model='luna',effort='medium',source='fallback'),))
    assert decision.routing_result == 'rejected'


def test_unconfirmed_provider_quality_does_not_escalate(tmp_path):
    def unconfirmed(req):
        return ProviderFailure(**request_evidence(req), failure_type='QUALITY_FAILURE',source='adapter',
            stage='normalization',cause_code='unconfirmed')
    req,cl,deps=setup(tmp_path,[unconfirmed,success])
    result=execute(req,deps,supplied_classification=cl)
    assert deps.provider.call_count == 1
    assert result.recovery_actions[-1].action == 'diagnose'


def test_cancel_during_invocation_retains_evidence(tmp_path):
    cancel=False
    def work(req):
        nonlocal cancel
        cancel=True
        return success(req)
    req,cl,deps=setup(tmp_path,[work],cancelled=lambda:cancel)
    result=execute(req,deps,supplied_classification=cl)
    assert result.status == 'cancelled'
    assert result.attempts[0].provider_outcome is not None


def test_real_adapter_cannot_use_synthetic_flag_to_dispatch(tmp_path):
    from model_router.execution.openai_provider import OpenAIProvider
    req,cl,deps=setup(tmp_path)
    deps=replace(deps,provider=OpenAIProvider(deps.bundle))
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='blocked' and result.failure.cause_code=='mock_provider_required'


def test_mock_classifier_runs_and_failure_persists(tmp_path):
    from model_router.classification import MockClassifier, load_classifier_config
    req,cl,deps=setup(tmp_path)
    config=load_classifier_config('config/classifier.yaml',deps.bundle)
    payload=dict(task_family=cl.task_family,task_subclass=None,components=cl.components.model_dump(),confidence=1.,
        flags={flag:False for flag in ('substantive_implementation','repository_wide','multivariable',
            'consequential_multi_system','long_horizon','exceptional_end_to_end')})
    classifier=MockClassifier([payload],deps.bundle,config)
    deps=replace(deps,classifier=classifier)
    result=execute(req,deps)
    assert result.status=='succeeded' and classifier.call_count==1
    req=req.model_copy(update={'task_id':'empty-script'})
    result=execute(req,deps)
    assert result.status=='failed' and result.failure.source=='classifier'
    assert deps.repository.get(req.task_id).status=='failed'


def test_completion_persistence_failure_retains_provider_evidence_in_journal(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path)
    save=deps.repository.save
    def outage(task,events,**kwargs):
        if task.attempts and task.attempts[-1].provider_outcome is not None:
            raise RepositoryUnavailable('unavailable')
        return save(task,events,**kwargs)
    monkeypatch.setattr(deps.repository,'save',outage)
    with pytest.raises(RepositoryUnavailable,match='retained'):
        execute(req,deps,supplied_classification=cl)
    assert deps.provider.call_count==1
    persisted=deps.repository.get(req.task_id)
    assert persisted.attempts[0].status=='started'
    assert 'provider_outcome' in deps.repository.journal_path.read_text()
    monkeypatch.setattr(deps.repository,'save',save)
    assert deps.repository.reconcile_pending()==1
    persisted=deps.repository.get(req.task_id)
    assert persisted.attempts[0].provider_outcome.response_status=='completed'
    execute(req,deps,supplied_classification=cl)
    assert deps.provider.call_count==1


def test_storage_failure_before_dispatch_never_calls_provider(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path)
    save=deps.repository.save
    def outage(task,events,**kwargs):
        if task.attempts:
            raise RepositoryUnavailable('unavailable')
        return save(task,events,**kwargs)
    monkeypatch.setattr(deps.repository,'save',outage)
    with pytest.raises(RepositoryUnavailable):
        execute(req,deps,supplied_classification=cl)
    assert deps.provider.call_count==0


def test_validator_infrastructure_error_never_escalates(tmp_path):
    def unavailable(*args):
        raise RuntimeError('secret provider exception')
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,required_checks=('compile',)),
        validator=V0Validator({'compile':DeterministicCheck(unavailable)}))
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='failed' and deps.provider.call_count==1
    assert result.recovery_actions[-1].action=='diagnose'
    assert 'secret provider exception' not in result.model_dump_json()


def test_slow_storage_cannot_dispatch_after_deadline(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path)
    save=deps.repository.save
    def slow(task,events,**kwargs):
        result=save(task,events,**kwargs)
        if any(e.kind=='ATTEMPT_STARTED' for e in events):
            deps.clock.advance(30000)
        return result
    monkeypatch.setattr(deps.repository,'save',slow)
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='failed' and deps.provider.call_count==0
    assert result.attempts[0].status=='cancelled'
    assert result.total_cost_usd==0


def test_each_required_hook_checks_deadline(tmp_path):
    calls=[]
    def first(*_):
        calls.append('first')
        deps.clock.advance(30000)
        return ValidationOutcome(evaluation_id=str(uuid4()),check='first',status='passed')
    def second(*_):
        calls.append('second')
        return ValidationOutcome(evaluation_id=str(uuid4()),check='second',status='passed')
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,required_checks=('first','second')),
        validator=V0Validator({'first':DeterministicCheck(first),'second':DeterministicCheck(second)}))
    result=execute(req,deps,supplied_classification=cl)
    assert calls==['first'] and result.status=='failed'


def test_snapshot_failure_terminalizes_claim_instead_of_stuck_created(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path)
    def unavailable(**kwargs):
        raise RepositoryUnavailable('private storage exception')
    monkeypatch.setattr(deps.repository,'pin_versions',unavailable)
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='blocked'
    assert result.failure.cause_code=='configuration_snapshot_unavailable'
    assert deps.repository.get(req.task_id).status=='blocked'
    replay=execute(req,deps,supplied_classification=cl)
    assert replay.status=='blocked' and deps.provider.call_count==0


def test_nonretryable_infrastructure_does_not_retry(tmp_path):
    def failure(req):
        return ProviderFailure(**request_evidence(req),failure_type='PROVIDER_FAILURE',source='provider',
            stage='invocation',cause_code='nonretryable',retryable=False)
    req,cl,deps=setup(tmp_path,[failure,success])
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='failed' and deps.provider.call_count==1
    assert result.recovery_actions[-1].reason=='infrastructure_not_retryable'


def test_validator_error_cannot_claim_quality_failure(tmp_path):
    def error(*_):
        return ValidationOutcome(evaluation_id=str(uuid4()),check='quality',status='error',
            failure=Failure(failure_type='QUALITY_FAILURE',source='validation',stage='validation',cause_code='error'),
            evidence_code='error_is_not_quality')
    req,cl,deps=setup(tmp_path,[success]*3,controls=ExecutionControls(authorized=True,required_checks=('quality',)),
        validator=V0Validator({'quality':DeterministicCheck(error)}))
    result=execute(req,deps,supplied_classification=cl)
    assert deps.provider.call_count==1 and result.recovery_actions[-1].action=='diagnose'
    assert result.attempts[0].validations[-1].status=='error'


def test_hook_cost_overrun_stops_next_hook(tmp_path):
    calls=[]
    def first(*_):
        calls.append('first')
        return ValidationOutcome(evaluation_id=str(uuid4()),check='first',status='passed',cost_usd='1')
    def second(*_):
        calls.append('second')
        return ValidationOutcome(evaluation_id=str(uuid4()),check='second',status='passed',cost_usd='.1')
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,required_checks=('first','second')),
        validator=V0Validator({'first':DeterministicCheck(first,Decimal('.1')),'second':DeterministicCheck(second,Decimal('.1'))}))
    result=execute(req,deps,supplied_classification=cl)
    assert calls==['first'] and result.status=='failed'
    assert result.known_cost_usd>1


def test_application_scope_cannot_drift_between_claim_and_dispatch(tmp_path):
    req,cl,deps=setup(tmp_path)
    snapshots=iter([deps.environment.model_copy(update={'trusted_application_id':'a'}),
                    deps.environment.model_copy(update={'trusted_application_id':'b'})])
    deps=replace(deps,environment=lambda:next(snapshots))
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='blocked' and result.failure.cause_code=='trusted_execution_environment_changed'
    assert deps.provider.call_count==0 and result.application_id=='a'


def test_snapshot_conflict_terminalizes_claim(tmp_path):
    req,cl,deps=setup(tmp_path)
    deps.repository.store_policy_version(deps.bundle.policy['version'],{'different':'snapshot'})
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='blocked' and result.failure.cause_code=='configuration_snapshot_conflict'
    assert execute(req,deps,supplied_classification=cl).status=='blocked'
    assert deps.provider.call_count==0


def test_outbox_correlates_every_tool_and_validation_record(tmp_path):
    call=ToolCall(tool='read',operation='read',cost_upper_bound_usd='0')
    tools=MockToolExecutor([ToolOutcome(tool_event_id='ignored',tool='read',operation='read',status='succeeded',cost_usd='0')])
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,authorized_tools=('read',),tool_calls=(call,)),tools=tools)
    result=execute(req,deps,supplied_classification=cl)
    events=deps.repository.pending_outbox()
    for tool in result.tool_events:
        linked=[e for e in events if e.tool_event_id==tool.tool_event_id]
        assert {e.kind for e in linked}=={'TOOL_STARTED','TOOL_COMPLETED'}
        assert all(e.attempt_id==tool.parent_attempt_id for e in linked)
    for attempt in result.attempts:
        for evaluation in attempt.validations:
            assert any(e.evaluation_id==evaluation.evaluation_id and e.attempt_id==attempt.attempt_id for e in events)


def test_readiness_prerequisites_cannot_drift_before_generation(tmp_path):
    req,cl,deps=setup(tmp_path)
    base=deps.environment
    reads=0
    def environment():
        nonlocal reads
        reads+=1
        return base if reads<3 else base.model_copy(update={'durable_retention':False,'required_tool_charge':True})
    result=execute(req,replace(deps,environment=environment),supplied_classification=cl)
    assert result.status=='blocked' and deps.provider.call_count==0


def test_latest_health_blocks_dispatch_after_intent_persisted(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path)
    state={'environment':deps.environment}
    save=deps.repository.save
    def fail_health(task,events,**kwargs):
        result=save(task,events,**kwargs)
        if any(e.kind=='ATTEMPT_STARTED' for e in events):
            env=state['environment']
            state['environment']=env.model_copy(update={'models':{alias:model.model_copy(update={'state':'UNHEALTHY'}) for alias,model in env.models.items()}})
        return result
    monkeypatch.setattr(deps.repository,'save',fail_health)
    result=execute(req,replace(deps,environment=lambda:state['environment']),supplied_classification=cl)
    assert result.status!='succeeded' and deps.provider.call_count==0


def test_readiness_drift_during_tool_intent_write_prevents_tool_dispatch(tmp_path,monkeypatch):
    call=ToolCall(tool='read',operation='read',cost_upper_bound_usd='0')
    tools=MockToolExecutor([])
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,authorized_tools=('read',),tool_calls=(call,)),tools=tools)
    state={'environment':deps.environment}
    save=deps.repository.save
    def alter(task,events,**kwargs):
        result=save(task,events,**kwargs)
        if any(e.kind=='TOOL_STARTED' for e in events):
            state['environment']=state['environment'].model_copy(update={'durable_retention':False})
        return result
    monkeypatch.setattr(deps.repository,'save',alter)
    result=execute(req,replace(deps,environment=lambda:state['environment']),supplied_classification=cl)
    assert result.status=='blocked' and tools.call_count==0


def test_application_identity_is_immutable_in_storage(tmp_path):
    from model_router.core.execution_contracts import ConcurrentUpdate,TaskResult,ExecutionEvent
    req,cl,deps=setup(tmp_path)
    now=deps.clock.now()
    task=TaskResult(task_id='id',trace_id='trace',application_id='a',status='created',policy_version='p',created_at=now,updated_at=now)
    event=ExecutionEvent(event_id='event',task_id='id',trace_id='trace',kind='TASK_CREATED',policy_version='p',occurred_at=now)
    deps.repository.create(task,event,scope='a',key_digest=None,request_digest='digest')
    with pytest.raises(ConcurrentUpdate):
        deps.repository.save(task.model_copy(update={'revision':1,'application_id':'b'}),(),expected_revision=0)


def test_large_finite_budget_does_not_overflow_or_lose_small_spend(tmp_path):
    from model_router.execution.admission import MemoryBudgetAuthority
    from model_router.execution.arithmetic import money_difference
    req,cl,deps=setup(tmp_path)
    ceiling=Decimal('1e1000000')
    env=deps.environment.model_copy(update={'budget':deps.environment.budget.model_copy(update={'task_cost_ceiling_usd':ceiling}),'remaining_usd':ceiling})
    deps=replace(deps,environment=env,limits=deps.limits.model_copy(update={'task_cost_ceiling_usd':ceiling}),
        budget=MemoryBudgetAuthority(default_ceiling=ceiling))
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='succeeded'
    assert money_difference(ceiling,deps.budget.remaining(req.task_id))==result.known_cost_usd


def test_budget_settlement_failure_preserves_paid_attempt_and_stops(tmp_path,monkeypatch):
    req,cl,deps=setup(tmp_path,[success,success])
    def fail(*args):
        raise RuntimeError('private ledger exception')
    monkeypatch.setattr(deps.budget,'settle',fail)
    result=execute(req,deps,supplied_classification=cl)
    assert result.status=='failed' and deps.provider.call_count==1
    assert result.failure.cause_code=='budget_authority_unavailable'
    stored=deps.repository.get(req.task_id)
    assert stored.attempts[0].provider_outcome is not None
    assert stored.attempts[0].actual_cost_usd>0
    assert 'private ledger exception' not in stored.model_dump_json()


def test_validation_guard_retains_earlier_incurred_check_cost(tmp_path):
    calls=[]
    def first(*_):
        calls.append('first')
        state['env']=state['env'].model_copy(update={'durable_retention':False})
        return ValidationOutcome(evaluation_id=str(uuid4()),check='first',status='passed',cost_usd='.2')
    def second(*_):
        calls.append('second')
        return ValidationOutcome(evaluation_id=str(uuid4()),check='second',status='passed')
    req,cl,deps=setup(tmp_path,controls=ExecutionControls(authorized=True,required_checks=('first','second')),
        validator=V0Validator({'first':DeterministicCheck(first,Decimal('.2')),'second':DeterministicCheck(second)}))
    state={'env':deps.environment}
    result=execute(req,replace(deps,environment=lambda:state['env']),supplied_classification=cl)
    assert result.status=='blocked' and calls==['first']
    assert result.known_cost_usd==Decimal('.20014')
    assert result.attempts[0].validations[1].cost_usd==Decimal('.2')
