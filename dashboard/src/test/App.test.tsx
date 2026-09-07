import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { responseFor } from './fixtures'

function installFetch(overrides?: (url: string) => unknown) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const data = overrides ? overrides(url) : responseFor(url)
    return { ok: true, status: 200, json: async () => data } as Response
  }))
}

function renderPath(path: string) { return render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>) }

describe('dashboard', () => {
  beforeEach(() => { localStorage.clear(); installFetch() })

  it.each([
    ['/', 'Overview'], ['/spend', 'Spend'], ['/routing', 'Routing'], ['/efficacy', 'Efficacy'], ['/health', 'Health'], ['/tasks', 'Tasks'],
  ])('renders %s page from typed API evidence', async (path, heading) => {
    renderPath(path)
    expect(await screen.findByRole('heading', { name: heading, level: 1 })).toBeInTheDocument()
    expect(await screen.findByText(/Synthetic dataset/)).toBeInTheDocument()
  })

  it('shows skeleton loading then a calm API error with retry', async () => {
    let reject!: (reason: Error) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise((_resolve, nextReject) => { reject = nextReject })))
    renderPath('/spend')
    expect(screen.getByRole('status', { name: 'Loading telemetry' })).toBeInTheDocument()
    reject(new Error('Service unavailable'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable')
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('renders honest no-data and unknown states', async () => {
    installFetch((url) => {
      const value = responseFor(url)
      if (url.includes('/telemetry/spend')) return { ...(value as object), production: { amount: null, known_subtotal: '0', missing_count: 0, status: 'unavailable' }, shadow: { amount: null, known_subtotal: '0', missing_count: 0, status: 'unavailable' }, series: [] }
      return value
    })
    renderPath('/spend')
    expect(await screen.findByText('No spend data yet')).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
  })

  it('applies global filters with explicit UTC semantics', async () => {
    const user = userEvent.setup(); renderPath('/tasks')
    await screen.findByRole('heading', { name: 'Tasks' })
    await user.click(screen.getByRole('button', { name: /filters/i }))
    const application = screen.getByRole('textbox', { name: 'Application' })
    await user.type(application, 'support')
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('application=support'), expect.anything()))
    expect(screen.getByText(/Task metrics use creation time/)).toBeInTheDocument()
  })

  it('persists a first-class theme choice', async () => {
    const user = userEvent.setup(); renderPath('/')
    await screen.findByRole('heading', { name: 'Overview' })
    await user.click(screen.getByRole('button', { name: 'Dark theme' }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(localStorage.getItem('model-router-theme')).toBe('dark')
  })

  it('exposes timeline details progressively without raw content', async () => {
    const user = userEvent.setup(); renderPath('/tasks/task-safe-1')
    expect(await screen.findByRole('heading', { name: '2 timeline steps' })).toBeInTheDocument()
    expect(screen.getByText('Shadow')).toBeInTheDocument()
    const attempt = screen.getByRole('button', { name: /Attempt 1/ })
    expect(attempt).toHaveAttribute('aria-expanded', 'false')
    await user.click(attempt)
    expect(attempt).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Pricing version')).toBeInTheDocument()
    expect(screen.getByText('Input Tokens')).toBeInTheDocument()
    expect(screen.queryByText(/Tokens tokens/)).not.toBeInTheDocument()
    expect(screen.getByText('Safe metadata')).toBeInTheDocument()
    expect(screen.queryByText(/raw prompt|raw output/i)).not.toBeInTheDocument()
  })

  it('provides semantic navigation, filter region, and labeled data tables', async () => {
    renderPath('/tasks'); await screen.findByRole('heading', { name: 'Tasks' })
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Telemetry filters' })).toBeInTheDocument()
    const tableRegion = screen.getByRole('region', { name: 'Task list' })
    expect(within(tableRegion).getByRole('columnheader', { name: 'Status' })).toBeInTheDocument()
    expect(screen.getByText(/UTC · start inclusive/)).toBeInTheDocument()
  })

  it('supports keyboard entry and timeline disclosure', async () => {
    const user = userEvent.setup(); renderPath('/tasks/task-safe-1')
    await screen.findByRole('heading', { name: '2 timeline steps' })
    await user.tab()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveFocus()
    const attempt = screen.getByRole('button', { name: /Attempt 1/ })
    attempt.focus()
    await user.keyboard('{Enter}')
    expect(attempt).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Safe metadata')).toBeInTheDocument()
  })

  it('labels incomplete cost evidence and health uncertainty', async () => {
    renderPath('/health')
    await screen.findByText(/Synthetic dataset/)
    expect(screen.getAllByText(/STALE/i).length).toBeGreaterThan(0)
  })

  it('renders an empty trend for a date axis with no outcome evidence', async () => {
    installFetch((url) => {
      const value = responseFor(url)
      if (url.includes('/telemetry/routing')) return { ...(value as object), trend: [{date: '2026-09-07', first_pass_success: {value: null, numerator: 0, denominator: 0}, final_success: {value: null, numerator: 0, denominator: 0}, effective_cost_per_success: {amount: null, known_subtotal: '0', missing_count: 0, status: 'unavailable'}}] }
      return value
    })
    renderPath('/routing')
    expect(await screen.findByText('No routing trend yet')).toBeInTheDocument()
  })

  it('shows sanitized backend error messages', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({message: 'Telemetry storage is unavailable.'}) })))
    renderPath('/health')
    expect(await screen.findByRole('alert')).toHaveTextContent('Telemetry storage is unavailable.')
  })
  it('shows policy score identity and scale alongside a small-sample guard', async () => {
    renderPath('/efficacy')
    const table = await screen.findByRole('region', { name: 'Policy efficacy comparison' })
    expect(within(table).getByText('Insufficient sample')).toBeInTheDocument()
    expect(within(table).getByText(/rubric-v2 · correctness · 0.88 on 0–1 · 8 evaluated attempts · primary/)).toBeInTheDocument()
  })

})
