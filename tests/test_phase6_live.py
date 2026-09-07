"""Offline tests of explicit live admission; no provider network transport."""
from dataclasses import replace
from decimal import Decimal
import json

from model_router.core.contracts import EnvironmentSnapshot, thaw
from model_router.core.configuration import bundle_from_documents
from model_router.execution.live import LiveExecutionAuthorization, ReleaseEnvironmentSnapshot
from model_router.execution.orchestrator import execute
from tests.phase3_support import setup, success


def composition(tmp_path, *, check=lambda: True, classifier_factory=None):
    req, classification, deps = setup(tmp_path)
    documents = [json.loads(json.dumps(thaw(getattr(deps.bundle, k)),default=str)) for k in ('catalog','policy','budgets','validation')]
    catalog, policy, budgets, validation = documents
    for doc in documents:
        doc['status'] = 'active'
    budgets['defaults'].update(task_cost_ceiling_usd='1',task_deadline_ms=30000,live_execution_enabled=True)
    policy['escalation']['limits'].update(max_total_generation_attempts=3,max_quality_escalations=2,
        max_infrastructure_retries=1,max_tool_recoveries=0,max_elapsed_ms=30000)
    policy['escalation']['infrastructure']['backoff'].update(initial_ms=1,max_ms=10,jitter=0.0)
    bundle = bundle_from_documents(policy,catalog,budgets,validation)
    env = ReleaseEnvironmentSnapshot.model_validate({'release_version':'test-release',**deps.environment.model_dump(mode='python'),
        'synthetic':False, 'validation':{}, 'recovery_bounded':True})
    live = LiveExecutionAuthorization('test-release',8192,1024,check,classifier_factory)
    return req, classification, replace(deps,bundle=bundle,environment=env,live=live)


def test_disabled_guard_dispatches_nothing(tmp_path):
    req, cls, deps = composition(tmp_path, check=lambda:False)
    result = execute(req,deps,supplied_classification=cls)
    assert result.status == 'blocked'
    assert not deps.provider.requests


def test_guard_failure_is_closed(tmp_path):
    def broken(): raise RuntimeError('sensitive')
    req, cls, deps = composition(tmp_path,check=broken)
    result = execute(req,deps,supplied_classification=cls)
    assert result.status == 'blocked'
    assert 'sensitive' not in result.model_dump_json()


def test_explicit_live_composition_uses_normal_engine(tmp_path):
    req, cls, deps = composition(tmp_path)
    result = execute(req,deps,supplied_classification=cls)
    assert result.status == 'succeeded', result.failure
    assert not result.initial_decision.synthetic
    assert result.known_cost_usd > 0
    assert result.attempts[0].estimated_cost_usd >= Decimal('0.02')
    assert len(deps.provider.requests) == 1


def test_untrusted_input_estimate_cannot_reduce_reservation(tmp_path):
    req, cls, deps = composition(tmp_path)
    req = req.model_copy(update={'context':req.context.model_copy(update={'input_tokens':1})})
    result=execute(req,deps,supplied_classification=cls)
    assert result.status=='succeeded'
    assert result.initial_decision.estimated_cost.generation_subtotal > Decimal('0.01')


def test_oversize_input_does_not_dispatch_or_incur_cost(tmp_path):
    req, cls, deps = composition(tmp_path)
    result=execute(req.model_copy(update={'input':'x'*20000}),deps,supplied_classification=cls)
    assert result.status != 'succeeded'
    assert not deps.provider.requests
    assert result.total_cost_usd == 0


def test_unknown_cost_holds_reservation(tmp_path):
    from model_router.core.provider_contracts import ProviderUsage
    from model_router.execution.provider import MockProvider
    req, cls, deps = composition(tmp_path)
    provider=MockProvider([lambda r:success(r).model_copy(update={'usage':ProviderUsage()})])
    result=execute(req,replace(deps,provider=provider),supplied_classification=cls)
    assert result.total_cost_usd is None
    assert result.reserved_cost_usd > 0


def test_live_refuses_side_effects(tmp_path):
    req, cls, deps = composition(tmp_path)
    result=execute(req.model_copy(update={'side_effecting_tool':True}),deps,supplied_classification=cls)
    assert result.status=='blocked'
    assert not deps.provider.requests


def classifier_composition(tmp_path, *, fail=False):
    from model_router.classification import OpenAIClassifier
    from model_router.execution.provider import MockProvider
    from tests.test_phase2_classifier import enabled_config, valid_output
    req, cls, deps = composition(tmp_path)
    config=enabled_config(tmp_path,deps.bundle)
    factory=lambda provider: OpenAIClassifier(provider,deps.bundle,config)
    def classified(r):
        from model_router.core.provider_contracts import ProviderFailure
        from model_router.execution.provider import request_evidence
        if fail:
            return ProviderFailure(**request_evidence(r),failure_type='TIMEOUT',source='provider',
                stage='invocation',cause_code='timeout')
        return success(r).model_copy(update={'structured_output':r.output_type.model_validate(valid_output())})
    live=replace(deps.live,classifier_factory=factory)
    return req, replace(deps,live=live,provider=MockProvider([classified,success]))


