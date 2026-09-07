"""Real Phase 4 execution, accounting, recovery and durable evidence regressions."""
from dataclasses import replace
from decimal import Decimal
import pytest
from sqlalchemy import select
from phase3_support import setup, success
from model_router.core.contracts import FailureType
from model_router.core.execution_contracts import ValidationOutcome, TaskStatus, ConcurrentUpdate
from model_router.core.provider_contracts import ProviderFailure, ProviderUsage
from model_router.execution import execute
from model_router.execution.provider import request_evidence
from model_router.policy.phase4 import load_phase4
from model_router.validation.semantic import ValidationService, MockEvaluator, MockDomainValidator, EvaluatorScore
from model_router.storage.models import VerificationEvidenceRow
from model_router.storage import SQLiteTaskRepository


def score(value):
    def call(request):
        return success(request).model_copy(update={'text': None, 'structured_output': EvaluatorScore(score=value)})
    return call


def timeout(request):
    return ProviderFailure(**request_evidence(request), failure_type=FailureType.TIMEOUT,
        source='provider', stage='invocation', cause_code='timeout', retryable=True,
        usage=ProviderUsage(input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
            output_tokens=0, reasoning_tokens=0, total_tokens=0))


def configured(tmp_path, evaluations, *, consequence='moderate', generations=None, domain=None):
    request, classification, deps = setup(tmp_path, outcomes=generations)
    config = load_phase4('config/phase4.yaml', deps.bundle)
    if domain:
        config = config.model_copy(update={'domain_validator_ref': 'mock-domain'})
    semantic = ValidationService(config, MockEvaluator(evaluations), deps.bundle,
        {'mock-domain': domain} if domain else None)
    deps = replace(deps, semantic=semantic)
    request = request.model_copy(update={'consequence': consequence,
        'approval_evidence': consequence in ('high','critical'), 'domain_clearance_evidence': consequence == 'critical'})
    return request, classification, deps


@pytest.mark.parametrize('level,consequence', [('V1','moderate'), ('V2','high')])
def test_required_evaluator_executes_independently_and_costs_once(tmp_path, level, consequence):
    request, classification, deps = configured(tmp_path, [score(1.0)], consequence=consequence)
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED
    assert result.initial_decision.validation_level == level
    assert deps.provider.call_count == deps.semantic.provider.call_count == 1
    generation, evaluator = result.attempts[0], result.evaluator_attempts[0]
    assert evaluator.attempt_id != generation.attempt_id
    assert evaluator.parent_attempt_id == generation.attempt_id
    assert evaluator.provider_outcome.purpose == 'evaluation'
    assert result.total_cost_usd == generation.actual_cost_usd + evaluator.actual_cost_usd
    assert result.production_generation_cost_usd == generation.actual_cost_usd
    assert result.production_validation_cost_usd == evaluator.actual_cost_usd
    assert result.output == 'private output'
    stored = deps.repository.get(result.task_id)
    assert stored.output is None and stored.evaluator_attempts[0].validations[0].score == 1.0
    assert 'private output' not in stored.model_dump_json() and 'private prompt' not in stored.model_dump_json()


def test_evaluator_timeout_retries_evaluator_without_regeneration(tmp_path):
    request, classification, deps = configured(tmp_path, [timeout, score(1.0)])
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED
    assert len(result.attempts) == deps.provider.call_count == 1
    assert len(result.evaluator_attempts) == 2
    assert result.evaluator_attempts[0].failure.source == 'evaluator'
    assert result.evaluator_attempts[0].failure.failure_type == FailureType.TIMEOUT
    assert result.evaluator_attempts[-1].validations[0].status == 'passed'
    assert result.recovery_actions[0].action == 'retry_evaluator'
    assert result.counters.infrastructure_retries == result.counters.quality_escalations == 0
    assert result.total_cost_usd == sum(a.actual_cost_usd for a in (*result.attempts,*result.evaluator_attempts))


def test_evaluator_retry_exhaustion_never_promotes_generation(tmp_path):
    request, classification, deps = configured(tmp_path, [timeout, timeout, score(1.0)])
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.FAILED
    assert result.failure.source == 'evaluator' and result.failure.failure_type == FailureType.TIMEOUT
    assert deps.provider.call_count == 1 and deps.semantic.provider.call_count == 2
    assert result.counters.quality_escalations == 0
    assert result.output is None


def test_semantic_quality_failure_can_recover_generation(tmp_path):
    request, classification, deps = configured(tmp_path, [score(0.1), score(1.0)], generations=[success, success])
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED
    assert len(result.attempts) == len(result.evaluator_attempts) == 2
    assert result.recovery_actions[0].action == 'increase_effort'
    assert result.evaluator_attempts[0].validations[0].failure.failure_type == FailureType.QUALITY_FAILURE
    assert result.attempts[0].provider_outcome.text == 'private output'


