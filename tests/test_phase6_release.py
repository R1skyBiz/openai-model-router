from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
import yaml
from pydantic import ValidationError

from model_router.policy.loader import load_bundle
from model_router.release import (
    ActivationBlocked,
    ReleaseConfigurationError,
    RuntimeEvidence,
    activate,
    load_release,
    parse_application_credentials,
    preflight,
)
from model_router.release.runtime import collect_evidence
from model_router.storage.migrations import migrate_database


MANIFEST = Path("config/releases/route-only-v1.yaml")
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _runtime(*, live: bool = False) -> RuntimeEvidence:
    components = ["configuration", "database", "telemetry"]
    if live:
        components.extend(
            ["provider:luna", "provider:terra", "provider:sol", "provider:astra"]
        )
    return RuntimeEvidence(
        database_reachable=True,
        database_dialect="sqlite",
        database_revision="0003_phase6_durable_storage",
        outbox_ready=True,
        health_ready=True,
        health_config_version="health-offline-v1",
        health_observed_at=NOW,
        healthy_components=tuple(components),
    )


def test_route_only_release_loads_without_activation_and_is_deeply_immutable():
    release = load_release(MANIFEST)
    assert release.config.release_id == "route-only-v1.0.0"
    assert release.config.operations.route is True
    assert release.config.operations.execute is False
    assert release.policy_bundle.policy["status"] == "draft"
    with pytest.raises((TypeError, ValidationError)):
        release.config.manifest = {}  # type: ignore[attr-defined]


def test_loader_rejects_unknown_duplicate_and_changed_policy_references(tmp_path: Path):
    original = MANIFEST.read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(original + "\nunknown_field: true\n", encoding="utf-8")
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(original + "\nrelease_id: duplicate\n", encoding="utf-8")
    changed = tmp_path / "changed.yaml"
    changed.write_text(
        original.replace(
            "86488ba0335650081aea550bf5551e2b777498fcab1143685b6fb5cc637dec0b",
            "0" * 64,
        ),
        encoding="utf-8",
    )
    for path in (unknown, duplicate, changed):
        with pytest.raises(ReleaseConfigurationError):
            load_release(path)


def test_route_only_preflight_fails_closed_and_never_requires_openai_key():
    release = load_release(MANIFEST)
    result = preflight(release, environment={}, evidence=RuntimeEvidence(), now=NOW)
    assert result.ready is False
    assert set(result.blockers) >= {
        "auth_credentials",
        "database_url",
        "database_connectivity",
        "database_migration",
        "outbox",
        "health",
    }
    assert "provider_credentials" not in {check.name for check in result.checks}
    assert next(check for check in result.checks if check.name == "live_execution").passed


def test_route_only_activation_records_exact_scope_and_cannot_overwrite(tmp_path: Path):
    release = load_release(MANIFEST)
    destination = tmp_path / "activation.json"
    report = activate(
        release,
        environment={
            "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(
                {"app": {"token_env": "APP_TOKEN", "scopes": ["route", "read", "health"]}}
            ),
            "APP_TOKEN": "a" * 32,
            "MODEL_ROUTER_DATABASE_URL": "sqlite:///ignored-and-never-reported.db",
        },
        evidence=_runtime(),
        report_path=destination,
        now=NOW,
    )
    assert report.enabled_operations == ("route", "read", "health")
    assert report.live_execution_enabled is False
    assert "provider execution disabled" in report.operation_scope
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted["release_sha256"] == release.release_sha256
    assert "sqlite:///ignored-and-never-reported.db" not in destination.read_text()
    with pytest.raises(FileExistsError):
        activate(
            release,
            environment={
                "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(
                    {"app": {"token_env": "APP_TOKEN", "scopes": ["route", "read", "health"]}}
                ),
                "APP_TOKEN": "b" * 32,
                "MODEL_ROUTER_DATABASE_URL": "present",
            },
            evidence=_runtime(),
            report_path=destination,
            now=NOW,
        )


