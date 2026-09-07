import type {
  Efficacy,
  Filters,
  Health,
  Policies,
  Routing,
  Spend,
  Summary,
  TaskDetail,
  TaskList,
} from './api-types'

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

export function queryString(filters: Filters, extra: Record<string, string | number | undefined> = {}) {
  const params = new URLSearchParams()
  Object.entries({ ...filters, ...extra }).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = (await response.json()) as { detail?: string; message?: string }
      if (body.message) detail = body.message
      else if (body.detail) detail = body.detail
    } catch { /* retain the safe status message */ }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  summary: (filters: Filters, signal?: AbortSignal) => get<Summary>(`/v1/telemetry/summary${queryString(filters)}`, signal),
  spend: (filters: Filters, signal?: AbortSignal) => get<Spend>(`/v1/telemetry/spend${queryString(filters)}`, signal),
  routing: (filters: Filters, signal?: AbortSignal) => get<Routing>(`/v1/telemetry/routing${queryString(filters)}`, signal),
  efficacy: (filters: Filters, signal?: AbortSignal) => get<Efficacy>(`/v1/telemetry/efficacy${queryString(filters)}`, signal),
  policies: (filters: Filters, signal?: AbortSignal) => get<Policies>(`/v1/telemetry/policies${queryString(filters)}`, signal),
  health: (filters: Filters, signal?: AbortSignal) => get<Health>(`/v1/telemetry/health${queryString(filters)}`, signal),
  tasks: (filters: Filters, offset = 0, limit = 25, signal?: AbortSignal) =>
    get<TaskList>(`/v1/tasks${queryString(filters, { offset, limit })}`, signal),
  task: (id: string, filters: Filters, offset = 0, limit = 100, signal?: AbortSignal) =>
    get<TaskDetail>(`/v1/tasks/${encodeURIComponent(id)}${queryString(filters, { view: 'timeline', offset, limit })}`, signal),
  models: (filters: Filters, signal?: AbortSignal) => get<Efficacy>(`/v1/telemetry/models${queryString(filters)}`, signal),
  taskFamilies: (filters: Filters, signal?: AbortSignal) => get<Efficacy>(`/v1/telemetry/task-families${queryString(filters)}`, signal),
}
