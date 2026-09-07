import { describe, expect, it } from 'vitest'
import { formatCost, formatDate, plotCost } from '../format'
import type { Cost } from '../api-types'

const cost = (amount: string | null, status: Cost['status'] = 'known'): Cost => ({amount, status, known_subtotal: amount ?? '0', missing_count: amount === null ? 1 : 0})

describe('honest evidence formatting', () => {
  it('distinguishes zero, incomplete zero subtotal, and unavailable', () => {
    expect(formatCost(cost('0'))).toBe('$0.00')
    expect(formatCost(cost(null, 'partial'))).toContain('+')
    expect(formatCost(cost(null, 'unavailable'))).toBe('Unknown')
  })
  it('keeps sub-cent spend visible and does not plot infinity', () => {
    expect(formatCost(cost('0.000001'))).toContain('<')
    expect(plotCost(cost('1' + '0'.repeat(400)))).toBeNull()
  })
  it('keeps date-only labels on UTC boundaries', () => {
    expect(formatDate('2026-09-07T00:00:00Z', false)).toBe('Sep 7, 2026')
  })
})
