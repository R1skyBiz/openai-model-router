import { ArrowRight, GitBranch, Lightbulb, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ChartSummary, DataFootnote, EmptyState, ErrorState, Kpi, LoadingState, PageHeader, Panel, StateBadge, SyntheticBanner } from '../components/Primitives'
import { HorizontalBars, MultiLineChart, TrendChart } from '../components/Charts'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatCost, formatDate, formatRate, plotCost, shortModel } from '../format'

export default function Overview() {
  const { filters } = useDashboard()
  const key = filterKey(filters)
  const state = useAsync(async (signal) => {
    const [summary, spend, routing, health, tasks] = await Promise.all([
      api.summary(filters, signal), api.spend(filters, signal), api.routing(filters, signal), api.health(filters, signal), api.tasks(filters, 0, 100, signal),
    ])
    return { summary, spend, routing, health, tasks }
  }, [key])

  if (state.loading) return <><PageHeader eyebrow="Telemetry" title="Overview" description="A concise read on economics, routing quality, and operating health."/><LoadingState /></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const { summary, spend, routing, health, tasks } = state.data
  const m = summary.metrics
  const spendSeries = spend.series.map((point) => ({ date: point.date, production: plotCost(point.production), cumulative: plotCost(point.cumulative_production) }))
  const hasSpendSeries = spendSeries.some((point) => point.production !== null)
  const routingTrend = routing.trend.map((point) => ({ date: point.date, success: point.final_success.value == null ? null : point.final_success.value * 100, firstPass: point.first_pass_success.value == null ? null : point.first_pass_success.value * 100 }))
  const modelMix = routing.models.map((item) => ({ key: shortModel(item.key), value: item.count }))

  return <>
    <PageHeader eyebrow="Telemetry" title="Overview" description="A concise read on economics, routing quality, and operating health." action={<StateBadge state={health.state} />}/>
    <SyntheticBanner meta={summary.meta}/>
    <section className="kpi-grid overview-kpis" aria-label="Key performance indicators">
      <Kpi label="Spend today" value={summary.spend_today}/><Kpi label="Spend MTD" value={summary.spend_mtd}/><Kpi label="Projected month" value={summary.projected_month} detail={summary.forecast_method === 'linear_mtd_run_rate' ? 'Linear month-to-date estimate' : summary.forecast_method.replaceAll('_', ' ')}/>
      <Kpi label="Successful tasks" value={m.successful_tasks}/><Kpi label="First-pass success" value={m.first_pass_success}/><Kpi label="Effective cost / success" value={m.effective_cost_per_success} featured/>
      <Kpi label="Escalation rate" value={m.escalation_rate}/><Kpi label="System health" value={health.state} detail={health.production_ready ? undefined : health.readiness_note} tone={health.state.toLowerCase()}/>
    </section>
    <p className="cohort-note">Selected cohort: {m.total_tasks} tasks · {m.terminal_tasks} terminal · {m.pending_tasks} pending (including {m.blocked_tasks} blocked). Cancelled tasks remain in success denominators.</p>
    <div className="dashboard-grid two-thirds">
      <Panel title="Spend over time" subtitle="Production charges · UTC · partial points show known spend" action={<Link className="panel-link" to="/spend">Details <ArrowRight size={14}/></Link>}>
        {hasSpendSeries ? <><TrendChart data={spendSeries} yKey="production" valueLabel={(value) => `$${value.toFixed(2)}`}/><ChartSummary>Daily production spend from {spend.series[0]?.date} through {spend.series.at(-1)?.date}. Total {formatCost(spend.production)}. Shadow spend is excluded.</ChartSummary></> : <EmptyState title="No spend data yet" detail="No production charges were observed in this window."/>}
      </Panel>
      <Panel title="Model mix" subtitle="Initial generation routes">
        {modelMix.length ? <><HorizontalBars data={modelMix}/><ChartSummary>{routing.models.map((item) => `${item.key}: ${item.count} tasks`).join('. ')}</ChartSummary></> : <EmptyState title="No routing data yet" detail="No admitted tasks match the selected filters."/>}
      </Panel>
      <Panel title="Success trend" subtitle="Final and first-pass task success">
        {routingTrend.some(point => point.success !== null || point.firstPass !== null) ? <><MultiLineChart data={routingTrend} lines={[{ key: 'success', label: 'Final success' }, { key: 'firstPass', label: 'First-pass success' }]} valueLabel={(value) => `${value.toFixed(0)}%`}/><ChartSummary>{routing.trend.map((point) => `${point.date}: final ${formatRate(point.final_success)}, first pass ${formatRate(point.first_pass_success)}`).join('. ')}</ChartSummary></> : <EmptyState title="No success trend yet" detail="Trend data will appear after terminal tasks are recorded."/>}
      </Panel>
      <Panel title="Effective cost / success" subtitle="Includes failed work · partial points show known spend">
        {routing.trend.some(point => plotCost(point.effective_cost_per_success) !== null) ? <><TrendChart data={routing.trend.map((point) => ({ date: point.date, value: plotCost(point.effective_cost_per_success) }))} valueLabel={(value) => `$${value.toFixed(3)}`}/><ChartSummary>Effective cost per successful task over time. Unknown points are omitted.</ChartSummary></> : <EmptyState title="No efficacy data yet" detail="This measure requires successful tasks and attributable spend."/>}
      </Panel>
    </div>
    <div className="dashboard-grid thirds">
      <Panel title="Recent tasks" subtitle="Newest admitted tasks" className="span-2">
        {tasks.items.length ? <div className="compact-list">{tasks.items.slice(0, 6).map((task) => <Link to={`/tasks/${task.task_id}`} key={task.task_id} className="compact-row"><div><strong>{task.task_family ?? 'Unclassified task'}</strong><small>{formatDate(task.created_at)} · {task.application ?? 'Unknown app'}</small></div><div className="compact-route"><span>{shortModel(task.model)} · {task.effort ?? '—'}</span><StateBadge state={task.status}/></div></Link>)}</div> : <EmptyState title="No recent tasks" detail="No tasks match the current cohort."/>}
      </Panel>
      <Panel title="Current health" subtitle="Retained evidence only">
        <div className="health-callout"><ShieldCheck aria-hidden="true"/><StateBadge state={health.state}/><p>{health.readiness_note}</p><Link to="/health">Inspect evidence <ArrowRight size={14}/></Link></div>
      </Panel>
      <Panel title="Recent escalations" subtitle="Among the 100 newest tasks">
        {tasks.items.some((task) => task.escalated) ? <div className="compact-list">{tasks.items.filter((task) => task.escalated).slice(0, 4).map((task) => <Link to={`/tasks/${task.task_id}`} key={task.task_id} className="compact-row"><GitBranch size={16}/><div><strong>{task.task_family ?? task.task_id}</strong><small>{formatDate(task.created_at)} · {shortModel(task.model)} · {formatCost(task.cost)}</small></div></Link>)}</div> : <EmptyState title="No recent escalations" detail="No escalation appears among the 100 newest matching tasks."/>}
      </Panel>
      <Panel title="Policy version" subtitle="Immutable decision policy">
        <div className="policy-list">{summary.policy_versions.length ? summary.policy_versions.map((policy) => <span key={policy}>{policy}</span>) : <span>Unknown</span>}</div><Link className="panel-link standalone" to="/efficacy">Compare policy cohorts <ArrowRight size={14}/></Link>
      </Panel>
      <Panel title="Highest-spend families" subtitle="Ranked by known production spend">
        {spend.by_task_family.length ? <div className="legend-list">{spend.by_task_family.slice(0, 5).map((group) => <div key={group.key}><span>{group.key}<small>{group.count} records</small></span><strong>{formatCost(group.cost)}</strong></div>)}</div> : <EmptyState title="No family spend" detail="No attributed task-family charges match this window."/>}
      </Panel>
      <Panel title="Optimization observations" subtitle="Evidence-led, never self-modifying">
        <div className="placeholder-observation"><Lightbulb size={18}/><p>Deterministic observations will appear when comparable cohorts have sufficient evidence.</p></div>
      </Panel>
    </div>
    <DataFootnote meta={summary.meta}/>
  </>
}