def _active_release(tmp_path: Path) -> Path:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    for name in ("routing-policy.yaml", "models.yaml", "budgets.yaml", "validation.yaml"):
        shutil.copy(Path("config") / name, policy_dir / name)

    policy_path = policy_dir / "routing-policy.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    policy["status"] = "active"
    policy["escalation"]["limits"].update(
        max_total_generation_attempts=3,
        max_quality_escalations=1,
        max_infrastructure_retries=1,
        max_tool_recoveries=0,
        max_elapsed_ms=60000,
    )
    policy["escalation"]["infrastructure"]["backoff"].update(
        initial_ms=100, max_ms=2000, jitter=0.0
    )
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False))

    models_path = policy_dir / "models.yaml"
    models = yaml.safe_load(models_path.read_text())
    models["status"] = "active"
    models["verification"]["live_account_probe_performed"] = True
    for model in models["models"].values():
        model["availability"]["account_status"] = "verified"
        model["pricing"]["status"] = "verified"
    models_path.write_text(yaml.safe_dump(models, sort_keys=False))

    budgets_path = policy_dir / "budgets.yaml"
    budgets = yaml.safe_load(budgets_path.read_text())
    budgets["status"] = "active"
    budgets["defaults"].update(
        task_cost_ceiling_usd="1.00",
        task_deadline_ms=60000,
        period_spend_ceiling_usd="10.00",
        period="day",
        live_execution_enabled=True,
    )
    budgets_path.write_text(yaml.safe_dump(budgets, sort_keys=False))

    validation_path = policy_dir / "validation.yaml"
    validation = yaml.safe_load(validation_path.read_text())
    validation["status"] = "active"
    validation_path.write_text(yaml.safe_dump(validation, sort_keys=False))
    bundle = load_bundle(policy_dir)

    evidence = {
        "credential_sha256": sha256(b"present-but-never-called").hexdigest(),
        "schema_version": 1,
        "evidence_id": "live-proof-v1",
        "provider": "openai",
        "verified_at": NOW.isoformat(),
        "account_access_verified": True,
        "pricing_verified": True,
        "models": {
            alias: {
                "provider_model_id": model["provider_model_id"],
                "access_verified": True,
                "pricing_version": model["pricing"]["version"],
                "input_usd": str(model["pricing"]["input_usd"]),
                "cached_input_usd": str(model["pricing"]["cached_input_usd"]),
                "output_usd": str(model["pricing"]["output_usd"]),
                "cache_write_input_multiplier": str(
                    model["pricing"]["cache_write_input_multiplier"]
                ),
                "reasoning_efforts": model["reasoning_efforts"],
                "source_url": model["source_url"],
            }
            for alias, model in models["models"].items()
        },
    }
    evidence_path = tmp_path / "live-evidence.yaml"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False))

    manifest = yaml.safe_load(MANIFEST.read_text())
    manifest["release_id"] = "live-test-v1"
    manifest["policy"]["directory"] = str(policy_dir)
    manifest["policy"]["content_sha256"] = bundle.content_hash
    manifest["operations"].update(execute=True, live_provider=True)
    manifest["auth"]["required_scopes"].append("execute")
    manifest["live"]["evidence"] = {
        "path": str(evidence_path),
        "sha256": sha256(evidence_path.read_bytes()).hexdigest(),
        "version": "live-proof-v1",
    }
    manifest_path = tmp_path / "release.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return manifest_path


def test_live_preflight_requires_current_exact_evidence_and_provider_health(tmp_path: Path):
    release = load_release(_active_release(tmp_path))
    environment = {
        "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(
            {
                "live-app": {
                    "token_env": "LIVE_APP_TOKEN",
                    "scopes": ["route", "read", "health", "execute"],
                }
            }
        ),
        "LIVE_APP_TOKEN": "c" * 32,
        "MODEL_ROUTER_DATABASE_URL": "present",
        "OPENAI_API_KEY": "present-but-never-called",
        "RUN_LIVE_OPENAI_TESTS": "1",
    }
    ready = preflight(release, environment=environment, evidence=_runtime(live=True), now=NOW)
    assert ready.ready
    rotated=preflight(release,environment={**environment,'OPENAI_API_KEY':'different-account-key'},evidence=_runtime(live=True),now=NOW)
    assert not rotated.ready and 'live_credential_evidence' in rotated.blockers
    without_opt_in = preflight(release, environment={k:v for k,v in environment.items() if k != 'RUN_LIVE_OPENAI_TESTS'}, evidence=_runtime(live=True), now=NOW)
    assert not without_opt_in.ready
    assert 'live_runtime_opt_in' in without_opt_in.blockers

    stale = preflight(
        release,
        environment=environment,
        evidence=_runtime(live=True),
        now=NOW + timedelta(hours=25),
    )
    assert not stale.ready
    assert "live_evidence_freshness" in stale.blockers
    assert "live_health_evidence_freshness" in stale.blockers


def test_live_activation_is_blocked_without_provider_credentials(tmp_path: Path):
    release = load_release(_active_release(tmp_path))
    with pytest.raises(ActivationBlocked) as caught:
        activate(
            release,
            environment={
                "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(
                    {
                        "live-app": {
                            "token_env": "LIVE_APP_TOKEN",
                            "scopes": ["route", "read", "health", "execute"],
                        }
                    }
                ),
                "LIVE_APP_TOKEN": "d" * 32,
                "MODEL_ROUTER_DATABASE_URL": "present",
            },
            evidence=_runtime(live=True),
            now=NOW,
        )
    assert "provider_credentials" in caught.value.report.blockers


