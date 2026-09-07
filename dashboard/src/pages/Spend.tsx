import { api } from '../api'
import { ChartSummary, DataFootnote, EmptyState, ErrorState, Kpi, LoadingState, PageHeader, Panel, PartialMark, SyntheticBanner } from '../components/Primitives'
import { HorizontalBars, MultiLineChart, TrendChart } from '../components/Charts'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatCost, plotCost } from '../format'
import type { SpendGroup } from '../api-types'

export default function SpendPage() {
  const { filters } = useDashboard(); const key = filterKey(filters)
  const state = useAsync((signal) => api.spend(filters, signal), [key])
  if (state.loading) return <><PageHeader eyebrow="Economics" title="Spend" description="Where production cost accumulates, with shadow activity held apart."/><LoadingState/></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const spend = state.data
  const series = spend.series.map((point) => ({ date: point.date, production: plotCost(point.production), shadow: plotCost(point.shadow), cumulative: plotCost(point.cumulative_production) }))
  const hasDailySpend = series.some((point) => point.production !== null || point.shadow !== null)
  const hasCumulativeSpend = series.some((point) => point.cumulative !== null)
  return <>
    <PageHeader eyebrow="Economics" title="Spend" description="Where production cost accumulates, with shadow activity held apart."/>
    <SyntheticBanner meta={spend.meta}/>
    <section className="kpi-grid four"><Kpi label="Production spend" value={spend.production} featured/><Kpi label="Shadow spend" value={spend.shadow} detail="Excluded from production task cost"/><Kpi label="All observed spend" value={spend.all_spend}/><Kpi label="Unallocated spend" value={spend.unallocated} detail="Timestamp or correlation unavailable"/></section>
    <div className="dashboard-grid two-thirds">
      <Panel title="Daily spend" subtitle="Production and shadow shown separately · partial points use known subtotal" className="span-2">
        {hasDailySpend ? <><MultiLineChart data={series} lines={[{ key: 'production', label: 'Production' }, { key: 'shadow', label: 'Shadow' }]} valueLabel={(value) => `$${value.toFixed(2)}`}/><ChartSummary>Production total {formatCost(spend.production)}. Shadow total {formatCost(spend.shadow)} and is excluded from production totals.</ChartSummary></> : <EmptyState title="No spend data yet" detail="No charge evidence was placed in this window."/>}
      </Panel>
      <Panel title="Cumulative production" subtitle="Selected UTC window · partial points use known subtotal">
        {hasCumulativeSpend ? <><TrendChart data={series} yKey="cumulative" valueLabel={(value) => `$${value.toFixed(2)}`}/><ChartSummary>Cumulative production spend ends at {formatCost(spend.production)}.</ChartSummary></> : <EmptyState title="No cumulative spend" detail="Cumulative spend needs attributable production charges."/>}
      </Panel>
      <SpendBreakdown title="By model" groups={spend.by_model}/><SpendBreakdown title="By task family" groups={spend.by_task_family}/><SpendBreakdown title="By application" groups={spend.by_application}/>
      <SpendBreakdown title="By reasoning effort" groups={spend.by_effort}/><SpendBreakdown title="By policy" groups={spend.by_policy}/><SpendBreakdown title="By attempt purpose" groups={spend.by_purpose}/>
      <SpendBreakdown title="Generation, validation, and retry" groups={spend.by_contribution} className="span-2"/>
    </div>
    <DataFootnote meta={spend.meta}/>
  </>
}

function SpendBreakdown({ title, groups, className }: { title: string; groups: SpendGroup[]; className?: string }) {
  return <Panel title={title} subtitle="Historical charge evidence" className={className}>
    {groups.length ? <><HorizontalBars data={groups.flatMap((group) => { const value = plotCost(group.cost); return value === null ? [] : [{key: group.key, value}] })} valueLabel={(value) => `$${value.toFixed(3)}`}/><ChartSummary>{groups.map((group) => `${group.key}: ${formatCost(group.cost)} across ${group.count} charges`).join('. ')}</ChartSummary><div className="legend-list">{groups.map((group) => <div key={group.key}><span>{group.key}<small>{group.count} records</small></span><strong>{formatCost(group.cost)} <PartialMark cost={group.cost}/></strong></div>)}</div></> : <EmptyState title={`No ${title.toLowerCase()} data`} detail="No attributable charges match the selected filters."/>}
  </Panel>
}
