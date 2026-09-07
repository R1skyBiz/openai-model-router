import type { Cost, Rate } from './api-types'

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 })
const integer = new Intl.NumberFormat('en-US')

export function formatCost(cost: Cost | null | undefined): string {
  if (!cost || cost.status === 'unavailable' || cost.amount === null) {
    if (cost?.status === 'partial') return `${formatDecimalMoney(cost.known_subtotal)}+`
    return 'Unknown'
  }
  const shown = formatDecimalMoney(cost.amount)
  return cost.status === 'partial' ? `${shown}+` : shown
}

function formatDecimalMoney(value: string): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return `$${value}`
  if (numeric > 0 && numeric < 0.00005) return '<$0.0001'
  if (numeric < 0 && numeric > -0.00005) return '>-$0.0001'
  return money.format(numeric)
}

export function costNote(cost: Cost | null | undefined): string | undefined {
  if (!cost || cost.status === 'unavailable') return 'No charge evidence is available'
  if (cost.status === 'partial') return `${cost.missing_count} cost record${cost.missing_count === 1 ? '' : 's'} incomplete; known subtotal ${formatDecimalMoney(cost.known_subtotal)}`
  return undefined
}

export function plotCost(cost: Cost | null | undefined): number | null {
  if (!cost) return null
  const value = cost.amount ?? (cost.status === 'partial' ? cost.known_subtotal : null)
  if (value === null) return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

export function formatRate(rate: Rate | null | undefined): string {
  return rate?.value == null ? 'Unknown' : `${(rate.value * 100).toFixed(1)}%`
}

export function rateNote(rate: Rate | null | undefined): string {
  if (!rate || rate.value == null) return 'No eligible denominator'
  return `${integer.format(rate.numerator)} of ${integer.format(rate.denominator)}`
}

export function formatCount(value: number | null | undefined): string {
  return value == null ? 'Unknown' : integer.format(value)
}

export function formatLatency(value: number | null | undefined): string {
  if (value == null) return 'Unknown'
  if (value < 1_000) return `${Math.round(value)} ms`
  return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`
}

export function formatDate(value: string | null | undefined, includeTime = true): string {
  if (!value) return 'Unknown'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: includeTime ? undefined : 'numeric',
    hour: includeTime ? 'numeric' : undefined, minute: includeTime ? '2-digit' : undefined,
    timeZone: 'UTC', timeZoneName: includeTime ? 'short' : undefined,
  }).format(date)
}

export function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function shortModel(value: string | null): string {
  if (!value) return 'Unknown model'
  return value.replace(/^gpt-/, '').replace(/-\d{4}-\d{2}-\d{2}$/, '')
}
