import { AlertTriangle, CheckCircle2, Scale } from 'lucide-react'
import { api } from '../api'
import type { Cohort, Cost } from '../api-types'
import { DataFootnote, EmptyState, ErrorState, Kpi, LoadingState, PageHeader, Panel, PartialMark, SyntheticBanner } from '../components/Primitives'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatCost, formatLatency, formatRate, shortModel } from '../format'

export default function EfficacyPage() {
  const { filters } = useDashboard(); const key = filterKey(filters)
  const state = useAsync(async (signal) => {
    const [efficacy, policies] = await Promise.all([api.efficacy(filters, signal), api.policies(filters, signal)])
    return { efficacy, policies }
  }, [key])
  if (state.loading) return <><PageHeader eyebrow="Economics × outcomes" title="Efficacy" description="The cost of successful work across model, effort, and policy cohorts."/><LoadingState/></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const { efficacy, policies } = state.data
  return <>
    <PageHeader eyebrow="Economics × outcomes" title="Efficacy" description="The cost of successful work across model, effort, and policy cohorts."/>
    <SyntheticBanner meta={efficacy.meta}/>
    <Panel title="Model and effort cohorts" subtitle="Production spend includes all eligible failed-task cost">
      {efficacy.cohorts.length ? <div className="efficacy-cards">{efficacy.cohorts.map((cohort) => <CohortCard key={cohort.key} cohort={cohort}/>)}</div> : <EmptyState title="No efficacy data yet" detail="No model and effort cohort has eligible terminal-task evidence."/>}
    </Panel>
    <Panel title="Economic comparison" subtitle="Use outcome and evidence quality together">
      {efficacy.cohorts.length ? <CohortTable cohorts={efficacy.cohorts}/> : <EmptyState title="No comparable cohorts" detail="Comparison requires task outcomes and cost evidence."/>}
    </Panel>
    <Panel title="Policy comparison" subtitle={policies.comparison_note}>
      {policies.cohorts.length ? <CohortTable cohorts={policies.cohorts} policy/> : <EmptyState title="No policy cohorts" detail="No policy-attributed tasks match this window."/>}
    </Panel>
    <DataFootnote meta={efficacy.meta}/>
  </>
}

function CohortCard({ cohort }: { cohort: Cohort }) {
  const metrics = cohort.metrics
  return <article className="cohort-card">
    <header><div><strong>{shortModel(cohort.model)}</strong><span>{cohort.effort ?? 'unspecified effort'}</span></div>{cohort.insufficient_sample && <span className="sample-warning"><AlertTriangle size={13}/> Small sample</span>}</header>
    <div className="cohort-hero"><span>Effective cost / success</span><b>{formatCost(metrics.effective_cost_per_success)}</b><PartialMark cost={metrics.effective_cost_per_success}/></div>
    <dl><div><dt>Tasks</dt><dd>{metrics.total_tasks}</dd></div><div><dt>First pass</dt><dd>{formatRate(metrics.first_pass_success)}</dd></div><div><dt>Final success</dt><dd>{formatRate(metrics.final_success)}</dd></div><div><dt>Escalation</dt><dd>{formatRate(metrics.escalation_rate)}</dd></div><div><dt>Avg. task cost</dt><dd>{formatCost(metrics.cost_per_task)}</dd></div><div><dt>P95 latency</dt><dd>{formatLatency(metrics.p95_latency_ms)}</dd></div></dl>
    <QualitySummary cohort={cohort}/>
  </article>
}

function QualitySummary({ cohort }: { cohort: Cohort }) {
  const quality = cohort.quality
  const reason = quality.reason === 'no_comparable_evaluator_scores'
    ? 'No comparable evaluator scores in this cohort.'
    : 'Evaluator evidence uses different rubrics, checks, or score scales.'
  if (!quality.comparable) return <div className="quality-note quality-incomparable"><Scale size={15}/><span><strong>Quality not comparable</strong>{reason}</span></div>
  if (!quality.groups.length) return <div className="quality-note"><span><strong>Evaluator result unknown</strong>No compatible scored evidence.</span></div>
  return <div className="quality-note quality-comparable"><CheckCircle2 size={15}/><span><strong>Within-rubric evaluator score</strong>{quality.groups.map((group) => `${group.rubric_version} · ${group.check} · ${group.mean.toFixed(2)} on ${group.score_min}–${group.score_max} · ${group.sample_size} evaluated attempts · ${group.role}`).join('; ')}. Scores from different rubrics or checks must not be compared.</span></div>
}

function CohortTable({ cohorts, policy = false }: { cohorts: Cohort[]; policy?: boolean }) {
  return <div className="table-scroll" role="region" aria-label={policy ? 'Policy efficacy comparison' : 'Model efficacy comparison'} tabIndex={0}>
    <table><thead><tr><th scope="col">{policy ? 'Policy' : 'Route'}</th><th scope="col">Tasks</th><th scope="col">First pass</th><th scope="col">Final success</th><th scope="col">Escalation</th><th scope="col">Cost / task</th><th scope="col">Effective cost / success</th><th scope="col">P50 / P95</th><th scope="col">Evidence</th></tr></thead>
      <tbody>{cohorts.map((cohort) => <tr key={cohort.key}><th scope="row"><strong>{policy ? cohort.policy_version ?? cohort.key : shortModel(cohort.model)}</strong>{!policy && <small>{cohort.effort ?? '—'}</small>}</th><td>{cohort.metrics.total_tasks}</td><td>{formatRate(cohort.metrics.first_pass_success)}</td><td>{formatRate(cohort.metrics.final_success)}</td><td>{formatRate(cohort.metrics.escalation_rate)}</td><td><CostCell cost={cohort.metrics.cost_per_task}/></td><td className="emphasis-cell"><CostCell cost={cohort.metrics.effective_cost_per_success}/></td><td>{formatLatency(cohort.metrics.p50_latency_ms)} / {formatLatency(cohort.metrics.p95_latency_ms)}</td><td className="cohort-evidence">{cohort.insufficient_sample && <span className="sample-warning"><AlertTriangle size={13}/>Insufficient sample</span>}<QualitySummary cohort={cohort}/></td></tr>)}</tbody>
    </table>
  </div>
}

function CostCell({ cost }: { cost: Cost }) { return <>{formatCost(cost)} <PartialMark cost={cost}/></> }
