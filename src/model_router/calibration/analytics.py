"""Central, descriptive experimental economics. Money is never a float."""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from math import ceil, sqrt
from model_router.execution.arithmetic import money_sum, money_difference
from .contracts import CalibrationRun, Disposition, StrategyRun

PRODUCTION = frozenset({'classification', 'generation', 'production_validation'})
RESOLVED = frozenset({Disposition.PASS, Disposition.FAIL})


def divide(numerator, denominator):
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = max(80, len(Decimal(numerator).as_tuple().digits) + 30)
        return Decimal(numerator) / Decimal(denominator)


def disposition(row):
    if row.execution_status == 'invalid':
        return Disposition.INVALID
    return row.grade.disposition if row.grade is not None else Disposition.UNKNOWN


def calls(row):
    """One authority per call ID, rejecting conflicting duplicate evidence."""
    evidence = list(row.calls)
    if row.grade is not None:
        for score in (row.grade.primary, row.grade.adjudicator):
            if score is not None:
                evidence.extend(score.calls)
    unique = {}
    for call in evidence:
        previous = unique.get(call.call_id)
        if previous is not None and previous != call:
            raise ValueError('conflicting calibration call evidence')
        unique[call.call_id] = call
    return tuple(unique.values())


def cost(values, *, available=True):
    values = tuple(values)
    missing = sum(value is None for value in values)
    known = money_sum(value for value in values if value is not None)
    return {'amount': known if available and not missing else None,
            'known_subtotal': known, 'missing_count': missing,
            'status': 'unavailable' if not available else 'partial' if missing else 'known'}


def production_cost(row):
    return cost(call.cost_usd for call in calls(row) if call.purpose in PRODUCTION)


def quantile(values, percentile):
    values = sorted(values)
    return values[max(0, ceil(len(values) * percentile) - 1)] if values else None


