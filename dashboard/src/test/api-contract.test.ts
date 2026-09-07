import { describe, expect, it } from 'vitest'
import type { Efficacy, Health, Policies, Routing, Spend, Summary, TaskDetail, TaskList } from '../api-types'
import { efficacy, health, policies, routing, spend, summary, taskDetail, tasks } from './fixtures'

describe('frozen wire-contract fixtures', () => {
  it('remain assignable to every backend projection consumed by the UI', () => {
    const fixtures: [string, Summary | Spend | Routing | Efficacy | Policies | Health | TaskList | TaskDetail][] = [
      ['summary', summary], ['spend', spend], ['routing', routing], ['efficacy', efficacy], ['policies', policies], ['health', health], ['tasks', tasks], ['task-detail', taskDetail],
    ]
    expect(fixtures.map(([name]) => name)).toEqual(['summary', 'spend', 'routing', 'efficacy', 'policies', 'health', 'tasks', 'task-detail'])
    for (const [, fixture] of fixtures) {
      expect(fixture.meta.metric_definition_version).toBe('phase5-v1')
      expect(fixture.meta.synthetic).toBe(true)
    }
  })
})
