"""Operator-owned service composition; importing this module enables nothing."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from hashlib import sha256
from dataclasses import replace


from model_router.core.contracts import EnvironmentSnapshot, Limits, ModelHealth
from model_router.core.execution_contracts import ExecutionControls, ExecutionLimits
from model_router.execution.clock import SystemClock
from model_router.execution.live import LiveExecutionAuthorization, ReleaseEnvironmentSnapshot
from model_router.execution.orchestrator import ExecutionDependencies
from model_router.execution.provider import MockProvider
from model_router.release.activation import ActivationBlocked, preflight, _portable
from model_router.release.loader import load_release
from model_router.release.schema import ActivationReport, RuntimeEvidence


def _repository(release, environment, journal_path):
    from model_router.storage.repository import SQLTaskRepository
    return SQLTaskRepository(environment[release.config.database.url_env], journal_path=journal_path,
        connection_timeout_ms=release.config.database.connect_timeout_ms,
        pool_size=release.config.database.pool_size)


def collect_evidence(release, environment=None, journal_path=None):
    """Observe actual local dependencies; never probe or pay the provider."""
    env = os.environ if environment is None else environment
    journal = Path(journal_path or env.get(release.config.database.journal_path_env,'model-router-pending.jsonl'))
    repo = None
    try:
        repo = _repository(release, env, journal)
        revision = repo.current_migration_revision()
        status = repo.readiness(max_pending_outbox=release.config.outbox.max_pending_events)
        # Test retention filesystem using a distinct temporary file, never the journal itself.
        import tempfile
        journal.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=journal.parent) as stream:
            stream.write(b'retention-preflight')
            stream.flush()
            os.fsync(stream.fileno())
        components = ['configuration','database']
        if status['ready']:
            components.append('telemetry')
        evidence = release.live_evidence
        if evidence is not None:
            age = datetime.now(UTC)-evidence.verified_at
            if timedelta(0) <= age < timedelta(milliseconds=release.config.health.freshness_ms):
                components.extend('provider:'+alias for alias in evidence.models)
                if release.config.operations.live_classifier:
                    components.append('classifier')
        return RuntimeEvidence(database_reachable=True,database_dialect=repo.engine.dialect.name,
            database_revision=revision,outbox_ready=status['ready'],
            health_ready=set(release.config.health.required_components).issubset(components),
            health_config_version=release.config.health.config_version,healthy_components=tuple(components),
            health_observed_at=evidence.verified_at if evidence is not None else datetime.now(UTC))
    except Exception:
        return RuntimeEvidence()
    finally:
        if repo is not None:
            repo.engine.dispose()


from model_router.service.release import ReleaseService


def build_app(release, activation_path, journal_path, environment=None):
    """Load a matching activation receipt and recheck all gates before serving."""
    env=os.environ if environment is None else environment
    from model_router.release.activation import parse_application_credentials
    from model_router.service import AuthenticatedApplication, create_authenticated_app
    from model_router.storage.budget import SQLBudgetAuthority
    receipt=ActivationReport.model_validate_json(Path(activation_path).read_text())
    if (receipt.release_sha256 != release.release_sha256
            or receipt.release_id != release.config.release_id
            or _portable(receipt.manifest) != _portable(release.canonical_manifest)
            or not all(check.passed for check in receipt.checks)):
        raise ValueError('activation receipt does not match release')
    def check():
        current=load_release(release.source)
        if current.release_sha256 != release.release_sha256:
            return False
        return preflight(current,environment=env,
            evidence=collect_evidence(current,env,journal_path)).ready
    report=preflight(release,environment=env,evidence=collect_evidence(release,env,journal_path))
    if not report.ready:
        raise ActivationBlocked(report)
    identity={'release_sha256':receipt.release_sha256,
        'activated_at':receipt.activated_at.isoformat(),
        'enabled_operations':list(receipt.enabled_operations),
        'checks':[item.model_dump(mode='json') for item in receipt.checks]}
    expected_id='activation-'+sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (receipt.activation_id != expected_id or receipt.activated_at > datetime.now(UTC)
            or receipt.enabled_operations != report.enabled_operations
            or (receipt.paid_classifier_enabled is not None
                and receipt.paid_classifier_enabled != release.config.operations.live_classifier)
            or receipt.live_execution_enabled != release.config.operations.live_provider
            or tuple(c.name for c in receipt.checks) != tuple(c.name for c in report.checks)):
        raise ValueError('activation receipt is incomplete or altered')
    config=release.config
    repo=_repository(release,env,journal_path)
    clock=SystemClock()
    limits=ExecutionLimits(max_total_generation_attempts=config.limits.actions.max_total_generation_attempts,
        max_quality_escalations=config.limits.actions.max_quality_escalations,
        max_infrastructure_retries=config.limits.actions.max_infrastructure_retries,
        max_tool_recoveries=config.limits.actions.max_tool_recoveries,
        max_elapsed_ms=config.limits.task_deadline_ms,initial_backoff_ms=config.limits.backoff.initial_ms,
        max_backoff_ms=config.limits.backoff.maximum_ms,task_cost_ceiling_usd=str(config.limits.task_cost_ceiling_usd))
    provider=MockProvider([])
    live=None
    if config.operations.live_provider:
        from model_router.execution.openai_provider import OpenAIProvider
        provider=OpenAIProvider(release.policy_bundle, api_key=env[config.live.credential_env])
        factory=None
        if config.operations.live_classifier:
            from model_router.classification import OpenAIClassifier
            factory=lambda p:OpenAIClassifier(p,release.policy_bundle,release.classifier_config)
        live=LiveExecutionAuthorization(config.release_id,config.limits.max_input_tokens,
            config.live.classifier_input_overhead_tokens,check,factory,
            max_output_tokens=config.limits.max_output_tokens,provider_timeout_ms=config.limits.provider_timeout_ms)
    def readiness():
        facts=collect_evidence(release,env,journal_path)
        status=preflight(release,environment=env,evidence=facts)
        return {'ready':status.ready,'state':'HEALTHY' if status.ready else 'UNHEALTHY',
            'enabled_operations':list(status.enabled_operations),'blockers':list(status.blockers),
            'components':list(facts.healthy_components),'checked_at':status.checked_at.isoformat(),
            'live_execution_enabled':config.operations.live_provider,
            'paid_classifier_enabled':config.operations.live_classifier}
    records=[]
    preview_provider = None
    if config.operations.classify_route:
        from model_router.execution.openai_provider import OpenAIProvider
        preview_provider = OpenAIProvider(release.policy_bundle, api_key=env[config.live.credential_env])
    for credential in parse_application_credentials(release,env):
        app_id=credential['application_id']
        def snapshot(identity=app_id):
            now=clock.now()
            source=release.live_evidence
            observed=source.verified_at if source is not None else now
            # An absent account observation never manufactures provider readiness.
            models={alias:ModelHealth(state='HEALTHY',account_access='verified')
                for alias in (source.models if source else ())}
            return ReleaseEnvironmentSnapshot(release_version=config.release_id,snapshot_id=release.release_sha256,clock=now,
                pricing_version=release.policy_bundle.catalog['catalog_version'],
                trusted_application_id=identity,models=models,
                health_snapshot_id=source.evidence_id if source else None,
                health_observed_at=observed if source else None,
                health_valid_until=observed+timedelta(milliseconds=config.health.freshness_ms) if source else None,
                recovery_bounded=live is not None,durable_retention=check() if live else False,
                budget=Limits(task_cost_ceiling_usd=str(config.limits.task_cost_ceiling_usd),
                    task_deadline_ms=config.limits.task_deadline_ms,
                    live_execution_enabled=config.operations.live_provider))
        budget=SQLBudgetAuthority(repo,app_id,config.limits.allocation_id,
            str(config.limits.application_cost_ceiling_usd),str(config.limits.task_cost_ceiling_usd))
        application_live=replace(live,durable_allocation_verified=lambda task_id,authority=budget: authority.remaining(task_id) >= 0) if live else None
        deps=ExecutionDependencies(bundle=release.policy_bundle,environment=snapshot,provider=provider,
            repository=repo,budget=budget,clock=clock,limits=limits,
            controls=ExecutionControls(authorized=config.operations.execute),live=application_live,release_readiness=readiness)
        preview = None
        if config.operations.classify_route:
            from model_router.execution.preview import PreviewDependencies
            from model_router.storage.previews import SQLPreviewRepository
            preview_budget = SQLBudgetAuthority(repo, app_id,
                config.limits.allocation_id + ':classify-route',
                str(config.limits.application_cost_ceiling_usd), str(config.limits.task_cost_ceiling_usd))
            preview = PreviewDependencies(application_id=app_id, bundle=release.policy_bundle,
                release_sha256=release.release_sha256, activation_id=receipt.activation_id,
                account_evidence_id=release.live_evidence.evidence_id,
                environment=snapshot, classifier_config=release.classifier_config,
                classifier_provider=preview_provider,
                authorization=LiveExecutionAuthorization(config.release_id,
                    config.limits.max_input_tokens, config.live.classifier_input_overhead_tokens, check,
                    max_output_tokens=config.limits.max_output_tokens,
                    provider_timeout_ms=config.limits.provider_timeout_ms),
                repository=SQLPreviewRepository(repo, preview_budget.allocation_id, config.limits.max_preview_records),
                budget=preview_budget, clock=clock,
                deadline_ms=config.limits.task_deadline_ms)
        # Scopes are an intersection, so disabled operations cannot be exposed by
        # an accidentally overprivileged credential record.
        scopes=frozenset(s for s in credential['scopes'] if getattr(config.operations,s))
        records.append(AuthenticatedApplication(app_id,credential['credential_digest'],deps,scopes,preview))
    app=create_authenticated_app(applications=records)
    service=ReleaseService(app,release,check)
    service.applications=tuple(records)
    return service