def test_v3_missing_blocks_and_mock_domain_passes(tmp_path):
    request, classification, deps = configured(tmp_path, [], consequence='critical')
    blocked = execute(request, deps, supplied_classification=classification)
    assert blocked.status == TaskStatus.BLOCKED and deps.provider.call_count == 0
    child = tmp_path/'other'; child.mkdir()
    domain = MockDomainValidator([ValidationOutcome(evaluation_id='domain-1',check='mock-domain',status='passed')])
    request, classification, deps = configured(child, [], consequence='critical', domain=domain)
    passed = execute(request, deps, supplied_classification=classification)
    assert passed.status == TaskStatus.SUCCEEDED
    assert len(passed.domain_validations) == 1 and domain.call_count == 1
    assert deps.semantic.provider.call_count == 0


def test_missing_required_evaluator_and_v0_hook_never_downgrade(tmp_path):
    request, classification, deps = configured(tmp_path, [])
    missing = deps.semantic.config.model_copy(update={'evaluators': ()})
    deps = replace(deps, semantic=ValidationService(missing, MockEvaluator([]), deps.bundle))
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.BLOCKED and deps.provider.call_count == 0
    child=tmp_path/'hook';child.mkdir()
    request, classification, deps = configured(child, [score(1.0)])
    deps=replace(deps,controls=deps.controls.model_copy(update={'required_checks':('missing',)}))
    result=execute(request,deps,supplied_classification=classification)
    assert result.status == TaskStatus.BLOCKED and deps.provider.call_count == 0


