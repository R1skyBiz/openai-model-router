import { Clock3, Database, Gauge, RadioTower, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import { DataFootnote, EmptyState, ErrorState, Kpi, LoadingState, PageHeader, Panel, StateBadge, SyntheticBanner } from '../components/Primitives'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatDate, formatLatency, formatRate, shortModel } from '../format'

export default function HealthPage() {
  const { filters } = useDashboard(); const key = filterKey(filters)
  const state = useAsync((signal) => api.health(filters, signal), [key])
  if (state.loading) return <><PageHeader eyebrow="Retained evidence" title="Health" description="Operational signals from stored snapshots. Opening this page never runs a probe."/><LoadingState/></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const health = state.data
  return <>
    <PageHeader eyebrow="Retained evidence" title="Health" description="Operational signals from stored snapshots. Opening this page never runs a probe." action={<StateBadge state={health.state}/>}/>
    <SyntheticBanner meta={health.meta}/>
    <section className={`readiness-callout readiness-${health.state.toLowerCase()}`}><ShieldAlert aria-hidden="true"/><div><span>Overall readiness</span><h2>{health.state}</h2><p>{health.readiness_note}</p></div><div className="production-lock"><strong>Production readiness</strong><span>{health.production_ready ? 'Ready' : 'Not established'}</span></div></section>
    <section className="kpi-grid four"><Kpi label="Failure rate" value={health.failure_rate}/><Kpi label="P50 latency" value={formatLatency(health.p50_latency_ms)}/><Kpi label="P95 latency" value={formatLatency(health.p95_latency_ms)}/><Kpi label="Outbox pending" value={health.outbox_pending} detail={health.oldest_pending_at ? `Oldest ${formatDate(health.oldest_pending_at)}` : 'No pending age'}/></section>
    <div className="dashboard-grid two-thirds">
      <Panel title="Components" subtitle="Snapshot freshness, circuit, and observed state" className="span-2">
        {health.components.length ? <div className="health-components">{health.components.map((component, index) => <article key={`${component.component}-${component.model}-${index}`}><div className="component-icon">{component.component.toLowerCase().includes('database') ? <Database/> : component.component.toLowerCase().includes('telemetry') ? <RadioTower/> : <Gauge/>}</div><div className="component-title"><strong>{component.component}</strong><small>{component.model ? shortModel(component.model) : component.capability ?? (component.required ? 'Required' : 'Optional')}</small></div><StateBadge state={component.state}/><dl><div><dt>Observed</dt><dd>{formatDate(component.observed_at)}</dd></div><div><dt>Valid until</dt><dd>{formatDate(component.valid_until)}</dd></div><div><dt>Circuit</dt><dd>{component.circuit_state || 'Unknown'}</dd></div><div><dt>Failures</dt><dd>{component.failure_count}</dd></div><div><dt>Latency</dt><dd>{formatLatency(component.latency_ms)}</dd></div></dl></article>)}</div> : <EmptyState title="No health snapshots" detail="Operational readiness is unknown until retained evidence is available."/>}
      </Panel>
      <Panel title="Observed incidents" subtitle="Selected window">
        <div className="incident-metrics"><div><ShieldAlert/><span><strong>{health.timeouts}</strong>Timeouts</span></div><div><Clock3/><span><strong>{health.rate_limits}</strong>Rate limits</span></div><div><Gauge/><span><strong>{formatRate(health.failure_rate)}</strong>Failure rate</span></div></div>
      </Panel>
      <Panel title="Degraded periods" subtitle="Retained observation intervals, not continuous outage measurements" className="span-3">
        {health.degraded_periods.length ? <div className="period-list">{health.degraded_periods.map((period, index) => <div key={`${period.component}-${period.start}-${index}`}><span className="period-line"/><StateBadge state={period.state}/><strong>{period.component}</strong><span>{formatDate(period.start)} → {period.end ? formatDate(period.end) : 'Ongoing'}</span></div>)}</div> : <EmptyState title="No degraded periods" detail="No retained degradation interval matches the selected window."/>}
      </Panel>
    </div>
    <DataFootnote meta={health.meta}/>
  </>
}
