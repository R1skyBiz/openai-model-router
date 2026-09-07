import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, CircleCheck, CircleDot, Clock3, Coins, Cpu, GitBranch, Search, ShieldCheck, TriangleAlert, Wrench } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import type { TaskItem, TimelineStep } from '../api-types'
import { DataFootnote, EmptyState, ErrorState, LoadingState, PageHeader, PartialMark, StateBadge, SyntheticBanner } from '../components/Primitives'
import { filterKey, useDashboard } from '../state'
import { useAsync } from '../hooks'
import { formatCost, formatDate, formatLatency, shortModel, titleCase } from '../format'

export default function TasksPage() {
  const { taskId } = useParams()
  return taskId ? <TaskDetailPage taskId={taskId}/> : <TaskListPage/>
}

function TaskListPage() {
  const { filters } = useDashboard(); const [offset, setOffset] = useState(0); const limit = 25
  const [search, setSearch] = useState(''); const key = filterKey(filters)
  useEffect(() => setOffset(0), [key])
  const state = useAsync((signal) => api.tasks(filters, offset, limit, signal), [key, offset])
  if (state.loading) return <><PageHeader eyebrow="Trace explorer" title="Tasks" description="Inspect the route, cost, outcome, and safe execution history of any task."/><LoadingState/></>
  if (state.error || !state.data) return <ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/>
  const data = state.data
  const visible = data.items.filter((task) => !search || [task.task_id, task.application, task.task_family, task.model, task.status].some((value) => value?.toLowerCase().includes(search.toLowerCase())))
  return <>
    <PageHeader eyebrow="Trace explorer" title="Tasks" description="Inspect the route, cost, outcome, and safe execution history of any task." action={<label className="task-search"><Search size={16}/><span className="sr-only">Search current task page</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search this page"/></label>}/>
    <SyntheticBanner meta={data.meta}/>
    <div className="task-table-wrap">
      {visible.length ? <div className="table-scroll" role="region" aria-label="Task list" tabIndex={0}><table className="task-table"><thead><tr><th scope="col">Created · UTC</th><th scope="col">Application / family</th><th scope="col">Complexity</th><th scope="col">Route</th><th scope="col">Status</th><th scope="col">Cost</th><th scope="col">Latency</th><th scope="col"><span className="sr-only">Inspect</span></th></tr></thead><tbody>{visible.map((task) => <TaskRow task={task} key={task.task_id}/>)}</tbody></table></div> : <EmptyState title="No tasks found" detail={search ? 'No task on this page matches your search.' : 'No admitted tasks match the selected filters.'}/>}
      <footer className="pagination"><span>Showing {data.total ? offset + 1 : 0}–{Math.min(offset + limit, data.total)} of {data.total}</span><div><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}><ArrowLeft size={15}/>Previous</button><button disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)}>Next<ArrowRight size={15}/></button></div></footer>
    </div>
    <DataFootnote meta={data.meta}/>
  </>
}

function TaskRow({ task }: { task: TaskItem }) {
  return <tr><td><Link to={`/tasks/${task.task_id}`}>{formatDate(task.created_at)}</Link><small className="id-text">{task.task_id}</small></td><td><strong>{task.application ?? 'Unknown app'}</strong><small>{task.task_family ?? 'Unclassified'}</small></td><td>{task.complexity ?? 'Unknown'}</td><td><strong>{shortModel(task.model)}</strong><small>{task.effort ?? 'Unknown effort'}</small></td><td><StateBadge state={task.status}/>{task.escalated && <span className="escalated-mark"><GitBranch size={12}/>Escalated</span>}</td><td>{formatCost(task.cost)} <PartialMark cost={task.cost}/></td><td>{formatLatency(task.latency_ms)}</td><td><Link className="inspect-link" to={`/tasks/${task.task_id}`} aria-label={`Inspect task ${task.task_id}`}><ChevronRight/></Link></td></tr>
}