def test_v0_does_not_run_evaluator_and_high_consequence_simple_keeps_tier(tmp_path):
    request, classification, deps = configured(tmp_path, [], consequence='low')
    result = execute(request, deps, supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED and not result.evaluator_attempts
    child=tmp_path/'high';child.mkdir()
    request, classification, deps = configured(child, [score(1.0)], consequence='high')
    classification=classification.model_copy(update={'components': type(classification.components)(
        reasoning_depth=1,step_dependency=1,context_synthesis=1,technical_precision=1,
        ambiguity=1,tool_orchestration=0,reliability_requirement=1)})
    result=execute(request,deps,supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED
    assert result.initial_decision.selected_model_alias == 'luna'
    assert result.initial_decision.validation_level == 'V2'


def test_restart_keeps_evaluator_and_outbox_evidence_no_replay(tmp_path):
    request, classification, deps = configured(tmp_path, [timeout,score(1.0)])
    result=execute(request,deps,supplied_classification=classification)
    reopened=SQLiteTaskRepository(str(deps.repository.engine.url),journal_path=tmp_path/'journal.jsonl')
    stored=reopened.get(request.task_id)
    assert len(stored.evaluator_attempts)==2
    again=execute(request,replace(deps,repository=reopened),supplied_classification=classification)
    assert again.revision==result.revision and deps.semantic.provider.call_count==2
    with reopened.engine.connect() as connection:
        assert len(connection.execute(select(VerificationEvidenceRow)).all())==2


def healthy(deps, request):
    from model_router.health import HealthService, SyntheticHealthSource
    config=load_phase4('config/phase4.yaml',deps.bundle)
    health=HealthService(deps.clock, config.health)
    SyntheticHealthSource(health).seed(models=deps.bundle.catalog['models'], provider_capabilities=request.requirements)
    if deps.semantic:
        for b in deps.semantic.config.evaluators:
            health.observe('evaluator',model=b.model_alias,success=True)
    return replace(deps,health=health)


def test_real_health_snapshots_persist_and_evaluator_retry_is_scoped(tmp_path):
    request, classification, deps = configured(tmp_path, [timeout,score(1.0)])
    deps=healthy(deps,request)
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED
    assert len(result.evaluator_attempts)==2
    snapshots=deps.repository.get(request.task_id).health_snapshots
    assert snapshots and len({s.snapshot_id for s in snapshots})==len(snapshots)
    assert deps.health.available('provider',model='luna')
    assert all(o.failure_count==0 for o in deps.health.snapshot().observations if o.component=='provider')


def test_stale_health_blocks_before_provider_and_unhealthy_is_excluded(tmp_path):
    request,classification,deps=setup(tmp_path)
    deps=healthy(deps,request)
    deps.clock.sleep(deps.health.config.freshness_ms)
    blocked=execute(request,deps,supplied_classification=classification)
    assert blocked.status==TaskStatus.FAILED and deps.provider.call_count==0
    child=tmp_path/'exclude';child.mkdir()
    request,classification,deps=setup(child)
    deps=healthy(deps,request)
    deps.health.observe('provider',model='terra',state='UNHEALTHY')
    result=execute(request,deps,supplied_classification=classification)
    assert result.initial_decision.selected_model_alias!='terra'
    assert all(r['model_alias']!='terra' for r in deps.provider.requests)


def test_required_evaluator_outage_does_not_fail_v0_task(tmp_path):
    request,classification,deps=setup(tmp_path)
    deps=healthy(deps,request)
    deps.health.observe('evaluator',model='sol',state='UNHEALTHY')
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED


def test_eval_deadline_is_not_extended_by_adapter(tmp_path):
    request,classification,deps=configured(tmp_path,[score(1.0)])
    def slow_generation(call):
        deps.clock.sleep(29500)
        return success(call)
    from model_router.execution.provider import MockProvider
    deps=replace(deps,provider=MockProvider([slow_generation]))
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED
    assert deps.semantic.provider.requests[0]['timeout_ms']==500


def test_evaluator_started_intent_survives_interruption_and_never_replays(tmp_path):
    request,classification,deps=configured(tmp_path,[])
    class Interrupted(BaseException): pass
    def crash(call): raise Interrupted()
    deps=replace(deps,semantic=ValidationService(deps.semantic.config,MockEvaluator([crash]),deps.bundle))
    with pytest.raises(Interrupted):
        execute(request,deps,supplied_classification=classification)
    stored=deps.repository.get(request.task_id)
    assert stored.evaluator_attempts[0].status=='started'
    assert stored.attempts[0].provider_outcome is not None
    again=execute(request,deps,supplied_classification=classification)
    assert again.evaluator_attempts[0].status=='started'
    assert deps.provider.call_count==deps.semantic.provider.call_count==1


def shadow_dependencies(tmp_path, outcomes):
    from test_phase4_shadow import enabled_bundle
    from model_router.shadow import ShadowService
    from model_router.execution.provider import MockProvider
    from model_router.execution.admission import MemoryBudgetAuthority
    request,classification,deps=setup(tmp_path)
    bundle=enabled_bundle()
    shadow=ShadowService(bundle,MockProvider(outcomes),MemoryBudgetAuthority(default_ceiling='10'),deps.clock,privacy_allowed=True)
    return request,classification,replace(deps,bundle=bundle,shadow=shadow)


def test_shadow_failure_keeps_production_output_counters_and_cost(tmp_path):
    request,classification,deps=shadow_dependencies(tmp_path,[timeout])
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED and result.output=='private output'
    assert result.shadow_runs[0].status=='failed'
    assert result.counters.generation_attempts==1 and result.counters.infrastructure_retries==0
    assert result.total_cost_usd==result.attempts[0].actual_cost_usd
    assert result.shadow_runs[0].attempts[0].role=='shadow'


@pytest.mark.parametrize('when',['intent','observed'])
def test_shadow_storage_outage_retains_production_success_in_journal(tmp_path,when):
    from model_router.core.execution_contracts import RepositoryUnavailable
    request,classification,deps=shadow_dependencies(tmp_path,[success])
    save=deps.repository.save
    def failing(task,events,*,expected_revision):
        if task.shadow_runs:
            last=task.shadow_runs[-1].attempts
            if when=='intent' or last and last[-1].provider_outcome is not None:
                raise RepositoryUnavailable('injected storage outage')
        return save(task,events,expected_revision=expected_revision)
    deps.repository.save=failing
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED and result.output=='private output'
    assert deps.shadow.provider.call_count==(0 if when=='intent' else 1)
    assert result.shadow_runs[0].status=='failed'
    assert deps.repository.journal_path.exists()
    deps.repository.save=save
    assert deps.repository.reconcile_pending()>0
    stored=deps.repository.get(request.task_id)
    assert stored.status==TaskStatus.SUCCEEDED
    assert len(stored.shadow_runs)==1
    assert not deps.repository.journal_path.read_text().strip()


def test_decisions_reference_exact_retained_health_snapshot_with_ticking_clock(tmp_path):
    from datetime import timedelta
    request,classification,deps=setup(tmp_path)
    original=deps.clock
    class Tick:
        def now(self):
            original.advance(1)
            return original.now()
        def sleep(self,ms):original.sleep(ms)
    deps=replace(deps,clock=Tick())
    deps=healthy(deps,request)
    result=execute(request,deps,supplied_classification=classification)
    assert result.status==TaskStatus.SUCCEEDED
    snapshots={s.snapshot_id:s for s in deps.repository.get(request.task_id).health_snapshots}
    for decision in result.decisions:
        assert decision.health_snapshot_id in snapshots


def test_unavailable_evaluator_model_blocks_without_generation_tier_jump(tmp_path):
    request,classification,deps=configured(tmp_path,[])
    models=dict(deps.environment.models)
    models['luna']=models['luna'].model_copy(update={'usable':False,'state':'UNHEALTHY'})
    deps=replace(deps,environment=deps.environment.model_copy(update={'models':models}))
    task=execute(request,deps,supplied_classification=classification)
    assert task.status==TaskStatus.BLOCKED and task.failure.cause_code=='required_evaluator_unavailable'
    assert task.initial_decision.selected_model_alias=='terra'
    assert deps.provider.call_count==deps.semantic.provider.call_count==0