def rate(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': divide(numerator, denominator)}


def wilson(passed, resolved):
    """Descriptive 95% Wilson score interval for a single binomial proportion."""
    if resolved == 0:
        return None
    z = 1.959963984540054
    p = passed / resolved
    denominator = 1 + z*z / resolved
    center = (p + z*z / (2*resolved)) / denominator
    half = z * sqrt(p*(1-p)/resolved + z*z/(4*resolved*resolved)) / denominator
    return {'method': 'wilson_95', 'low': max(0., center-half), 'high': min(1., center+half),
            'assumption': 'independent representative cases; excludes unresolved outcomes'}


def escalated(row):
    return bool({'increase_effort', 'increase_tier'} & set(row.recovery_actions))


def first_pass(row):
    return (disposition(row) == Disposition.PASS and
            sum(c.purpose == 'generation' for c in calls(row)) == 1 and
            not set(row.recovery_actions) - {'stop_success', 'stop'})


def cohort(rows, minimum):
    rows = tuple(rows)
    counts = Counter(disposition(row) for row in rows)
    resolved = tuple(row for row in rows if disposition(row) in RESOLVED)
    passed = counts[Disposition.PASS]
    costs = [production_cost(row)['amount'] for row in resolved]
    total = cost(costs, available=bool(resolved))
    known = [value for value in costs if value is not None]
    complete = bool(resolved) and len(known) == len(costs)
    all_calls = [call for row in rows for call in calls(row)]
    generations = [row for row in rows if any(c.purpose == 'generation' for c in calls(row))]
    return {
        'cases_recorded': len(rows),
        'cases_attempted': sum(bool(calls(row)) or row.execution_status != 'invalid' for row in rows),
        'resolved_cases': len(resolved),
        'states': {state.value: counts[state] for state in Disposition},
        'pass_rate': rate(passed, len(resolved)),
        'unknown_rate': rate(counts[Disposition.UNKNOWN], len(rows)),
        'unresolved_rate': rate(sum(counts[state] for state in (Disposition.UNKNOWN, Disposition.NEEDS_REVIEW)), len(rows)),
        'first_pass_success': rate(sum(first_pass(row) for row in resolved), len(resolved)),
        'final_success': rate(passed, len(resolved)),
        'production_equivalent_cost': total,
        'mean_production_equivalent_cost_usd': divide(total['amount'], len(resolved)) if complete else None,
        'p50_production_equivalent_cost_usd': quantile(known, .50) if complete else None,
        'p95_production_equivalent_cost_usd': quantile(known, .95) if complete else None,
        'effective_cost_per_successful_task_usd': divide(total['amount'], passed) if complete else None,
        'latency_ms': {'p50': quantile([r.latency_ms for r in generations], .5),
                       'p95': quantile([r.latency_ms for r in generations], .95),
                       'denominator': len(generations), 'scope': 'generation-attempted tasks, excludes calibration grading'},
        'router_escalation_rate': rate(sum(escalated(r) for r in resolved if r.strategy.kind == 'router'),
                                      sum(r.strategy.kind == 'router' for r in resolved)),
        'classifier_cost': cost(c.cost_usd for c in all_calls if c.purpose == 'classification'),
        'experiment_overhead': cost(c.cost_usd for c in all_calls if c.purpose not in PRODUCTION),
        'experiment_inclusive_spend': cost((c.cost_usd for c in all_calls), available=bool(rows)),
        'pass_rate_interval': wilson(passed, len(resolved)),
        'sample_status': 'INSUFFICIENT SAMPLE' if len(resolved) < minimum else 'DESCRIPTIVE ONLY',
        'minimum_cohort_size': minimum,
    }


def comparable(a, b):
    return a.input_sha256 == b.input_sha256 and a.validation_signature == b.validation_signature


def initial_generation_cost(row):
    generation = [c for c in calls(row) if c.purpose == 'generation']
    return generation[0].cost_usd if generation else None


def comparison(router, baseline, catalog, ratio):
    record = {'case_id': router.case_id, 'router': router.strategy.name, 'baseline': baseline.strategy.name,
              'comparable': comparable(router, baseline), 'over_routing_candidate': False,
              'under_routing_candidate': False}
    if not record['comparable']:
        return {**record, 'observation': 'incomparable_validation_or_input'}
    a, b = disposition(router), disposition(baseline)
    if a not in RESOLVED or b not in RESOLVED:
        return {**record, 'observation': 'disagreement_or_unknown'}
    rc, bc = production_cost(router)['amount'], production_cost(baseline)['amount']
    if a == b == Disposition.PASS:
        label = ('both_pass_cost_unknown' if rc is None or bc is None else
                 'router_cheaper_both_pass' if rc < bc else
                 'router_more_expensive_both_pass' if rc > bc else 'equal_cost_both_pass')
    elif a == Disposition.PASS:
        label = 'router_passes_baseline_fails'
    elif b == Disposition.PASS:
        label = 'router_fails_baseline_passes'
    else:
        label = 'both_fail'
    rg, bg = initial_generation_cost(router), initial_generation_cost(baseline)
    if rg is not None and bg is not None and b == Disposition.PASS:
        with localcontext() as context:
            context.prec = 80
            record['over_routing_candidate'] = rg > bg and rg >= bg * ratio
    models = catalog.get('models', {})
    rt = models.get(router.initial_model, {}).get('tier_rank')
    bt = models.get(baseline.initial_model, {}).get('tier_rank')
    quality_failure = any(c.purpose == 'generation' and c.attempt_number == 1 and
                          c.failure_type in {'QUALITY_FAILURE', 'VALIDATION_FAILURE', 'MALFORMED_OUTPUT'} for c in calls(router))
    record['under_routing_candidate'] = bool(first_pass(baseline) and rt is not None and bt is not None and bt > rt and
                                            (escalated(router) or quality_failure or
                                             (a == Disposition.FAIL and router.execution_status == 'completed'
                                              and len([c for c in calls(router) if c.purpose == 'generation']) == 1
                                              and next(c for c in calls(router) if c.purpose == 'generation').status == 'completed')))
    return {**record, 'observation': label, 'router_cost_usd': rc, 'baseline_cost_usd': bc}


def _paired_summary(pairs, rows_by_id, minimum):
    eligible = [p for p in pairs if p['comparable'] and p['observation'] != 'disagreement_or_unknown']
    left = [rows_by_id[(p['case_id'], p['router'])] for p in eligible]
    right = [rows_by_id[(p['case_id'], p['baseline'])] for p in eligible]
    lm, rm = cohort(left, minimum), cohort(right, minimum)
    differences = {}
    for name, a, b in (
        ('pass_rate', lm['pass_rate']['value'], rm['pass_rate']['value']),
        ('ecps_usd', lm['effective_cost_per_successful_task_usd'], rm['effective_cost_per_successful_task_usd']),
        ('mean_cost_usd', lm['mean_production_equivalent_cost_usd'], rm['mean_production_equivalent_cost_usd']),
    ):
        absolute = money_difference(a, b) if a is not None and b is not None else None
        differences[name] = {'absolute_router_minus_baseline': absolute,
                             'relative_to_baseline': divide(absolute, b) if absolute is not None else None}
    return {'paired_resolved_cases': len(eligible), 'excluded_pairs': len(pairs)-len(eligible),
            'observations': dict(Counter(p['observation'] for p in pairs)), 'differences': differences,
            'sample_status': 'INSUFFICIENT SAMPLE' if len(eligible) < minimum else 'DESCRIPTIVE ONLY',
            'significance_claim': False}


def analyze(run: CalibrationRun) -> dict:
    rows = run.strategy_runs
    config = run.manifest.config
    if len({(r.case_id, r.strategy.name) for r in rows}) != len(rows):
        raise ValueError('duplicate case-strategy evidence')
    # IDs are globally unique within a run; shared charges across strategies would
    # make strategy-attributed spend ambiguous and are rejected.
    identities = [c.call_id for row in rows for c in calls(row)]
    if len(identities) != len(set(identities)):
        raise ValueError('call evidence shared across strategies')
    by_strategy = {s.name: cohort([r for r in rows if r.strategy.name == s.name], config.min_cohort_size)
                   for s in config.strategies}
    segmented = {}
    for dimension, field in (('task_family', 'task_family'), ('complexity', 'complexity_band'),
                             ('model', 'initial_model'), ('effort', 'initial_effort'),
                             ('source_kind', 'source_kind'), ('consequence', 'consequence'),
                             ('policy_version', 'policy_version'), ('tags', 'tags')):
        groups = defaultdict(list)
        for row in rows:
            values = getattr(row, field) if field == 'tags' else (getattr(row, field),)
            for value in values or ('unannotated',):
                groups[(str(value) if value is not None else 'unavailable', row.strategy.name)].append(row)
        segmented[dimension] = [{'value': value, 'strategy': strategy, 'metrics': cohort(items, config.min_cohort_size)}
                                for (value, strategy), items in sorted(groups.items())]
    case_rows = defaultdict(list)
    for row in rows:
        case_rows[row.case_id].append(row)
    pairs, cheapest = [], []
    for case_id, items in sorted(case_rows.items()):
        for router in (r for r in items if r.strategy.kind == 'router'):
            for baseline in (r for r in items if r.strategy.kind == 'fixed'):
                pairs.append(comparison(router, baseline, run.manifest.model_catalog, config.material_cost_ratio))
        compatible_groups = defaultdict(list)
        for row in items:
            compatible_groups[(row.input_sha256, row.validation_signature)].append(row)
        for (_, signature), tested in compatible_groups.items():
            passed = [r for r in tested if disposition(r) == Disposition.PASS]
            observed = [(r, production_cost(r)['amount']) for r in passed]
            if len(tested) < 2 or not observed or any(amount is None for _, amount in observed):
                continue
            minimum = min(amount for _, amount in observed)
            cheapest.append({'case_id': case_id, 'validation_signature': signature,
                             'strategies': [r.strategy.name for r, amount in observed if amount == minimum],
                             'production_equivalent_cost_usd': minimum,
                             'tested_strategies': len(tested), 'passing_strategies': len(passed),
                             'scope': 'cheapest observed passing strategy among comparable tested strategies only'})
    all_calls = [c for r in rows for c in calls(r)]
    review = [{'case_id': r.case_id, 'strategy': r.strategy.name,
               'candidate_id': r.grade.candidate_id if r.grade else None,
               'output_reference': r.grade.output_reference if r.grade else None,
               'disposition': disposition(r).value,
               'grade': r.grade.model_dump(mode='json') if r.grade else None}
              for r in rows if disposition(r) not in RESOLVED or (r.grade and (r.grade.disagreement or r.grade.human_review_needed))]
    pair_groups = defaultdict(list)
    for pair in pairs:
        pair_groups[(pair['router'], pair['baseline'])].append(pair)
    by_id = {(r.case_id, r.strategy.name): r for r in rows}
    return {
        'schema_version': 1,
        'experiment': {'run_id': run.manifest.run_id, 'created_at': run.manifest.created_at.isoformat(),
                       'offline': run.manifest.offline, 'status': run.status, 'stop_reason': run.stop_reason,
                       'software_commit': run.manifest.software_commit, 'policy_version': run.manifest.policy_version,
                       'policy_sha256': run.manifest.policy_sha256, 'config_version': config.version, 'seed': config.seed},
        'corpus': run.manifest.corpus.model_dump(mode='json'),
        'denominators': {'resolved': 'PASS + FAIL; UNKNOWN, NEEDS_REVIEW and INVALID excluded',
                         'ecps': 'all resolved production-equivalent cost / resolved PASS count; failed work included',
                         'unknown': 'UNKNOWN / all case-strategy records; NEEDS_REVIEW and INVALID reported separately',
                         'missing_cost': 'any missing included cost makes aggregate cost and ECPS unavailable',
                         'paired': 'same case, identical input and validation; both results resolved'},
        'spend': {'production_equivalent_all_attempted': cost((c.cost_usd for c in all_calls if c.purpose in PRODUCTION), available=bool(rows)),
                  'experiment_overhead': cost(c.cost_usd for c in all_calls if c.purpose not in PRODUCTION),
                  'experiment_inclusive_spend': cost((c.cost_usd for c in all_calls), available=bool(rows)),
                  'total_paid_experiment_spend': cost((c.cost_usd for c in all_calls), available=bool(rows)) if not run.manifest.offline else cost(()),
                  'offline_costs_are_simulated': run.manifest.offline,
                  'by_purpose': {purpose: cost(c.cost_usd for c in all_calls if c.purpose == purpose)
                                 for purpose in sorted(PRODUCTION | {'judge', 'adjudication'})}},
        'strategies': by_strategy, 'segments': segmented, 'comparisons': pairs,
        'paired_comparisons': [{'router': names[0], 'baseline': names[1], **_paired_summary(items, by_id, config.min_cohort_size)}
                               for names, items in sorted(pair_groups.items())],
        'cheapest_observed_passing': cheapest, 'review_queue': review,
        'policy_observations': {'over_routing_candidates': [p for p in pairs if p['over_routing_candidate']],
                                'under_routing_candidates': [p for p in pairs if p['under_routing_candidate']],
                                'automatic_policy_change': False},
        'limitations': ['Synthetic/sample corpus proves harness behavior, not real benchmark performance.',
                       'Model judging is fallible; disagreements and unresolved evidence remain visible.',
                       'Observed cheapest success does not establish how untested routes would perform.',
                       'Over/under-routing candidates are descriptive observations, never automatic policy recommendations.',
                       'Wilson intervals assume independent representative cases; no automatic significance claim.',
                       'Model/effort segmentation attributes downstream cost to initial route; spend uses actual calls.'],
    }
