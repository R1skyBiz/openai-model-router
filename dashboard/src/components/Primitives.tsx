import type { ReactNode } from 'react'
import { AlertCircle, Database, RefreshCw } from 'lucide-react'
import type { Cost, Meta, Rate } from '../api-types'
import { costNote, formatCost, formatRate, rateNote } from '../format'

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-header">
    <div>
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
    {action && <div className="page-action">{action}</div>}
  </header>
}

export function Panel({ title, subtitle, action, children, className = '' }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>
    <header className="panel-heading">
      <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
      {action}
    </header>
    <div className="panel-body">{children}</div>
  </section>
}

type KpiValue = string | number | Cost | Rate | null
export function Kpi({ label, value, detail, tone, featured = false }: { label: string; value: KpiValue; detail?: string; tone?: string; featured?: boolean }) {
  let display: string
  let note = detail
  if (value && typeof value === 'object' && 'status' in value) {
    display = formatCost(value as Cost)
    note ??= costNote(value as Cost)
  } else if (value && typeof value === 'object' && 'denominator' in value) {
    display = formatRate(value as Rate)
    note ??= rateNote(value as Rate)
  } else display = value == null ? 'Unknown' : String(value)
  return <article className={`kpi ${featured ? 'kpi-featured' : ''}`}>
    <span className="kpi-label">{label}</span>
    <strong className={tone ? `text-${tone}` : ''}>{display}</strong>
    {note && <small>{note}</small>}
  </article>
}

export function StateBadge({ state }: { state: string }) {
  const normalized = state.toLowerCase().replaceAll(' ', '-')
  return <span className={`status status-${normalized}`}><span aria-hidden="true" />{state.replaceAll('_', ' ')}</span>
}

export function SyntheticBanner({ meta }: { meta: Meta }) {
  if (!meta.synthetic) return null
  return <div className="synthetic-banner" role="note"><Database size={16} aria-hidden="true" /><span><strong>Synthetic dataset</strong> — illustrative local evidence, never production telemetry.</span></div>
}

export function DataFootnote({ meta }: { meta: Meta }) {
  const date = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' })
  return <footer className="data-footnote">
    <span>UTC · start inclusive, end exclusive</span>
    <span>{date.format(new Date(meta.start))} – {date.format(new Date(meta.end))}</span>
    {meta.freshness && <span>Freshness {meta.freshness}</span>}
    <span>Definition {meta.metric_definition_version}</span>
    {meta.notes.map((note, index) => <span key={index}>{note}</span>)}
  </footer>
}

export function LoadingState({ label = 'Loading telemetry' }: { label?: string }) {
  return <div className="loading-state" role="status" aria-label={label}>
    <div className="skeleton skeleton-title" /><div className="skeleton" /><div className="skeleton skeleton-short" />
  </div>
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return <div className="message-state" role="alert">
    <AlertCircle aria-hidden="true" /><div><h2>Telemetry is unavailable</h2><p>{error.message}</p></div>
    {onRetry && <button className="quiet-button" onClick={onRetry}><RefreshCw size={15} />Try again</button>}
  </div>
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="message-state empty-state"><div className="empty-mark" aria-hidden="true" /><div><h3>{title}</h3><p>{detail}</p></div></div>
}

export function ChartSummary({ children }: { children: ReactNode }) {
  return <p className="sr-only">{children}</p>
}

export function PartialMark({ cost }: { cost: Cost }) {
  return cost.status === 'partial' ? <span className="partial-mark" title={costNote(cost)}>Partial</span> : null
}