def test_credential_parser_hashes_external_tokens_and_rejects_duplicates():
    release = load_release(MANIFEST)
    source = {
        "one": {"token_env": "TOKEN_ONE", "scopes": ["route", "read"]},
        "two": {"token_env": "TOKEN_TWO", "scopes": ["health"]},
    }
    environment = {
        "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(source),
        "TOKEN_ONE": "one-" + "x" * 32,
        "TOKEN_TWO": "two-" + "y" * 32,
    }
    records = parse_application_credentials(release, environment)
    assert {item["application_id"] for item in records} == {"one", "two"}
    assert all("TOKEN" not in json.dumps(dict(item)) for item in records)
    assert all(len(item["credential_digest"]) == 64 for item in records)

    environment["TOKEN_TWO"] = environment["TOKEN_ONE"]
    with pytest.raises(ValueError, match="digests must be unique"):
        parse_application_credentials(release, environment)


def test_measured_route_only_runtime_activates_from_real_sqlite_evidence(
    tmp_path: Path,
):
    release = load_release(MANIFEST)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'release.db'}"
    migrate_database(database_url, release.config.database.required_migration_revision)
    token = "runtime-token-" + "z" * 32
    environment = {
        "MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON": json.dumps(
            {
                "runtime-app": {
                    "token_env": "RUNTIME_APP_TOKEN",
                    "scopes": ["route", "read", "health"],
                }
            }
        ),
        "RUNTIME_APP_TOKEN": token,
        "MODEL_ROUTER_DATABASE_URL": database_url,
    }
    journal = tmp_path / "pending.jsonl"
    measured = collect_evidence(release, environment, journal)
    checked = preflight(release, environment=environment, evidence=measured)
    assert checked.ready

    receipt = tmp_path / "activation.json"
    activate(
        release,
        environment=environment,
        evidence=measured,
        report_path=receipt,
    )
    persisted = json.loads(receipt.read_text(encoding="utf-8"))
    assert persisted["enabled_operations"] == ["route", "read", "health"]


def test_activated_service_scopes_health_and_never_enables_execution(tmp_path):
    from fastapi.testclient import TestClient
    from model_router.release.runtime import build_app
    release=load_release(MANIFEST)
    url=f'sqlite+pysqlite:///{tmp_path / "service.db"}'
    migrate_database(url, release.config.database.required_migration_revision)
    env={'MODEL_ROUTER_DATABASE_URL':url,'APP_TOKEN':'x'*40,
         'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON':json.dumps({'app':{'token_env':'APP_TOKEN','scopes':['route','read','health']}}),
         'OPENAI_API_KEY':'presence-must-not-enable-live'}
    journal=tmp_path/'pending.jsonl'
    receipt=tmp_path/'activation.json'
    activate(release,environment=env,evidence=collect_evidence(release,env,journal),report_path=receipt)
    app=build_app(release,receipt,journal,env)
    with TestClient(app) as client:
        assert client.get('/health/live').status_code==200
        assert client.get('/health/ready').status_code==401
        headers={'Authorization':'Bearer '+env['APP_TOKEN']}
        ready=client.get('/health/ready',headers=headers)
        assert ready.status_code==200,ready.text
        assert ready.json()['live_execution_enabled'] is False
        assert client.post('/v1/execute',headers=headers,json={}).status_code==403
        assert client.get('/v1/tasks/nonexistent',headers=headers).status_code==404
    app.applications[0].dependencies.repository.engine.dispose()


@pytest.mark.parametrize('tamper',[{'checks':[]},{'enabled_operations':[]},{'activation_id':'made-up'},{'live_execution_enabled':True}])
def test_runtime_rejects_altered_activation_receipt(tmp_path,tamper):
    from model_router.release.runtime import build_app
    release=load_release(MANIFEST)
    url=f'sqlite+pysqlite:///{tmp_path / "tamper.db"}'
    migrate_database(url, release.config.database.required_migration_revision)
    env={'MODEL_ROUTER_DATABASE_URL':url,'APP_TOKEN':'x'*40,
         'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON':json.dumps({'app':{'token_env':'APP_TOKEN','scopes':['route','read','health']}})}
    journal=tmp_path/'pending.jsonl'
    receipt=activate(release,environment=env,evidence=collect_evidence(release,env,journal))
    payload=receipt.model_dump(mode='json')
    payload.update(tamper)
    path=tmp_path/'altered.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='activation receipt'):
        build_app(release,path,journal,env)


