from datetime import UTC, datetime
from decimal import Decimal, localcontext
import json
import pytest
from model_router.calibration.config import load_config
from model_router.calibration.contracts import (CalibrationRun, RunManifest, CorpusManifest, StrategyRun,
    CallEvidence, Grade, SemanticScore)
from model_router.calibration.analytics import analyze, cohort, comparison
from model_router.calibration.reporting import json_report, render_markdown

CONFIG = load_config('config/calibration-v1.yaml')

def row(case='a', strategy='ROUTER', state='PASS', cost='2', **changes):
    strat = next(s for s in CONFIG.strategies if s.name == strategy)
    model = strat.model or 'sol'
    calls = [CallEvidence(call_id=f'{case}-{strategy}-generation', purpose='generation', model=model,
                          effort='medium', cost_usd=cost, status='completed')]
    values = dict(strategy_run_id=f'{case}-{strategy}', case_id=case, strategy=strat, input_sha256='same',
                  validation_signature='v0-same-rubric', policy_version='policy', calls=tuple(calls),
                  initial_model=model, initial_effort='medium', execution_status='completed', complete=True,
                  grade=Grade(candidate_id=f'blind-{case}-{strategy}', disposition=state),
                  latency_ms=100, task_family='analysis', complexity_band='moderate',
                  source_kind='synthetic_control', consequence='low', tags=('sample',))
    values.update(changes)
    return StrategyRun(**values)

def run(*rows):
    return CalibrationRun(manifest=RunManifest(run_id='test', created_at=datetime.now(UTC),
        corpus=CorpusManifest(corpus_version='v1', corpus_sha256='hash', case_count=len({r.case_id for r in rows}), privacy='public'),
        policy_version='policy', policy_sha256='policyhash',
        model_catalog={'models': {'luna': {'tier_rank': 0}, 'terra': {'tier_rank': 1}, 'sol': {'tier_rank': 2}}},
        pricing_snapshot={}, classifier={}, rubrics=(), config=CONFIG, offline=True, strategy_order={}),
        strategy_runs=rows, status='completed')

def test_failed_work_in_ecps_and_unknown_excluded_but_spend_includes_it():
    report = analyze(run(row(cost='1'), row('b', state='FAIL', cost='2'), row('c', state='UNKNOWN', cost='100')))
    metrics = report['strategies']['ROUTER']
    assert metrics['effective_cost_per_successful_task_usd'] == Decimal('3')
    assert metrics['pass_rate'] == {'numerator': 1, 'denominator': 2, 'value': Decimal('.5')}
    assert metrics['unknown_rate']['numerator'] == 1
    assert report['spend']['experiment_inclusive_spend']['amount'] == Decimal('103')

@pytest.mark.parametrize('states', [(), ('FAIL',), ('UNKNOWN',), ('NEEDS_REVIEW',), ('INVALID',)])
def test_undefined_success_denominators(states):
    metrics = cohort([row(str(i), state=state) for i, state in enumerate(states)], 30)
    assert metrics['effective_cost_per_successful_task_usd'] is None
    if states != ('FAIL',):
        assert metrics['pass_rate']['value'] is None


def test_cost_roles_and_duplicate_grade_reference_charged_once():
    base = row(cost='1')
    classifier = CallEvidence(call_id='classifier', purpose='classification', cost_usd='.1', status='completed')
    validation = CallEvidence(call_id='validation', purpose='production_validation', cost_usd='.2', status='completed')
    judge = CallEvidence(call_id='judge', purpose='judge', cost_usd='10', status='completed')
    grade = Grade(candidate_id='blind', disposition='PASS', primary=SemanticScore(rubric_id='r',rubric_version='1',
                                                                                 score='1',status='scored',calls=(judge,)))
    r = base.model_copy(update={'calls': (*base.calls, classifier, validation, judge), 'grade':grade})
    report = analyze(run(r, row(strategy='TERRA_BASELINE', cost='2')))
    assert report['strategies']['ROUTER']['effective_cost_per_successful_task_usd'] == Decimal('1.3')
    assert report['strategies']['TERRA_BASELINE']['classifier_cost']['amount'] == 0
    assert report['spend']['experiment_overhead']['amount'] == 10
    assert report['spend']['experiment_inclusive_spend']['amount'] == Decimal('13.3')
    assert report['spend']['total_paid_experiment_spend']['amount'] == 0


def test_unknown_cost_not_zero_and_no_partial_cost_ranking():
    report = analyze(run(row(cost=None), row('b', cost='2')))
    metrics = report['strategies']['ROUTER']
    assert metrics['production_equivalent_cost']['known_subtotal'] == 2
    assert metrics['effective_cost_per_successful_task_usd'] is None
    assert metrics['p50_production_equivalent_cost_usd'] is None


def test_decimal_precision_is_independent_of_callers_context():
    with localcontext() as context:
        context.prec = 2
        report = analyze(run(row(cost='0.123456789123456789'), row('b', state='FAIL', cost='0.000000000000000001')))
    assert report['strategies']['ROUTER']['effective_cost_per_successful_task_usd'] == Decimal('0.123456789123456790')


