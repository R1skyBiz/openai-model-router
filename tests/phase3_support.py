from datetime import datetime, timezone
from decimal import Decimal
from model_router.core.contracts import Request, Classification, EnvironmentSnapshot
from model_router.core.execution_contracts import ExecutionLimits, ExecutionControls
from model_router.policy.loader import load_bundle
from model_router.execution.orchestrator import ExecutionDependencies
from model_router.execution.provider import MockProvider, request_evidence
from model_router.core.provider_contracts import ProviderResult, ProviderUsage
from model_router.execution.admission import MemoryBudgetAuthority
from model_router.execution.clock import MockClock
from model_router.storage import SQLiteTaskRepository
from model_router.storage.migrations import upgrade_database


def success(request):
    return ProviderResult(**request_evidence(request), response_status='completed', text='private output',
        usage=ProviderUsage(input_tokens=10, cached_input_tokens=0, cache_write_input_tokens=0,
                            output_tokens=10, reasoning_tokens=0, total_tokens=20))


def setup(tmp_path, outcomes=None, **kwargs):
    bundle = load_bundle('config')
    now = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)
    env = EnvironmentSnapshot(snapshot_id='synthetic', synthetic=True, clock=now, pricing_version='synthetic',
        health_snapshot_id='health', health_observed_at='2026-09-06T19:59:00Z', health_valid_until='2026-09-06T21:00:00Z',
        models={alias: {'state': 'HEALTHY', 'account_access': 'verified'} for alias in bundle.catalog['models']},
        budget={'task_cost_ceiling_usd': '10', 'task_deadline_ms': 30000, 'live_execution_enabled': True},
        remaining_usd='10', validation={'V0': 'configured_mock'}, recovery_bounded=True, durable_retention=True)
    request = Request(task_id='task', trace_id='trace', input='private prompt', requirements=('text_input','text_output'),
        consequence='low', context={'input_tokens': 100, 'expected_output_tokens': 100})
    classification = Classification(task_family='analysis', confidence=1., provenance='fixture', components={
        'reasoning_depth':12, 'step_dependency':11, 'context_synthesis':7, 'technical_precision':11,
        'ambiguity':5, 'tool_orchestration':0, 'reliability_requirement':3})
    limits = ExecutionLimits(max_total_generation_attempts=3, max_quality_escalations=2,
        max_infrastructure_retries=1, max_tool_recoveries=1, max_elapsed_ms=30000,
        initial_backoff_ms=100, max_backoff_ms=1000, task_cost_ceiling_usd='10')
    url = 'sqlite+pysqlite:///' + str(tmp_path / 'state.db')
    upgrade_database(url)
    repo = SQLiteTaskRepository(url, journal_path=tmp_path/'journal.jsonl')
    values = dict(bundle=bundle, environment=env, provider=MockProvider(outcomes or [success]),
        repository=repo, budget=MemoryBudgetAuthority(default_ceiling='10'), clock=MockClock(now),
        limits=limits, controls=ExecutionControls(authorized=True))
    values.update(kwargs)
    return request, classification, ExecutionDependencies(**values)
