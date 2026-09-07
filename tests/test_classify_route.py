"""Classifier-only release tests. All provider transport is offline and instrumented."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
import yaml

from model_router.classification import load_classifier_config
from model_router.core.provider_contracts import ProviderFailure, ProviderUsage
from model_router.execution.openai_provider import OpenAIProvider
from model_router.release import activate, load_release, preflight
from model_router.release.runtime import build_app, collect_evidence
from model_router.storage.migrations import migrate_database
from model_router.storage.models import RoutingPreviewRow, BudgetReservationRow, TaskRow, AttemptRow, OutboxRow
from tests.test_phase6_release import _active_release
from tests.test_phase2_classifier import valid_output
from tests.phase3_support import success


def preview_manifest(tmp_path):
    path = _active_release(tmp_path)
    manifest = yaml.safe_load(path.read_text())
    evidence_path = Path(manifest['live']['evidence']['path'])
    evidence = yaml.safe_load(evidence_path.read_text())
    evidence['verified_at'] = datetime.now(UTC).isoformat()
    evidence_path.write_text(yaml.safe_dump(evidence))
    manifest['live']['evidence']['sha256'] = sha256(evidence_path.read_bytes()).hexdigest()
    from model_router.policy.loader import load_bundle
    bundle = load_bundle(manifest['policy']['directory'])
    classifier_path = tmp_path / 'classifier.yaml'
    raw = yaml.safe_load(Path('config/classifier.yaml').read_text())
    raw.update(status='active', live_enabled=True, timeout_ms=10000)
    shutil.copytree('config/prompts', tmp_path / 'prompts')
    classifier_path.write_text(yaml.safe_dump(raw))
    classifier = load_classifier_config(classifier_path, bundle)
    manifest['live']['classifier_config'] = dict(path=str(classifier_path),
        sha256=classifier.configuration_hash, version=classifier.version)
    manifest['operations'].update(classify_route=True, live_classifier=True,
        execute=False, live_provider=False, route=True)
    manifest['auth']['required_scopes'] = ['classify_route', 'read', 'health', 'route']
    manifest['database']['required_migration_revision'] = '0004_routing_previews'
    manifest['limits'].update(application_cost_ceiling_usd='0.05', task_cost_ceiling_usd='0.01', max_preview_records=100)
    path.write_text(yaml.safe_dump(manifest))
    return path


@pytest.fixture
def composed(tmp_path, monkeypatch):
    path = preview_manifest(tmp_path)
    release = load_release(path)
    url = f'sqlite+pysqlite:///{tmp_path / "preview.db"}'
    migrate_database(url, release.config.database.required_migration_revision)
    env = {'MODEL_ROUTER_DATABASE_URL': url, 'APP_TOKEN': 'a'*40, 'OTHER_TOKEN': 'b'*40,
        'ROUTE_TOKEN': 'c'*40, 'RUN_LIVE_OPENAI_TESTS': '1', 'OPENAI_API_KEY': 'present-but-never-called',
        'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON': json.dumps({
            'leo': {'token_env': 'APP_TOKEN', 'scopes': ['classify_route', 'read', 'health', 'route']},
            'other': {'token_env': 'OTHER_TOKEN', 'scopes': ['classify_route']},
            'free': {'token_env': 'ROUTE_TOKEN', 'scopes': ['route']}})}
    journal, receipt = tmp_path/'pending.jsonl', tmp_path/'activation.json'
    activate(release, environment=env, evidence=collect_evidence(release, env, journal), report_path=receipt)
    calls = []
    def stub(self, request):
        calls.append(request)
        return success(request).model_copy(update={'structured_output': request.output_type.model_validate(valid_output()),
            'returned_model_id':request.provider_model_id, 'returned_service_tier':'default'})
    monkeypatch.setattr(OpenAIProvider, 'execute', stub)
    app = build_app(release, receipt, journal, env)
    body = {'request': {'task_id': 'task-1', 'trace_id': 'trace-1', 'input': 'PRIVATE_INPUT_SENTINEL',
        'consequence': 'low', 'requirements': ['text_input', 'text_output'],
        'context': {'input_tokens': 100, 'expected_output_tokens': 64}}, 'idempotency_key': 'PRIVATE_KEY_SENTINEL'}
    yield TestClient(app), app, calls, body, env
    app.applications[0].dependencies.repository.engine.dispose()


def headers(token='a'):
    return {'Authorization': 'Bearer ' + token*40}


def post(c, body, token='a'):
    return c.post('/v1/classify-route', json=body, headers=headers(token))


def test_success_single_call_retained_cost_and_production_exclusion(composed):
    c, app, calls, body, _ = composed
    before = {name:c.get('/v1/telemetry/'+name, headers=headers()).json()
        for name in ('summary','spend','efficacy','routing')}
    result = post(c, body)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['purpose'] == 'classify_route_preview'
    assert value['status'] == 'completed'
    assert value['route']['classification'] == value['classification']
    assert value['route']['selected_model_alias']
    assert value['route']['reasoning_effort']
    assert value['route']['validation_requirements']
    assert value['cost_status'] == 'known' and value['settled']
    assert value['classifier_usage_status'] == 'known'
    assert Decimal(value['actual_cost_usd']) > 0
    assert len(calls) == 1 and calls[0].purpose == 'classification'
    assert calls[0].timeout_ms <= 10000
    duplicate = post(c, body)
    assert duplicate.json() == value and len(calls) == 1
    assert c.get('/v1/previews/'+value['preview_id'],headers=headers()).json() == value
    repo = app.applications[0].dependencies.repository
    with Session(repo.engine) as session:
        rows = session.scalars(select(BudgetReservationRow)).all()
        assert len(rows) == 1 and rows[0].settled
        assert Decimal(rows[0].actual) == Decimal(value['actual_cost_usd'])
        for table in (TaskRow, AttemptRow, OutboxRow):
            assert session.scalar(select(func.count()).select_from(table)) == 0
        persisted = session.scalar(select(RoutingPreviewRow)).payload_json
        assert 'PRIVATE_INPUT_SENTINEL' not in persisted
        assert 'PRIVATE_KEY_SENTINEL' not in persisted
        assert 'private output' not in persisted
    for name, previous in before.items():
        after = c.get('/v1/telemetry/'+name, headers=headers()).json()
        after.pop('meta',None); previous.pop('meta',None)
        assert after == previous
    assert not repo.journal_path.exists()


def test_auth_scopes_and_legacy_route_remain_free(composed):
    c, app, calls, body, _ = composed
    assert c.post('/v1/classify-route', json=body).status_code == 401
    assert post(c, body, 'c').status_code == 403
    assert c.post('/v1/execute',json=body,headers=headers()).status_code == 403
    assert c.post('/v1/route',json={'request':body['request']},headers=headers('c')).status_code == 422
    classification = {'task_family':'transform','confidence':1.,'provenance':'supplied',
        'components':{key:0 for key in app.applications[0].dependencies.bundle.policy['complexity']['components']}}
    assert c.post('/v1/route',json={'request':body['request'],'classification':classification},
        headers=headers('c')).status_code == 200
    assert calls == []
    from model_router.service import create_app
    public = TestClient(create_app(app.applications[0].dependencies))
    assert public.post('/v1/classify-route',json=body).status_code == 401


def test_isolation_and_identity_spoofing(composed):
    c, _, calls, body, _ = composed
    value = post(c, body).json()
    assert c.get('/v1/previews/'+value['preview_id'],headers=headers('b')).status_code == 404
    other = post(c, body, 'b')
    assert other.status_code == 200, other.text
    assert other.json()['application_id'] == 'other'
    assert other.json()['preview_id'] != value['preview_id'] and len(calls) == 2
    forged = {**body,'request':{**body['request'],'application_id':'other'}}
    assert post(c,forged).status_code == 422
    assert len(calls) == 2


@pytest.mark.parametrize('mutation', ['input','context','requirements','key','missing_key','blank_key','environment','classification'])
def test_conflicts_and_invalid_input_never_dispatch_again(composed, mutation):
    c, _, calls, body, _ = composed
    assert post(c,body).status_code == 200
    changed = json.loads(json.dumps(body))
    if mutation == 'input': changed['request']['input'] = 'changed'
    elif mutation == 'context': changed['request']['context']['input_tokens'] = 101
    elif mutation == 'requirements': changed['request']['requirements'].append('image_input')
    elif mutation == 'key': changed['idempotency_key'] = 'new-key-same-task'
    elif mutation == 'missing_key': changed.pop('idempotency_key')
    elif mutation == 'blank_key': changed['idempotency_key'] = '  '
    else: changed[mutation] = {}
    assert post(c,changed).status_code in (409,422)
    assert len(calls) == 1


def test_unknown_cost_holds_reservation_and_does_not_replay(composed,monkeypatch):
    c, app, calls, body, _ = composed
    def unknown(self, request):
        calls.append(request)
        return success(request).model_copy(update={'usage':ProviderUsage(),
            'returned_model_id':request.provider_model_id,'returned_service_tier':'default'})
    monkeypatch.setattr(OpenAIProvider,'execute',unknown)
    response = post(c,body)
    assert response.status_code == 409,response.text
    value = response.json()
    assert value['cause_code'] == 'classifier_cost_unknown'
    assert value['actual_cost_usd'] is None and not value['settled']
    assert value['classifier_usage_status'] == 'unavailable'
    assert Decimal(value['reserved_cost_usd']) > 0
    assert post(c,body).json() == value and len(calls) == 1
    with Session(app.applications[0].dependencies.repository.engine) as session:
        row = session.scalar(select(BudgetReservationRow))
        assert not row.settled and row.actual is None


@pytest.mark.parametrize('mode',['timeout','exception','malformed','refusal'])
def test_failure_normalization(composed,monkeypatch,mode):
    c, _, calls, body, _ = composed
    def failure(self, request):
        calls.append(request)
        if mode == 'exception': raise RuntimeError('PRIVATE_EXCEPTION_SENTINEL')
        if mode == 'timeout':
            return ProviderFailure(**success(request).model_copy(update={
                'returned_model_id':request.provider_model_id,'returned_service_tier':'default'}).model_dump(exclude={'outcome','incomplete_reason','refused'}),
                failure_type='TIMEOUT',source='provider',stage='invocation',cause_code='provider_timeout')
        return success(request).model_copy(update={'refused': mode == 'refusal',
            'returned_model_id':request.provider_model_id,'returned_service_tier':'default'})
    monkeypatch.setattr(OpenAIProvider,'execute',failure)
    response = post(c,body)
    assert response.status_code in (409,422),response.text
    assert 'PRIVATE_EXCEPTION_SENTINEL' not in response.text
    assert response.json()['route'] is None
    assert len(calls) == 1
    assert post(c,body).json() == response.json() and len(calls) == 1


def test_route_rejection_retains_paid_classification(composed):
    c, _, calls, body, _ = composed
    body['request']['requirements'] = ['not-a-capability']
    response = post(c,body)
    assert response.status_code == 200,response.text
    assert response.json()['route']['routing_result'] == 'rejected'
    assert response.json()['classification'] and response.json()['settled']
    assert len(calls) == 1


def test_concurrent_duplicate_claims_only_dispatch_once(composed):
    c, _, calls, body, _ = composed
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _:post(c,body),range(4)))
    assert all(r.status_code in (200,409) for r in responses)
    assert len(calls) == 1
    assert post(c,body).status_code == 200


def test_budget_and_size_admission_precede_dispatch(composed):
    c, app, calls, body, _ = composed
    body['request']['constraints'] = {'task_cost_ceiling_usd':'0.00000001'}
    result = post(c,body)
    assert result.json()['cause_code'] == 'classifier_budget_exhausted'
    assert not calls
    body['request'].update(task_id='oversize',input='x'*50000)
    body['idempotency_key']='oversize'
    body['request'].pop('constraints')
    assert post(c,body).status_code == 413
    assert not calls


def test_started_crash_survives_restart_and_never_replays(composed,monkeypatch):
    c, app, calls, body, env = composed
    from model_router.core.execution_contracts import RepositoryUnavailable
    preview = app.applications[0].preview
    save = preview.repository.save
    def fail_on_result(previous,current):
        if current.status == 'accounted': raise RepositoryUnavailable('safe')
        return save(previous,current)
    monkeypatch.setattr(preview.repository,'save',fail_on_result)
    assert post(c,body).status_code == 503
    assert len(calls) == 1
    # A new service/repository sees the durable started intent and held funds.
    repo = app.applications[0].dependencies.repository
    restarted = build_app(app.release,repo.journal_path.parent/'activation.json',repo.journal_path,env)
    response = post(TestClient(restarted),body)
    assert response.status_code == 409
    assert response.json()['status'] == 'started' and len(calls) == 1
    assert response.json()['actual_cost_usd'] is None
    restarted.applications[0].dependencies.repository.engine.dispose()


def test_release_opt_in_and_fresh_evidence_required(composed):
    _, app, calls, _, env = composed
    facts = collect_evidence(app.release,env,app.applications[0].dependencies.repository.journal_path)
    missing = {k:v for k,v in env.items() if k != 'RUN_LIVE_OPENAI_TESTS'}
    assert 'live_runtime_opt_in' in preflight(app.release,environment=missing,evidence=facts).blockers
    assert 'live_credential_evidence' in preflight(app.release,environment={**env,'OPENAI_API_KEY':'changed'},evidence=facts).blockers
    assert not calls


def test_leo_example_and_composer_disable_generation(tmp_path):
    from model_router.release.schema import ReleaseConfig
    from model_router.release.loader import ReleaseConfigurationError
    from scripts.compose_leo_preview import compose
    example = ReleaseConfig.model_validate(yaml.safe_load(Path('config/releases/leo-shadow-v1.yaml').read_text()))
    assert example.operations.classify_route and example.operations.live_classifier
    assert not example.operations.execute and not example.operations.live_provider
    assert set(example.auth.required_scopes) == {'classify_route','health'}
    assert example.limits.application_cost_ceiling_usd == Decimal('0.05')
    with pytest.raises(ReleaseConfigurationError):
        load_release('config/releases/leo-shadow-v1.yaml')
    source = preview_manifest(tmp_path)
    destination = tmp_path/'leo.yaml'
    built = compose(source,destination)
    assert built.policy_bundle.content_hash == load_release(source).policy_bundle.content_hash
    assert not built.config.operations.execute and not built.config.operations.live_provider
    assert set(built.config.auth.required_scopes) == {'classify_route','health'}
    assert built.config.live.evidence == load_release(source).config.live.evidence
    with pytest.raises(FileExistsError): compose(source,destination)


def test_preview_has_no_generation_tools_evaluators_shadow_or_recovery(composed,monkeypatch):
    import model_router.execution.orchestrator as orchestrator
    import model_router.execution.verification as verification
    c, app, calls, body, _ = composed
    def forbidden(*args,**kwargs):
        pytest.fail('preview entered task execution or validation')
    monkeypatch.setattr(orchestrator,'execute',forbidden)
    monkeypatch.setattr(orchestrator._Execution,'run',forbidden)
    monkeypatch.setattr(orchestrator,'choose_recovery',forbidden)
    monkeypatch.setattr(orchestrator.V0Validator,'validate',forbidden)
    # The preview dependency type contains none of these execution ports.
    assert not {'tools','semantic','shadow','validator','provider'} & set(app.applications[0].preview.__dataclass_fields__)
    response = post(c,body)
    assert response.status_code == 200,response.text
    assert len(calls) == 1 and calls[0].purpose == 'classification'


def test_finite_application_allocation_enforced_and_intent_precedes_call(composed,monkeypatch):
    c, app, calls, body, _ = composed
    preview = app.applications[0].preview
    budget = preview.budget
    from model_router.storage.budget import SQLBudgetAuthority
    identity = 'preexisting-preview-spend'
    assert budget.reserve(identity,identity,Decimal('0.01'))
    # Consume the finite application allowance across unrelated task identities.
    for index in range(4):
        key = 'preexisting-'+str(index)
        assert budget.reserve(key,key,Decimal('0.01'))
    assert post(c,body).json()['cause_code'] == 'classifier_budget_exhausted'
    assert calls == []


def test_accounting_is_durable_before_settlement(composed,monkeypatch):
    c, app, calls, body, _ = composed
    preview = app.applications[0].preview
    original = preview.budget.settle
    def settle(task,action,actual):
        retained = preview.repository.get(task,'leo')
        assert retained.status == 'accounted'
        assert retained.actual_cost_usd == actual
        assert retained.classifier_evidence.usage.input_tokens == 10
        original(task,action,actual)
    monkeypatch.setattr(preview.budget,'settle',settle)
    transport = OpenAIProvider.execute
    def dispatch(self,request):
        with Session(preview.repository.repository.engine) as session:
            row = session.scalar(select(RoutingPreviewRow))
            retained = json.loads(row.payload_json)
            assert retained['status'] == 'started'
            reservation = session.scalar(select(BudgetReservationRow))
            assert not reservation.settled and Decimal(reservation.reserved) > 0
        return transport(self,request)
    monkeypatch.setattr(OpenAIProvider,'execute',dispatch)
    assert post(c,body).status_code == 200
    assert len(calls) == 1


def test_historical_manifest_hash_is_unchanged():
    assert load_release('config/releases/route-only-v1.yaml').release_sha256 == 'cb49d015db4fc51ad3bf7b8b9e8d937e1b3e319c5b4b05185d5140d9a3207a01'


@pytest.mark.parametrize('field,value',[('returned_model_id','different-model'),
    ('returned_model_id',None),('returned_service_tier','priority'),('returned_service_tier',None)])
def test_unverified_returned_tariff_holds_reservation(composed,monkeypatch,field,value):
    c, app, calls, body, _ = composed
    original = OpenAIProvider.execute
    def mismatch(self,request):
        return original(self,request).model_copy(update={field:value})
    monkeypatch.setattr(OpenAIProvider,'execute',mismatch)
    response = post(c,body)
    assert response.status_code == 409,response.text
    result = response.json()
    assert result['cause_code'] == 'classifier_tariff_unknown'
    assert result['actual_cost_usd'] is None and not result['settled']
    assert result['classifier_evidence']['usage']['input_tokens'] == 10
    assert result['route'] is None
    assert post(c,body).json() == result and len(calls) == 1


def test_stale_policy_rejected_without_claim_or_spend(composed):
    c, app, calls, body, _ = composed
    body['request']['policy_version']='old-policy'
    response=post(c,body)
    assert response.status_code == 422 and response.json()['code']=='policy_version_mismatch'
    with Session(app.applications[0].dependencies.repository.engine) as session:
        for table in (RoutingPreviewRow,BudgetReservationRow):
            assert session.scalar(select(func.count()).select_from(table)) == 0
    assert not calls


def test_transport_bounds_correlation_ids_and_streamed_bodies(composed):
    c, app, calls, body, _ = composed
    body['request']['task_id']='x'*20000
    assert post(c,body).status_code == 413
    with Session(app.applications[0].dependencies.repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(RoutingPreviewRow)) == 0
    payload=json.dumps(body).encode()
    assert c.post('/v1/classify-route',content=iter([payload[:9000],payload[9000:]]),
        headers={**headers(),'Content-Type':'application/json'}).status_code == 413
    assert not calls


def test_finite_record_allocation_rejects_free_disk_growth_and_retains_duplicates(composed,monkeypatch):
    c, app, calls, body, _ = composed
    preview = app.applications[0].preview
    monkeypatch.setattr(preview.repository,'max_records',2)
    body['request']['constraints']={'task_cost_ceiling_usd':'0.00000001'}
    first = post(c,body)
    assert first.status_code == 422
    second = {**body,'idempotency_key':'second','request':{**body['request'],'task_id':'second'}}
    assert post(c,second).status_code == 422
    third = {**body,'idempotency_key':'third','request':{**body['request'],'task_id':'third'}}
    assert post(c,third).status_code == 429
    assert post(c,body).json() == first.json()
    with Session(preview.repository.repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(RoutingPreviewRow)) == 2
    assert not calls


def test_paid_classifier_and_exact_activation_evidence_are_explicit(composed):
    c, app, calls, body, _ = composed
    readiness=c.get('/health/ready',headers=headers()).json()
    assert readiness['paid_classifier_enabled'] is True
    assert readiness['live_execution_enabled'] is False
    body['request']['constraints']={'task_cost_ceiling_usd':'0.00000001'}
    result=post(c,body).json()
    assert result['release_sha256']==app.release.release_sha256
    assert result['activation_id'].startswith('activation-')
    assert result['account_evidence_id']==app.release.live_evidence.evidence_id
    assert not calls


@pytest.mark.parametrize('tier,expected',[('default','default'),('priority','priority'),
    (None,None),('PRIVATE_TIER_SENTINEL',None)])
def test_real_adapter_retains_sanitized_returned_tariff(tier,expected):
    from tests.test_phase2_provider import Client, Responses, response, request
    from model_router.policy.loader import load_bundle
    bundle=load_bundle('config')
    provider=OpenAIProvider(bundle,client=Client(Responses(response=response(service_tier=tier))))
    result=provider.execute(request(bundle))
    assert result.returned_model_id=='gpt-5.6-luna'
    assert result.returned_service_tier==expected
    assert 'PRIVATE_TIER_SENTINEL' not in result.model_dump_json()


def test_preview_ingress_timeout_releases_concurrency_without_dispatch(composed,monkeypatch):
    import asyncio
    import model_router.service.auth as auth
    _, app, calls, _, _ = composed
    configured=[]
    def short_timeout(seconds):
        configured.append(seconds)
        return asyncio.timeout(.001)
    monkeypatch.setattr(auth,'timeout',short_timeout)
    messages=[]
    async def scenario():
        async def receive():
            await asyncio.sleep(.05)
            return {'type':'http.request','body':b'{}','more_body':False}
        async def send(message): messages.append(message)
        await app({'type':'http','path':'/v1/classify-route','method':'POST',
            'headers':[(b'authorization',('Bearer '+'a'*40).encode())]},receive,send)
    asyncio.run(scenario())
    assert configured == [app.applications[0].preview.deadline_ms/1000]
    assert messages[0]['status']==408 and not calls
    assert app.slots.acquire(blocking=False)
    app.slots.release()


@pytest.mark.parametrize('kind,status',[('http.disconnect',None),('invalid.message',400)])
def test_preview_ingress_disconnect_or_invalid_event_never_claims(composed,kind,status):
    import asyncio
    _, app, calls, _, _ = composed
    messages=[]
    async def scenario():
        async def receive(): return {'type':kind}
        async def send(message): messages.append(message)
        await app({'type':'http','path':'/v1/classify-route','method':'POST',
            'headers':[(b'authorization',('Bearer '+'a'*40).encode())]},receive,send)
    asyncio.run(scenario())
    assert not calls
    assert (messages[0]['status'] if messages else None) == status
    with Session(app.applications[0].dependencies.repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(RoutingPreviewRow)) == 0