def test_recovery_cost_retained_and_first_pass_separate():
    base = row(cost='1')
    retry = CallEvidence(call_id='retry', purpose='generation',cost_usd='2',status='completed',attempt_number=2)
    r = base.model_copy(update={'calls':(*base.calls,retry),'recovery_actions':('increase_tier',)})
    metrics = analyze(run(r))['strategies']['ROUTER']
    assert metrics['effective_cost_per_successful_task_usd'] == 3
    assert metrics['first_pass_success']['numerator'] == 0
    assert metrics['final_success']['numerator'] == 1
    assert metrics['router_escalation_rate']['value'] == 1


def test_over_routing_material_generation_cost_candidate():
    report = analyze(run(row(cost='2'), row(strategy='TERRA_BASELINE',cost='1')))
    assert report['comparisons'][0]['over_routing_candidate']
    assert report['comparisons'][0]['observation'] == 'router_more_expensive_both_pass'
    assert report['cheapest_observed_passing'][0]['strategies'] == ['TERRA_BASELINE']


def test_classifier_overhead_alone_does_not_establish_over_routing():
    r = row(cost='.9')
    fee = CallEvidence(call_id='classifier', purpose='classification',cost_usd='10',status='completed')
    report = analyze(run(r.model_copy(update={'calls':(*r.calls,fee)}), row(strategy='TERRA_BASELINE',cost='1')))
    assert not report['comparisons'][0]['over_routing_candidate']


def test_under_routing_requires_stronger_passing_baseline():
    report = analyze(run(row(state='FAIL', initial_model='luna'), row(strategy='TERRA_BASELINE')))
    assert report['comparisons'][0]['under_routing_candidate']
    report = analyze(run(row(state='UNKNOWN', initial_model='luna'), row(strategy='TERRA_BASELINE')))
    assert not report['comparisons'][0]['under_routing_candidate']


def test_incomparable_validation_excluded():
    report = analyze(run(row(), row(strategy='TERRA_BASELINE',validation_signature='different')))
    assert report['comparisons'][0]['observation'] == 'incomparable_validation_or_input'
    assert report['paired_comparisons'][0]['paired_resolved_cases'] == 0
    assert not report['cheapest_observed_passing']


def test_small_sample_and_wilson_are_explicit_not_significance():
    report = analyze(run(row(),row(strategy='TERRA_BASELINE')))
    m = report['strategies']['ROUTER']
    assert m['sample_status'] == 'INSUFFICIENT SAMPLE'
    assert m['pass_rate_interval']['method'] == 'wilson_95'
    assert not report['paired_comparisons'][0]['significance_claim']


def test_segments_do_not_mix_strategies_and_use_initial_route():
    report = analyze(run(row(),row(strategy='TERRA_BASELINE')))
    assert len(report['segments']['task_family']) == 2
    assert len(report['segments']['model']) == 2
    assert len(report['segments']['tags']) == 2


def test_disagreements_exported_even_when_deterministic_wins():
    r = row(grade=Grade(candidate_id='opaque',disposition='PASS',deterministic='PASS',disagreement=True))
    report = analyze(run(r))
    assert len(report['review_queue']) == 1
    assert report['strategies']['ROUTER']['states']['PASS'] == 1


def test_reports_serialize_decimal_strings_and_required_sections():
    report = analyze(run(row(),row(strategy='TERRA_BASELINE')))
    doc = json.loads(json_report(report))
    assert doc['strategies']['ROUTER']['effective_cost_per_successful_task_usd'] == '2'
    markdown = render_markdown(report)
    for section in ['Experiment', 'Corpus', 'Spend', 'Overall results','ROUTER vs TERRA_BASELINE',
                    'Policy observations','Disagreements / needs review','Cost breakdown','Latency','Limitations']:
        assert f'## {section}' in markdown


def test_duplicate_case_strategy_and_cross_strategy_call_id_rejected():
    with pytest.raises(ValueError,match='duplicate'):
        analyze(run(row(),row()))
    r = row()
    with pytest.raises(ValueError,match='shared'):
        analyze(run(r,row(strategy='TERRA_BASELINE',calls=r.calls)))


def test_paired_differences_use_common_resolved_cases():
    report = analyze(run(row(cost='1'),row(strategy='TERRA_BASELINE',cost='2'),row('b',cost='100')))
    pair = report['paired_comparisons'][0]
    assert pair['paired_resolved_cases'] == 1
    assert pair['differences']['ecps_usd']['absolute_router_minus_baseline'] == -1
    assert pair['differences']['ecps_usd']['relative_to_baseline'] == Decimal('-.5')


def test_infrastructure_failure_does_not_establish_under_routing():
    base = row(state='FAIL',initial_model='luna')
    bad = base.calls[0].model_copy(update={'status':'failed','failure_type':'TIMEOUT'})
    report = analyze(run(base.model_copy(update={'calls':(bad,)}),row(strategy='TERRA_BASELINE')))
    assert not report['comparisons'][0]['under_routing_candidate']


def test_completed_call_past_deadline_is_not_under_routing():
    base = row(state='FAIL',initial_model='luna',execution_status='failed')
    report = analyze(run(base,row(strategy='TERRA_BASELINE')))
    assert not report['comparisons'][0]['under_routing_candidate']