function TaskDetailPage({ taskId }: { taskId: string }) {
  const { filters } = useDashboard(); const key = filterKey(filters); const navigate = useNavigate()
  const [offset, setOffset] = useState(0); const limit = 100
  useEffect(() => setOffset(0), [taskId, key])
  const state = useAsync((signal) => api.task(taskId, filters, offset, limit, signal), [taskId, key, offset])
  if (state.loading) return <><PageHeader eyebrow="Task timeline" title="Loading trace" description="Reconstructing safe normalized execution evidence."/><LoadingState/></>
  if (state.error || !state.data) return <><button className="back-link" onClick={() => navigate('/tasks')}><ArrowLeft size={15}/>All tasks</button><ErrorState error={state.error ?? new Error('No response')} onRetry={state.reload}/></>
  const detail = state.data; const task = detail.task
  return <>
    <button className="back-link" onClick={() => navigate('/tasks')}><ArrowLeft size={15}/>All tasks</button>
    <PageHeader eyebrow="Task timeline" title={task.task_family ?? 'Unclassified task'} description={`${task.application ?? 'Unknown application'} · ${task.task_id}`} action={<StateBadge state={task.status}/>}/>
    <SyntheticBanner meta={detail.meta}/>
    <section className="task-hero"><div><span>Created</span><strong>{formatDate(task.created_at)}</strong></div><div><span>Initial route</span><strong>{shortModel(task.model)} · {task.effort ?? 'Unknown effort'}</strong></div><div><span>Cost</span><strong>{formatCost(task.cost)} <PartialMark cost={task.cost}/></strong></div><div><span>Latency</span><strong>{formatLatency(task.latency_ms)}</strong></div><div><span>Policy</span><strong>{task.policy_version}</strong></div>{task.escalated && <div className="task-escalated"><GitBranch/><span>Intelligence escalation occurred</span></div>}</section>
    <section className="timeline-section" aria-labelledby="timeline-title"><header><div><p className="eyebrow">Execution history</p><h2 id="timeline-title">{detail.total} timeline steps</h2></div><p>Safe normalized facts only. Prompt and output content are not exposed.</p></header>
      {detail.timeline.length ? <><ol className="timeline">{detail.timeline.map((step, index) => <TimelineItem step={step} key={step.id} index={offset + index} final={offset + index === detail.total - 1}/>)}</ol>{detail.total > limit && <footer className="pagination timeline-pagination"><span>Steps {offset + 1}–{Math.min(offset + limit, detail.total)} of {detail.total}</span><div><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}><ArrowLeft size={15}/>Earlier</button><button disabled={offset + limit >= detail.total} onClick={() => setOffset(offset + limit)}>Later<ArrowRight size={15}/></button></div></footer>}</> : <EmptyState title="No timeline evidence" detail="No safe execution events were retained for this task."/>}
    </section>
    <DataFootnote meta={detail.meta}/>
  </>
}

function TimelineItem({ step, index, final }: { step: TimelineStep; index: number; final: boolean }) {
  const [open, setOpen] = useState(false)
  const facts = useMemo(() => timelineFacts(step), [step])
  const Icon = timelineIcon(step.kind)
  return <li className={final ? 'timeline-final' : ''}><div className="timeline-marker"><Icon aria-hidden="true"/></div><article><button className="timeline-summary" aria-expanded={open} onClick={() => setOpen((value) => !value)}><div><span className="step-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{step.title}</h3><p>{formatDate(step.timestamp)}{step.model ? ` · ${shortModel(step.model)} / ${step.effort ?? 'unspecified'}` : ''}</p></div></div><div>{step.role.toLowerCase() === 'shadow' && <span className="shadow-mark">Shadow</span>}{step.cost && <span className="timeline-cost">{formatCost(step.cost)}</span>}{open ? <ChevronDown/> : <ChevronRight/>}</div></button>{open && <div className="timeline-details"><dl>{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{step.rationale_codes.length > 0 && <div className="rationale"><strong>Rationale</strong>{step.rationale_codes.map((code) => <span key={code}>{code}</span>)}</div>}{Object.keys(step.metadata).length > 0 && <details className="safe-metadata"><summary>Safe metadata</summary><dl>{Object.entries(step.metadata).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{value == null ? 'Unknown' : String(value)}</dd></div>)}</dl></details>}</div>}</article></li>
}

function timelineFacts(step: TimelineStep): [string, string][] {
  const facts: [string, string | null | undefined][] = [
    ['Model', step.model ? shortModel(step.model) : null], ['Reasoning effort', step.effort], ['Role', step.role], ['Latency', step.latency_ms == null ? null : formatLatency(step.latency_ms)], ['Validation', step.validation], ['Failure type', step.failure_type], ['Recovery action', step.recovery_action], ['Health snapshot', step.health_snapshot_id], ['Policy version', step.policy_version], ['Pricing version', step.pricing_version],
  ]
  Object.entries(step.tokens).forEach(([key, value]) => facts.push([titleCase(key), value == null ? null : String(value)]))
  return facts.filter((fact): fact is [string, string] => fact[1] !== null && fact[1] !== undefined && fact[1] !== '')
}

function timelineIcon(kind: string) {
  const key = kind.toLowerCase()
  if (key.includes('success') || key.includes('complete')) return CircleCheck
  if (key.includes('valid')) return ShieldCheck
  if (key.includes('recover') || key.includes('escalat')) return GitBranch
  if (key.includes('fail') || key.includes('error')) return TriangleAlert
  if (key.includes('tool')) return Wrench
  if (key.includes('attempt') || key.includes('model')) return Cpu
  if (key.includes('cost') || key.includes('charge')) return Coins
  if (key.includes('time')) return Clock3
  return CircleDot
}
