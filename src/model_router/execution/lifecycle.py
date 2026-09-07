"""Explicit task and attempt transitions; finalized evidence is immutable."""
from model_router.core.execution_contracts import TaskStatus, AttemptStatus, TaskResult, Attempt

_TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
_NEXT = {
    TaskStatus.CREATED: {TaskStatus.CLASSIFIED},
    TaskStatus.CLASSIFIED: {TaskStatus.ROUTED},
    TaskStatus.ROUTED: {TaskStatus.ADMITTED},
    TaskStatus.ADMITTED: {TaskStatus.RUNNING},
    TaskStatus.RUNNING: {TaskStatus.VALIDATING, TaskStatus.RECOVERING},
    TaskStatus.VALIDATING: {TaskStatus.SUCCEEDED, TaskStatus.RECOVERING},
    TaskStatus.RECOVERING: {TaskStatus.ROUTED, TaskStatus.VALIDATING},
}

def transition(task: TaskResult, status: TaskStatus, *, now, **changes) -> TaskResult:
    if task.status in _TERMINAL:
        raise ValueError('terminal task cannot transition')
    if status not in _NEXT.get(task.status, set()) | (_TERMINAL - {TaskStatus.SUCCEEDED}):
        raise ValueError('invalid task transition')
    return task.model_copy(update={**changes, 'status': status, 'updated_at': now})

def finish_attempt(started: Attempt, completed: Attempt) -> Attempt:
    if started.status != AttemptStatus.STARTED or completed.status == AttemptStatus.STARTED:
        raise ValueError('attempt finalization requires started to terminal')
    for key in ('attempt_id', 'task_id', 'trace_id', 'sequence', 'purpose', 'parent_attempt_id',
                'decision', 'started_at', 'estimated_cost_usd', 'pricing_version'):
        if getattr(started, key) != getattr(completed, key):
            raise ValueError('attempt identity and admission evidence are immutable')
    if completed.completed_at is None or completed.completed_at < started.started_at:
        raise ValueError('attempt completion time is invalid')
    return completed