def test_classifier_and_generation_share_durable_budget_and_evidence(tmp_path):
    req,deps=classifier_composition(tmp_path)
    result=execute(req,deps)
    assert result.status=='succeeded',result.failure
    assert [a.purpose for a in result.attempts]==['classification','generation']
    assert result.counters.generation_attempts==1
    assert result.total_cost_usd == sum(a.actual_cost_usd for a in result.attempts)
    persisted=deps.repository.get(req.task_id)
    assert persisted.total_cost_usd==result.total_cost_usd
    assert 'private prompt' not in persisted.model_dump_json()
    assert 'private output' not in persisted.model_dump_json()


def test_failed_classifier_keeps_unknown_cost_and_never_generates(tmp_path):
    req,deps=classifier_composition(tmp_path,fail=True)
    result=execute(req,deps)
    assert result.status=='failed'
    assert len(deps.provider.requests)==1
    assert result.total_cost_usd is None and result.reserved_cost_usd>0
    assert result.attempts[0].purpose=='classification'
    assert deps.repository.get(req.task_id).attempts[0].failure is not None


def test_successful_classifier_without_usage_stops_before_generation(tmp_path):
    from model_router.core.provider_contracts import ProviderUsage
    from model_router.execution.provider import MockProvider
    from tests.test_phase2_classifier import valid_output
    req,deps=classifier_composition(tmp_path)
    provider=MockProvider([lambda r:success(r).model_copy(update={
        'structured_output':r.output_type.model_validate(valid_output()),'usage':ProviderUsage()})])
    result=execute(req,replace(deps,provider=provider))
    assert result.failure.cause_code=='classifier_cost_unknown'
    assert len(provider.requests)==1
    assert result.total_cost_usd is None
    assert result.reserved_cost_usd>0


def test_provider_uses_explicit_release_credential(monkeypatch):
    from model_router.execution.openai_provider import OpenAIProvider
    from model_router.policy.loader import load_bundle
    import openai
    captured={}
    def client(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setenv('RUN_LIVE_OPENAI_TESTS','1')
    monkeypatch.setenv('OPENAI_API_KEY','different-account-key')
    monkeypatch.setattr(openai,'OpenAI',client)
    OpenAIProvider(load_bundle('config'),api_key='configured-release-key')._base_client()
    assert captured=={'api_key':'configured-release-key','max_retries':0}


def test_canary_opt_in_and_cap_are_checked_before_composition(tmp_path,monkeypatch):
    import pytest
    from model_router.release.live import CanaryBlocked,run_canaries
    from model_router.release import load_release
    release=load_release('config/releases/route-only-v1.yaml')
    args=(release,tmp_path/'missing-activation',tmp_path/'journal',tmp_path/'report')
    with pytest.raises(CanaryBlocked,match='opt-in'):
        run_canaries(*args,application_id='app',max_total_cost_usd='1')
    monkeypatch.setenv('RUN_LIVE_OPENAI_TESTS','1')
    with pytest.raises(CanaryBlocked,match='allocation'):
        run_canaries(*args,application_id='app',max_total_cost_usd='1',run_paid=True)
    with pytest.raises(CanaryBlocked,match='enabled'):
        run_canaries(*args,application_id='app',max_total_cost_usd='10',run_paid=True)
    assert not (tmp_path/'report').exists()


def test_durable_allocation_callback_is_scoped_and_fail_closed():
    seen=[]
    guard=LiveExecutionAuthorization('release',8192,1024,lambda:True,
        durable_allocation_verified=lambda task_id:seen.append(task_id) or True)
    assert guard.allocation_ready('actual-task-id')
    assert seen==['actual-task-id']
    def unavailable(_): raise RuntimeError('sensitive')
    assert not replace(guard,durable_allocation_verified=unavailable).allocation_ready('actual-task-id')


def test_live_known_infrastructure_failure_retries_without_intelligence_escalation(tmp_path):
    from model_router.core.provider_contracts import ProviderFailure
    from model_router.execution.provider import MockProvider,request_evidence
    req,cls,deps=composition(tmp_path)
    def timed_out(request):
        return ProviderFailure(**request_evidence(request),failure_type='TIMEOUT',source='provider',
            stage='invocation',cause_code='timeout',retryable=True,usage=success(request).usage)
    provider=MockProvider([timed_out,success])
    result=execute(req,replace(deps,provider=provider),supplied_classification=cls)
    assert result.status=='succeeded',result.failure
    assert len(provider.requests)==2
    assert len({(r['model_alias'],r['reasoning_effort']) for r in provider.requests})==1
    assert result.counters.quality_escalations==0
    assert result.total_cost_usd==sum(a.actual_cost_usd for a in result.attempts)


def test_predispatch_refusal_does_not_inflate_provider_call_metrics(tmp_path):
    from datetime import timedelta
    from model_router.telemetry.analytics import Analytics
    req,cls,deps=composition(tmp_path)
    task=execute(req.model_copy(update={'input':'x'*20000}),deps,supplied_classification=cls)
    assert not deps.provider.requests
    analytics=Analytics((task,),(),now=deps.clock.now()+timedelta(seconds=1),filters={},synthetic=False)
    assert analytics.summary()['metrics']['infrastructure_retry_rate']['denominator']==0
    assert analytics.spend()['by_purpose']==[]
