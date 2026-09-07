import { useEffect, useMemo, useState } from 'react'
import { CalendarDays, ChevronDown, RotateCcw, SlidersHorizontal } from 'lucide-react'
import { api } from '../api'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'

function toUtcBoundary(value: string, end = false): string {
  return value ? `${value}T${end ? '00:00:00' : '00:00:00'}Z` : ''
}

function dateValue(value?: string): string {
  return value?.slice(0, 10) ?? ''
}

export function FilterBar() {
  const { filters, setFilter, clearFilters } = useDashboard()
  const [expanded, setExpanded] = useState(false)
  const optionsFilters = useMemo(() => ({ start: filters.start, end: filters.end }), [filters.start, filters.end])
  const key = filterKey(optionsFilters)
  const models = useAsync((signal) => api.models(optionsFilters, signal), [key])
  const families = useAsync((signal) => api.taskFamilies(optionsFilters, signal), [key])
  const policies = useAsync((signal) => api.policies(optionsFilters, signal), [key])
  const active = Object.values(filters).filter(Boolean).length

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 821px)')
    const update = () => setExpanded(desktop.matches)
    update()
    desktop.addEventListener('change', update)
    return () => desktop.removeEventListener('change', update)
  }, [])

  const modelOptions = models.data?.cohorts.map((cohort) => cohort.key) ?? []
  const familyOptions = families.data?.cohorts.map((cohort) => cohort.key) ?? []
  const policyOptions = policies.data?.cohorts.map((cohort) => cohort.key) ?? []

  return <section className="filter-wrap" aria-label="Telemetry filters">
    <button className="filter-toggle" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
      <SlidersHorizontal size={16} /> Filters {active > 0 && <span>{active}</span>} <ChevronDown size={14} />
    </button>
    {expanded && <div className="filter-bar">
      <label className="date-field"><span>From · UTC</span><div><CalendarDays size={14} /><input aria-label="Start date UTC" type="date" value={dateValue(filters.start)} onChange={(event) => setFilter('start', toUtcBoundary(event.target.value))} /></div></label>
      <label className="date-field"><span>Until · UTC</span><div><CalendarDays size={14} /><input aria-label="End date UTC, exclusive" type="date" value={dateValue(filters.end)} onChange={(event) => setFilter('end', toUtcBoundary(event.target.value, true))} /></div></label>
      <FilterInput label="Application" value={filters.application} name="application" placeholder="All apps" onChange={(value) => setFilter('application', value)} />
      <FilterSelect label="Model" value={filters.model} options={modelOptions} onChange={(value) => setFilter('model', value)} />
      <FilterSelect label="Effort" value={filters.effort} options={['none', 'low', 'medium', 'high', 'xhigh', 'max']} onChange={(value) => setFilter('effort', value)} />
      <FilterSelect label="Family" value={filters.task_family} options={familyOptions} onChange={(value) => setFilter('task_family', value)} />
      <FilterSelect label="Policy" value={filters.policy_version} options={policyOptions} onChange={(value) => setFilter('policy_version', value)} />
      <FilterSelect label="Status" value={filters.status} options={['created', 'classified', 'routed', 'admitted', 'running', 'validating', 'recovering', 'succeeded', 'failed', 'blocked', 'cancelled']} onChange={(value) => setFilter('status', value)} />
      {active > 0 && <button className="reset-filters" onClick={clearFilters}><RotateCcw size={14} /> Reset</button>}
    </div>}
    <p className="filter-semantics">{filters.start || filters.end ? 'Custom UTC window' : 'Default: preceding 30 UTC days'} · Task metrics use creation time in [start, end); spend uses charge time in [start, end).</p>
  </section>
}

function FilterSelect({ label, value = '', options, onChange }: { label: string; value?: string; options: string[]; onChange: (value: string) => void }) {
  return <label><span>{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><option value="">All</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
}

function FilterInput({ label, value = '', name, placeholder, onChange }: { label: string; value?: string; name: string; placeholder: string; onChange: (value: string) => void }) {
  return <label><span>{label}</span><input name={name} aria-label={label} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>
}
