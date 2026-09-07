import { ArrowRight, CornerDownRight } from 'lucide-react'
import { api } from '../api'
import { ChartSummary, DataFootnote, EmptyState, ErrorState, Kpi, LoadingState, PageHeader, Panel, SyntheticBanner } from '../components/Primitives'
import { HorizontalBars, MultiLineChart } from '../components/Charts'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatRate, shortModel } from '../format'
import type { Distribution, Flow } from '../api-types'

export default function RoutingPage() {
  const { filters } = useDashboard(); const key = filterKey(filters)
  const state = useAsync((signal) => api.routing(filters, signal), [key])
  if (state.loading) return <><PageHeader eyebrow="Decisions" title="Routing" description="How admitted work moves from classification to a final execution route."/><LoadingState/></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const routing = state.data
  return <>
    <PageHeader eyebrow="Decisions" title="Routing" description="How admitted work moves from classification to a final execution route."/>
    <SyntheticBanner meta={routing.meta}/>
    <section className="kpi-grid two"><Kpi label="Preferred-floor relaxation" value={routing.preferred_floor_relaxation}/><Kpi label="Constrained fallback" value={routing.constrained_fallback}/></section>
    <div className="dashboard-grid thirds">
      <DistributionPanel title="Model distribution" items={routing.models} label={shortModel}/><DistributionPanel title="Reasoning effort" items={routing.efforts}/><DistributionPanel title="Complexity" items={routing.complexities}/>
      <Panel title="Task family → model" subtitle="Initial generation route" className="span-2">
        {routing.family_model_flow.length ? <FlowList flows={routing.family_model_flow}/> : <EmptyState title="No family flow yet" detail="No classified routes match the selected cohort."/>}
      </Panel>
      <Panel title="Escalation flow" subtitle="Intelligence route changes">
        {routing.escalation_flow.length ? <FlowList flows={routing.escalation_flow}/> : <EmptyState title="No escalation flow" detail="No task in this cohort required intelligence escalation."/>}
      </Panel>
      <DistributionPanel title="Routing rationale" items={routing.rationale_codes} className="span-2"/>
      <DistributionPanel title="Validation distribution" items={routing.validations}/>
      <Panel title="Success trend" subtitle="Task-level outcomes" className="span-3">
        {routing.trend.some(point => point.final_success.value !== null || point.first_pass_success.value !== null) ? <><MultiLineChart data={routing.trend.map((point) => ({ date: point.date, firstPass: point.first_pass_success.value == null ? null : point.first_pass_success.value * 100, final: point.final_success.value == null ? null : point.final_success.value * 100 }))} lines={[{key:'firstPass', label:'First pass'}, {key:'final', label:'Final'}]} valueLabel={(value) => `${value.toFixed(0)}%`}/><ChartSummary>{routing.trend.map((point) => `${point.date}: first pass ${formatRate(point.first_pass_success)}, final ${formatRate(point.final_success)}`).join('. ')}</ChartSummary></> : <EmptyState title="No routing trend yet" detail="Trend data will appear once tasks reach terminal outcomes."/>}
      </Panel>
    </div>
    <DataFootnote meta={routing.meta}/>
  </>
}

function DistributionPanel({ title, items, label = (key) => key, className }: { title: string; items: Distribution[]; label?: (key: string) => string; className?: string }) {
  return <Panel title={title} subtitle="Task-level share" className={className}>{items.length ? <><HorizontalBars data={items.map((item) => ({ key: label(item.key), value: item.count }))}/><ChartSummary>{items.map((item) => `${label(item.key)}: ${item.count}, ${item.share == null ? 'unknown share' : `${(item.share * 100).toFixed(1)} percent`}`).join('. ')}</ChartSummary><div className="distribution-key">{items.map((item) => <span key={item.key}><b>{label(item.key)}</b><small>{item.count} · {item.share == null ? '—' : `${(item.share * 100).toFixed(1)}%`}</small></span>)}</div></> : <EmptyState title={`No ${title.toLowerCase()}`} detail="No eligible routing evidence matches this view."/>}</Panel>
}

function FlowList({ flows }: { flows: Flow[] }) {
  const max = Math.max(...flows.map((flow) => flow.count), 1)
  return <div className="flow-list">{flows.slice(0, 12).map((flow, index) => <div className="flow-row" key={`${flow.source}-${flow.target}-${index}`}><span>{flow.source}</span><div className="flow-path"><CornerDownRight size={14}/><i style={{ width: `${Math.max(10, flow.count / max * 100)}%` }}/><ArrowRight size={14}/></div><strong>{flow.target}<small>{flow.count}</small></strong></div>)}</div>
}
