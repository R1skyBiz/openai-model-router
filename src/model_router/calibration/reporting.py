"""Portable JSON and Markdown over backend-owned formulas."""
from decimal import Decimal
import json


def json_report(report):
    return json.dumps(report, default=lambda v: str(v) if isinstance(v, Decimal) else _unsupported(v),
                      indent=2, sort_keys=True, allow_nan=False) + '\n'


def _unsupported(value):
    raise TypeError('unsupported report value')


def _text(value):
    if value is None:
        return 'unavailable'
    if isinstance(value, Decimal):
        return format(value, '.8g')
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;').replace('>', '&gt;')


def _table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |',
                      *['| ' + ' | '.join(_text(v) for v in row) + ' |' for row in rows]])


def render_markdown(report):
    experiment, corpus, spend = report['experiment'], report['corpus'], report['spend']
    lines = ['# Calibration Lab report', '', '## Experiment', '',
             f"Run: `{_text(experiment['run_id'])}`. Status: {_text(experiment['status'])}.",
             f"Mode: {'OFFLINE — costs are simulated, not paid' if experiment['offline'] else 'LIVE'}.",
             f"Policy: `{_text(experiment['policy_version'])}`; seed: {experiment['seed']}.",
             '', '## Corpus', '',
             f"Version: `{_text(corpus['corpus_version'])}`. Cases: {corpus['case_count']}. Privacy: {_text(corpus['privacy'])}.",
             f"SHA-256: `{_text(corpus['corpus_sha256'])}`.", '',
             'Synthetic/sample cases exercise the harness; they are not evidence of real workload performance.',
             '', 'Numbers display up to eight significant digits; JSON retains full decimal precision.',
             '', '## Spend', '',
             _table(['Measure', 'USD', 'Known subtotal', 'Completeness'],
                    [(name, value['amount'], value['known_subtotal'], value['status'])
                     for name, value in spend.items() if isinstance(value, dict) and 'amount' in value]),
             '', '## Overall results', '',
             _table(['Strategy', 'Attempted', 'Resolved', 'PASS', 'FAIL', 'UNKNOWN', 'NEEDS_REVIEW', 'ECPS USD', 'Sample'],
                    [(name, m['cases_attempted'], m['resolved_cases'], m['states']['PASS'], m['states']['FAIL'],
                      m['states']['UNKNOWN'], m['states']['NEEDS_REVIEW'], m['effective_cost_per_successful_task_usd'],
                      m['sample_status']) for name, m in report['strategies'].items()]), '',
             'ECPS includes failed resolved work and recovery. UNKNOWN, NEEDS_REVIEW and INVALID are excluded from resolved denominators. Missing included costs make ECPS unavailable.']
    for pair in report['paired_comparisons']:
        lines.extend(['', f"## {_text(pair['router'])} vs {_text(pair['baseline'])}", '',
                      f"Paired resolved cases: {pair['paired_resolved_cases']}; excluded: {pair['excluded_pairs']}. {pair['sample_status']}.", '',
                      _table(['Metric', 'Absolute Router minus baseline', 'Relative to baseline'],
                             [(key, value['absolute_router_minus_baseline'], value['relative_to_baseline'])
                              for key, value in pair['differences'].items()]), '',
                      _table(['Observation', 'Count'], pair['observations'].items())])
    for key, title in [('task_family', 'By task family'), ('complexity', 'By complexity')]:
        lines.extend(['', f'## {title}', '',
                      _table(['Cohort', 'Strategy', 'Resolved', 'PASS', 'ECPS USD', 'Sample'],
                             [(s['value'], s['strategy'], s['metrics']['resolved_cases'], s['metrics']['states']['PASS'],
                               s['metrics']['effective_cost_per_successful_task_usd'], s['metrics']['sample_status'])
                              for s in report['segments'][key]])])
    lines.extend(['', '## Policy observations', '',
                  'Descriptive observations only. No policy change or recommendation is applied.'])
    for key, title in [('over_routing_candidates', 'Over-routing candidates'), ('under_routing_candidates', 'Under-routing candidates')]:
        values = report['policy_observations'][key]
        lines.extend(['', f'### {title}', '',
                      _table(['Case', 'Router', 'Baseline', 'Observation'],
                             [(v['case_id'], v['router'], v['baseline'], v['observation']) for v in values]) if values else 'None observed.'])
    lines.extend(['', '## Cheapest observed passing strategies', '',
                  _table(['Case', 'Observed strategies', 'Production USD', 'Strategies tested'],
                         [(r['case_id'], ', '.join(r['strategies']), r['production_equivalent_cost_usd'], r['tested_strategies'])
                          for r in report['cheapest_observed_passing']]),
                  '', 'Untested routes remain unobserved; this establishes no causal optimum.',
                  '', '## Disagreements / needs review', '',
                  _table(['Case', 'Strategy', 'Blind candidate', 'Disposition'],
                         [(r['case_id'], r['strategy'], r['candidate_id'], r['disposition']) for r in report['review_queue']]),
                  '', 'Full deterministic/primary/adjudicator evidence is in the JSON review queue.',
                  '', '## Cost breakdown', '',
                  _table(['Purpose', 'USD', 'Known subtotal'],
                         [(p, c['amount'], c['known_subtotal']) for p, c in spend['by_purpose'].items()]),
                  '', '## Latency', '',
                  _table(['Strategy', 'P50 ms', 'P95 ms', 'Tasks'],
                         [(name, m['latency_ms']['p50'], m['latency_ms']['p95'], m['latency_ms']['denominator'])
                          for name, m in report['strategies'].items()]),
                  '', '## Limitations', '', *['- ' + note for note in report['limitations']], ''])
    return '\n'.join(lines)