def test_real_release_composition_executes_through_durable_admission(tmp_path,monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from model_router.release.runtime import build_app
    from tests.phase3_support import success
    from model_router.execution.openai_provider import OpenAIProvider
    manifest_path=_active_release(tmp_path)
    manifest=yaml.safe_load(manifest_path.read_text())
    evidence_path=Path(manifest['live']['evidence']['path'])
    evidence=yaml.safe_load(evidence_path.read_text())
    evidence['verified_at']=datetime.now(UTC).isoformat()
    evidence['credential_sha256']=sha256(b'offline-stub-only').hexdigest()
    evidence_path.write_text(yaml.safe_dump(evidence))
    manifest['live']['evidence']['sha256']=sha256(evidence_path.read_bytes()).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest))
    release=load_release(manifest_path)
    url=f'sqlite+pysqlite:///{tmp_path / "live-composition.db"}'
    migrate_database(url,release.config.database.required_migration_revision)
    env={'MODEL_ROUTER_DATABASE_URL':url,'APP_TOKEN':'x'*40,'OTHER_TOKEN':'y'*40,'RUN_LIVE_OPENAI_TESTS':'1','OPENAI_API_KEY':'offline-stub-only',
        'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON':json.dumps({app:{'token_env':token,'scopes':['route','read','execute','health']} for app,token in [('app','APP_TOKEN'),('other','OTHER_TOKEN')]})}
    journal=tmp_path/'live-pending.jsonl'
    receipt=tmp_path/'live-activation.json'
    activate(release,environment=env,evidence=collect_evidence(release,env,journal),report_path=receipt)
    calls=[]
    def stub(self,request):
        calls.append(request)
        return success(request)
    monkeypatch.setattr(OpenAIProvider,'execute',stub)
    app=build_app(release,receipt,journal,env)
    body={'request':{'task_id':'__readiness__','trace_id':'live-trace-1','input':'Reply OK.','consequence':'low',
         'requirements':['text_input','text_output'],'context':{'input_tokens':1,'expected_output_tokens':64}},
        'classification':{'task_family':'transform','confidence':1,'provenance':'test',
            'components':{key:0 for key in release.policy_bundle.policy['complexity']['components']}},'idempotency_key':'live-key-1'}
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+env['APP_TOKEN']}
        response=client.post('/v1/execute',json=body,headers=headers)
        assert response.status_code==200,response.text
        assert response.json()['status']=='succeeded',response.text
        assert len(calls)==1
        duplicate=client.post('/v1/execute',json=body,headers=headers)
        assert duplicate.status_code==200
        assert len(calls)==1
        other_body={**body,'request':{**body['request'],'task_id':'other-app-task','trace_id':'other-trace'}}
        other=client.post('/v1/execute',json=other_body,headers={'Authorization':'Bearer '+env['OTHER_TOKEN']})
        assert other.status_code==200,other.text
        assert other.json()['status']=='succeeded',other.text
        assert len(calls)==2
    app.applications[0].dependencies.repository.engine.dispose()


@pytest.mark.parametrize('section,field,value',[
    ('operations','shadow',True),('operations','tools',True),
    ('health','live_probes_enabled',True),('auth','minimum_token_bytes',1)])
def test_release_rejects_unimplemented_or_unsafe_settings(tmp_path,section,field,value):
    data=yaml.safe_load(MANIFEST.read_text())
    data[section][field]=value
    path=tmp_path/'unsafe.yaml'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ReleaseConfigurationError):
        load_release(path)


def test_cli_sanitizes_dependency_exception(monkeypatch,tmp_path,capsys):
    from model_router.release.cli import main
    monkeypatch.setenv('MODEL_ROUTER_DATABASE_URL','test')
    def fail(*args): raise RuntimeError('private-password-and-input')
    monkeypatch.setattr('model_router.storage.migrations.migrate_database',fail)
    assert main(['migrate',str(MANIFEST)])==2
    assert 'private-password' not in capsys.readouterr().out


def test_live_preflight_rejects_unsupported_long_context_envelope(tmp_path):
    path=_active_release(tmp_path)
    manifest=yaml.safe_load(path.read_text())
    manifest['limits']['max_input_tokens']=400000
    path.write_text(yaml.safe_dump(manifest))
    release=load_release(path)
    env={'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON':json.dumps({'app':{'token_env':'TOKEN','scopes':['route','read','execute','health']}}),
        'TOKEN':'x'*40,'MODEL_ROUTER_DATABASE_URL':'present','RUN_LIVE_OPENAI_TESTS':'1','OPENAI_API_KEY':'present-but-never-called'}
    report=preflight(release,environment=env,evidence=_runtime(live=True),now=NOW)
    assert not report.ready
    assert 'model_token_bounds' in report.blockers
