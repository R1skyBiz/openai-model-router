"""Explicitly fabricated, content-free local evidence; never a live execution path."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import yaml

from model_router.core.configuration import bundle_from_documents
from model_router.core.contracts import Candidate, Classification, Effort, EnvironmentSnapshot, Request, RouteDecision
from model_router.core.execution_contracts import (
    Attempt, AttemptStatus, Counters, ExecutionEvent, Failure, RecoveryAction, ShadowRun,
    RouteTarget, TaskResult, TaskStatus, ToolOutcome, ValidationOutcome,
)
from model_router.core.phase4_contracts import HealthObservation, HealthSnapshot
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.router import route
from model_router.storage import SQLiteTaskRepository
from model_router.storage.migrations import upgrade_database
from model_router.storage.telemetry import read_evidence

ROOT = Path(__file__).resolve().parents[3]
MARKER = 'synthetic-demo-v1'


def _bundle(version):
    documents = [yaml.safe_load((ROOT / 'config' / name).read_text()) for name in
                 ('routing-policy.yaml', 'models.yaml', 'budgets.yaml', 'validation.yaml')]
    documents[0]['version'] = version
    return bundle_from_documents(*documents)


def _classification(family, score, bundle):
    components = {}
    for name, limits in bundle.policy['complexity']['components'].items():
        value = min(score, limits['max'])
        components[name] = value
        score -= value
    return Classification(task_family=family, confidence=1.0,
                          provenance=MARKER, components=components)


def generate_demo(directory: str | Path, *, now: datetime | None = None, count: int = 180) -> Path:
    """Write a new marked directory. Refuse overwrite, even of an existing demo."""
    now = now or datetime.now(UTC)
    if now.utcoffset() is None or not 10 <= count <= 5000:
        raise ValueError('demo requires aware time and 10–5000 tasks')
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    database = target / 'synthetic-demo.sqlite3'
    manifest = target / 'synthetic-demo.json'
    if database.exists() or manifest.exists():
        raise ValueError('demo already exists; choose a new output directory')
    settings = yaml.safe_load((ROOT / 'config/demo.yaml').read_text())
    evaluator_bindings = yaml.safe_load((ROOT / 'config/phase4.yaml').read_text())['evaluators']
    bundles = [_bundle(version) for version in settings['policy_versions']]
    url = 'sqlite:///' + str(database)
    upgrade_database(url)
    repository = SQLiteTaskRepository(url, journal_path=target / 'synthetic-pending.jsonl')
    for bundle in bundles:
        repository.pin_versions(policy_version=bundle.policy['version'], policy_snapshot={
            'policy': bundle.policy, 'budgets': bundle.budgets, 'validation': bundle.validation,
            'content_hash': bundle.content_hash},
                                catalog_version=bundle.catalog['catalog_version'], catalog_snapshot=bundle.catalog)
    repository.store_pricing_version(MARKER, {'version': MARKER, 'synthetic': True,
        'source': 'fabricated_display_charges', 'notice': 'Not provider tariffs; config/demo.yaml defines sample amounts.'})
    for index in range(count):
        # Include both policy versions throughout the same month for descriptive comparisons.
        bundle = bundles[index % len(bundles)]
        spec = settings['scenarios'][index % len(settings['scenarios'])]
        created = now - timedelta(seconds=60 + (count - 1 - index) * 28 * 86400 / count)
        task_id = f'synthetic-demo-{index:04d}'
        trace_id = f'{task_id}-trace'
        policy = bundle.policy['version']
        application = settings['applications'][index % len(settings['applications'])]
        classification = _classification(spec['family'], spec['score'], bundle)
        environment = EnvironmentSnapshot(snapshot_id=f'{task_id}-environment', synthetic=True,
            clock=created, pricing_version=MARKER, trusted_application_id=application,
            health_snapshot_id=f'{task_id}-health', health_observed_at=created - timedelta(seconds=1),
            health_valid_until=created + timedelta(minutes=5),
            models={name: {'state': 'HEALTHY', 'account_access': 'verified'} for name in bundle.catalog['models']},
            budget={'task_cost_ceiling_usd': '10', 'task_deadline_ms': 30000, 'live_execution_enabled': True},
            remaining_usd='10', validation={'V0': 'configured_mock', 'V1': 'configured_mock', 'V2': 'configured_mock'},
            recovery_bounded=True, durable_retention=True)
        request = Request(task_id=task_id, trace_id=trace_id, application_id=application,
            input='synthetic content never persisted', requirements=('text_input', 'text_output'),
            consequence='low', requested_validation=spec['validation'],
            context={'input_tokens': 1200, 'expected_output_tokens': 500})
        initial = route(request, classification, environment, bundle,
                        recovery_candidates=(Candidate(model=spec['model'], effort=spec['effort'], source='fallback'),))
        if not isinstance(initial, RouteDecision):
            raise ValueError(f'synthetic route rejected for scenario {index % 5}')
        events = []
        def event(kind, timestamp, **kwargs):
            events.append(ExecutionEvent(event_id=f'{task_id}-event-{len(events):03d}', task_id=task_id,
                trace_id=trace_id, kind=kind, occurred_at=timestamp, policy_version=policy, **kwargs))
        event('TASK_CREATED', created)
        base = TaskResult(task_id=task_id, trace_id=trace_id, application_id=application,
                          status=TaskStatus.CREATED, policy_version=policy, created_at=created, updated_at=created)
        repository.create(base, events[0], scope=application, key_digest=None, request_digest=task_id)
        event('TASK_CLASSIFIED', created + timedelta(milliseconds=25))
        event('ROUTE_SELECTED', created + timedelta(milliseconds=50), decision_id=initial.decision_id)
        quality = index % 11 == 1 and 'recovery_effort' in spec
        retry = index % 13 == 2
        tool = index % 17 == 3
        failed = index % 19 == 4
        partial = index % 29 == 5
        pending = index % 41 == 6
        cancelled = index % 43 == 7
        decisions, attempts, evaluators, actions, tools = [initial], [], [], [], []
        cursor = created + timedelta(milliseconds=100)
        total = Decimal('0')
        validation_cost = Decimal('0')
        generation_cost = Decimal('0')
        for sequence in range(2 if quality or retry else 1):
            decision = decisions[-1]
            attempt_id = f'{task_id}-generation-{sequence + 1}'
            latency = 280 + (index * 173) % 5800
            finished = cursor + timedelta(milliseconds=latency)
            amount = Decimal(spec['cost']) * (Decimal('1') + Decimal(index % 7) / 10)
            actual = None if partial and sequence == 0 else amount
            failure = None
            if sequence == 0 and (retry or quality) or failed:
                kind = 'TIMEOUT' if retry and sequence == 0 else 'QUALITY_FAILURE'
                failure = Failure(failure_type=kind, source='provider' if kind == 'TIMEOUT' else 'validation',
                                  stage='invocation' if kind == 'TIMEOUT' else 'validation', cause_code='synthetic_failure', retryable=True)
            evidence = ProviderResult(task_id=task_id, trace_id=trace_id, invocation_id=attempt_id,
                policy_version=policy, catalog_version=decision.catalog_version, model_alias=decision.selected_model_alias,
                provider_model_id=decision.provider_model_id, reasoning_effort=decision.reasoning_effort,
                purpose='generation', response_status='completed', latency_ms=float(latency),
                usage=ProviderUsage(input_tokens=1200, cached_input_tokens=200, cache_write_input_tokens=0,
                                    output_tokens=500, reasoning_tokens=100, total_tokens=1700))
            if failure is not None and failure.failure_type == 'TIMEOUT':
                evidence = ProviderFailure(**{key: value for key, value in evidence.model_dump().items()
                    if key not in ('outcome', 'incomplete_reason', 'refused')},
                    failure_type='TIMEOUT', source='provider', stage='invocation', cause_code='synthetic_timeout', retryable=True)
            check = ValidationOutcome(evaluation_id=f'{attempt_id}-v0', check='provider_success',
                status='failed' if failure else 'passed', failure=failure, target_attempt_id=attempt_id)
            attempt = Attempt(attempt_id=attempt_id, task_id=task_id, trace_id=trace_id, sequence=sequence+1,
                status='failed' if failure else 'succeeded', started_at=cursor, completed_at=finished,
                decision=decision, actual_cost_usd=actual, pricing_version=MARKER,
                provider_outcome=evidence, failure=failure, validations=(check,))
            attempts.append(attempt)
            generation_cost += actual or Decimal('0')
            event('ATTEMPT_STARTED', cursor, attempt_id=attempt_id, decision_id=decision.decision_id)
            event('ATTEMPT_COMPLETED', finished, attempt_id=attempt_id, decision_id=decision.decision_id,
                  failure_type=failure.failure_type if failure else None)
            event('VALIDATION_COMPLETED', finished + timedelta(milliseconds=5), attempt_id=attempt_id, evaluation_id=check.evaluation_id)
            cursor = finished + timedelta(milliseconds=10)
            if spec['validation'] != 'V0' and not (retry and sequence == 0):
                binding = evaluator_bindings[0 if spec['validation'] == 'V1' else 1]
                evaluator_id = f'{attempt_id}-evaluator'
                evaluator_cost = Decimal(settings['validation_costs'][spec['validation']])
                evaluation = ValidationOutcome(evaluation_id=f'{evaluator_id}-result', check=spec['validation'],
                    status='failed' if failure else 'passed', evaluator_attempt_id=evaluator_id,
                    target_attempt_id=attempt_id, rubric_version='synthetic-rubric-' + spec['validation'],
                    score=0.45 if failure else 0.88 + (index % 4) * .02, score_min=0., score_max=1.)
                eval_evidence = evidence.model_copy(update={'invocation_id': evaluator_id, 'purpose': 'evaluation',
                    'model_alias': binding['model_alias'], 'provider_model_id': bundle.catalog['models'][binding['model_alias']]['provider_model_id'],
                    'reasoning_effort': Effort(binding['reasoning_effort']), 'latency_ms': 210.0})
                evaluators.append(Attempt(attempt_id=evaluator_id, task_id=task_id, trace_id=trace_id, sequence=len(evaluators)+1,
                    purpose='evaluation', parent_attempt_id=attempt_id, status='succeeded', started_at=cursor,
                    completed_at=cursor + timedelta(milliseconds=210), pricing_version=MARKER,
                    actual_cost_usd=evaluator_cost, provider_outcome=eval_evidence, validations=(evaluation,),
                    rubric_version=evaluation.rubric_version, evaluator_ref=binding['ref']))
                event('ATTEMPT_STARTED', cursor, attempt_id=evaluator_id, decision_id=decision.decision_id)
                event('ATTEMPT_COMPLETED', cursor + timedelta(milliseconds=210), attempt_id=evaluator_id)
                event('VALIDATION_COMPLETED', cursor + timedelta(milliseconds=210), attempt_id=attempt_id,
                      evaluation_id=evaluation.evaluation_id)
                cursor += timedelta(milliseconds=220)
                validation_cost += evaluator_cost
            if sequence == 0 and (quality or retry):
                action = 'increase_effort' if quality else 'retry_backoff'
                actions.append(RecoveryAction(action=action, failure='QUALITY_FAILURE' if quality else 'TIMEOUT',
                    route=RouteTarget(model=spec['model'], effort=spec['recovery_effort'] if quality else spec['effort']),
                    reason='synthetic_recovery', validated=quality))
                event('RECOVERY_SELECTED', cursor, attempt_id=attempt_id, action=action)
                if quality:
                    recovery = route(request, classification, environment, bundle,
                        recovery_candidates=(Candidate(model=spec['model'], effort=spec['recovery_effort'], source='fallback'),))
                    decisions.append(recovery)
                    event('ROUTE_SELECTED', cursor + timedelta(milliseconds=1), decision_id=recovery.decision_id)
                cursor += timedelta(milliseconds=250)
        if tool:
            for number in range(2):
                tool_id = f'{task_id}-tool-{number}'
                tools.append(ToolOutcome(tool_event_id=tool_id, tool='synthetic-search', operation='synthetic-read',
                    status='failed' if number == 0 else 'succeeded', cost_usd=settings['tool_cost'], parent_attempt_id=attempts[-1].attempt_id,
                    latency_ms=150, failure=Failure(failure_type='TOOL_FAILURE', source='tool', stage='tool', cause_code='synthetic_timeout') if number == 0 else None))
                event('TOOL_STARTED', cursor, tool_event_id=tool_id, attempt_id=attempts[-1].attempt_id)
                cursor += timedelta(milliseconds=150)
                event('TOOL_COMPLETED', cursor, tool_event_id=tool_id, attempt_id=attempts[-1].attempt_id)
                if number == 0:
                    actions.append(RecoveryAction(action='retry_tool', failure='TOOL_FAILURE', reason='synthetic_tool_recovery'))
                    event('RECOVERY_SELECTED', cursor, action='retry_tool')
        state = TaskStatus.RUNNING if pending else TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED if failed else TaskStatus.SUCCEEDED
        if not pending:
            event('TASK_' + state.value.upper(), cursor)
        health_state = 'DEGRADED' if index % 9 == 0 else 'HEALTHY'
        observations = tuple(HealthObservation(component=component, model=initial.selected_model_alias if component == 'model' else None,
            state=health_state if component == 'model' else 'HEALTHY', observed_at=created - timedelta(seconds=1),
            valid_until=created + timedelta(minutes=5), circuit_state='closed', latency_ms=50,
            failure_count=1 if component == 'model' and health_state == 'DEGRADED' else 0)
            for component in ('model', 'evaluator', 'database', 'telemetry', 'tools'))
        snapshot = HealthSnapshot(snapshot_id=initial.health_snapshot_id, config_version=MARKER,
            observed_at=created - timedelta(seconds=1), valid_until=created + timedelta(minutes=5), observations=observations)
        shadows = ()
        if index % 7 == 0:
            shadow_id = f'{task_id}-shadow-generation'
            comparison = settings['scenarios'][2 if spec['model'] != settings['scenarios'][2]['model'] else 4]
            shadow_route = route(request, classification, environment, bundle, recovery_candidates=(
                Candidate(model=comparison['model'], effort=comparison['effort'], source='fallback'),))
            if not isinstance(shadow_route, RouteDecision):
                shadow_route = initial
            shadow_check = ValidationOutcome(evaluation_id=shadow_id+'-v0', check='provider_success', status='passed', target_attempt_id=shadow_id)
            shadow_attempt = attempts[-1].model_copy(update={'attempt_id': f'{task_id}-shadow-generation', 'role': 'shadow',
                'decision': shadow_route, 'actual_cost_usd': Decimal(settings['shadow_cost']), 'validations': (shadow_check,), 'status': AttemptStatus.SUCCEEDED, 'failure': None,
                'provider_outcome': ProviderResult(task_id=task_id, trace_id=trace_id, invocation_id=shadow_id,
                    policy_version=policy, catalog_version=shadow_route.catalog_version, model_alias=shadow_route.selected_model_alias,
                    provider_model_id=shadow_route.provider_model_id, reasoning_effort=shadow_route.reasoning_effort,
                    purpose='generation', response_status='completed', latency_ms=450., usage=attempts[-1].provider_outcome.usage)})
            shadows = (ShadowRun(shadow_id=f'{task_id}-shadow', production_attempt_id=attempts[-1].attempt_id,
                config_version=MARKER, sampling_seed=MARKER, sampling_rate=1/7, selected=True,
                status='succeeded', reason='synthetic_comparison', attempts=(shadow_attempt,), generation_cost_usd=settings['shadow_cost']),)
            event('ATTEMPT_STARTED', shadow_attempt.started_at, attempt_id=shadow_id, decision_id=shadow_route.decision_id)
            event('ATTEMPT_COMPLETED', shadow_attempt.completed_at, attempt_id=shadow_id)
            event('VALIDATION_COMPLETED', shadow_attempt.completed_at, attempt_id=shadow_id, evaluation_id=shadow_check.evaluation_id)
        total = generation_cost + validation_cost + sum((t.cost_usd for t in tools), Decimal('0'))
        task = base.model_copy(update={'status': state, 'updated_at': cursor, 'revision': 1, 'classification': classification,
            'initial_decision': initial, 'decisions': tuple(decisions), 'attempts': tuple(attempts),
            'evaluator_attempts': tuple(evaluators), 'tool_events': tuple(tools), 'recovery_actions': tuple(actions),
            'counters': Counters(generation_attempts=len(attempts), quality_escalations=int(quality),
                                 infrastructure_retries=int(retry), tool_recoveries=int(tool)),
            'health_snapshots': (snapshot,), 'shadow_runs': shadows, 'total_cost_usd': None if partial else total,
            'known_cost_usd': total, 'production_generation_cost_usd': None if partial else generation_cost,
            'production_validation_cost_usd': validation_cost})
        task = TaskResult.model_validate(task.model_dump(mode='json'))
        repository.save(task, tuple(events[1:]), expected_revision=0)
    repository.engine.dispose()
    manifest.write_text(json.dumps({'dataset': MARKER, 'synthetic': True, 'generated_at': now.isoformat(),
        'task_count': count, 'database': database.name, 'sha256': hashlib.sha256(database.read_bytes()).hexdigest(),
        'notice': 'Fabricated display evidence, never production measurements or model-quality claims.'}, indent=2) + '\n')
    return database


def open_demo(directory: str | Path) -> SQLiteTaskRepository:
    """Require marker and per-record provenance; never open arbitrary telemetry as demo."""
    target = Path(directory).resolve()
    marker = json.loads((target / 'synthetic-demo.json').read_text())
    if marker.get('dataset') != MARKER or marker.get('synthetic') is not True:
        raise ValueError('explicit synthetic dataset marker required')
    database = target / 'synthetic-demo.sqlite3'
    if hashlib.sha256(database.read_bytes()).hexdigest() != marker.get('sha256'):
        raise ValueError('synthetic dataset changed since generation')
    repository = SQLiteTaskRepository('sqlite:///' + str(database), journal_path=target / 'synthetic-pending.jsonl')
    records, _ = read_evidence(repository)
    if len(records) != marker['task_count']:
        raise ValueError('synthetic dataset count mismatch')
    for task in records:
        if not task.task_id.startswith('synthetic-demo-') or not task.policy_version.startswith('synthetic-demo-policy-') or not task.initial_decision.synthetic:
            raise ValueError('mixed synthetic dataset is forbidden')
    return repository
