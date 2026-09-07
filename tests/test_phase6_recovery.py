"""Quiescent backup/restore preserves cost and duplicate execution evidence."""
from dataclasses import replace
import sqlite3
from model_router.execution.orchestrator import execute
from model_router.execution.provider import MockProvider
from model_router.storage.budget import SQLBudgetAuthority
from model_router.storage.repository import SQLTaskRepository
from tests.phase3_support import setup


def test_quiescent_backup_restores_allocation_outbox_and_idempotency(tmp_path):
    request,classification,deps=setup(tmp_path)
    authority=SQLBudgetAuthority(deps.repository,'backup-app','persistent-allocation','10','10')
    deps=replace(deps,budget=authority,environment=deps.environment.model_copy(update={'trusted_application_id':'backup-app'}),
        controls=deps.controls.model_copy(update={'idempotency_key':'backup-key'}))
    completed=execute(request,deps,supplied_classification=classification)
    assert completed.status=='succeeded'
    remaining=authority.remaining(request.task_id)
    original_events={e.event_id for e in deps.repository.pending_outbox()}
    # SQLite backup API includes committed WAL state; copying just state.db would not.
    with sqlite3.connect(tmp_path/'state.db') as source,sqlite3.connect(tmp_path/'restored.db') as destination:
        source.backup(destination)
    repo=SQLTaskRepository(f'sqlite+pysqlite:///{tmp_path / "restored.db"}',journal_path=tmp_path/'restored-journal.jsonl')
    restored=SQLBudgetAuthority(repo,'backup-app','persistent-allocation','10','10')
    assert restored.remaining(request.task_id)==remaining
    assert {e.event_id for e in repo.pending_outbox()}==original_events
    provider=MockProvider([])
    duplicate=execute(request,replace(deps,repository=repo,budget=restored,provider=provider),supplied_classification=classification)
    assert duplicate.task_id==completed.task_id
    assert duplicate.total_cost_usd==completed.total_cost_usd
    assert not provider.requests
    assert duplicate.output is None
    assert repo.reconcile_pending()==0
    repo.engine.dispose()
    deps.repository.engine.dispose()


def _duplicate_execute_worker(args):
    import os
    from pathlib import Path
    from tests.phase3_support import success
    url,root,index=args
    directory=Path(root)
    worker=directory/f'worker-{index}'
    worker.mkdir()
    request,classification,deps=setup(worker)
    repo=SQLTaskRepository(url,journal_path=directory/'shared-journal.jsonl')
    budget=SQLBudgetAuthority(repo,'race-app','execute-allocation','1','1')
    def paid_boundary(provider_request):
        fd=os.open(directory/'dispatches',os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
        try:
            os.write(fd,b'dispatched\n')
            os.fsync(fd)
        finally:
            os.close(fd)
        return success(provider_request)
    configured=replace(deps,repository=repo,budget=budget,provider=MockProvider([paid_boundary]),
        environment=deps.environment.model_copy(update={'trusted_application_id':'race-app'}),
        controls=deps.controls.model_copy(update={'idempotency_key':'shared-execute-key'}))
    task=execute(request,configured,supplied_classification=classification)
    repo.engine.dispose()
    deps.repository.engine.dispose()
    return task.status.value


def test_cross_process_duplicate_execute_dispatches_once(tmp_path):
    import multiprocessing
    from model_router.storage import upgrade_database
    url=f'sqlite+pysqlite:///{tmp_path / "shared.db"}'
    upgrade_database(url)
    with multiprocessing.get_context('spawn').Pool(4) as workers:
        statuses=workers.map(_duplicate_execute_worker,[(url,str(tmp_path),i) for i in range(4)])
    assert 'succeeded' in statuses
    assert (tmp_path/'dispatches').read_text().splitlines()==['dispatched']
