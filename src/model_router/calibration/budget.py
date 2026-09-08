"""Durable, separately named experiment allocations shared across local runs."""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
from model_router.core.contracts import money
from model_router.execution.arithmetic import money_sum, money_difference
from .corpus import require_safe_identifier


class CalibrationAllocation:
    """Reserve a whole conservative run bound before any paid call.

    A started reservation survives process exit. Unknown actual cost holds the
    entire reservation and blocks further runs; reconciliation is operator work.
    Existing IDs and ceilings cannot reset historical spend.
    """
    def __init__(self, root, allocation_id, ceiling):
        self.root = Path(root)
        self.allocation_id = require_safe_identifier(allocation_id)
        self.ceiling = money(ceiling)
        if self.ceiling <= 0:
            raise ValueError('allocation ceiling must be positive')
        self.path = self.root/(self.allocation_id+'.jsonl')

    @contextmanager
    def _ledger(self):
        for parent in (self.root,*self.root.parents):
            if parent.is_symlink():
                raise ValueError('allocation path cannot contain symlinks')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd = os.open(self.path,os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            with os.fdopen(os.dup(fd),'r',encoding='utf-8') as stream:
                lines = stream.readlines()
            if not lines:
                state = {'schema_version':1,'allocation_id':self.allocation_id,'ceiling_usd':str(self.ceiling),'runs':{}}
                self._append(fd,state)
                directory = os.open(self.root,os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            else:
                if any(not line.endswith('\n') for line in lines):
                    raise ValueError('allocation journal is incomplete')
                states = [json.loads(line) for line in lines]
                for item in states:
                    if item.get('allocation_id') != self.allocation_id or money(item['ceiling_usd']) != self.ceiling:
                        raise ValueError('allocation identity or ceiling changed')
                for previous,current in zip(states,states[1:]):
                    self._validate_transition(previous,current)
                state = states[-1]
                for run_id,reservation in state['runs'].items():
                    require_safe_identifier(run_id)
                    money(reservation['reserved'])
                    if reservation['status'] not in {'reserved','settled','uncertain'}:
                        raise ValueError('invalid allocation state')
                    if reservation['actual'] is not None:
                        money(reservation['actual'])
            yield fd,state
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _validate_transition(previous,current):
        before,after = previous['runs'],current['runs']
        if (set(previous) != set(current) or
                any(previous[k] != current[k] for k in previous if k != 'runs') or
                not set(before).issubset(after)):
            raise ValueError('allocation history cannot reset or remove runs')
        changed = [key for key in after if key not in before or before[key] != after[key]]
        if len(changed) != 1:
            raise ValueError('allocation journal must record one transition')
        key = changed[0]
        new = after[key]
        if set(new) != {'reserved','actual','status'}:
            raise ValueError('invalid allocation reservation')
        if key not in before:
            if new['status'] != 'reserved' or new['actual'] is not None:
                raise ValueError('allocation must reserve before settlement')
        else:
            old = before[key]
            if (old['status'] != 'reserved' or new['reserved'] != old['reserved'] or
                    new['status'] not in {'settled','uncertain'} or
                    (new['status'] == 'uncertain') != (new['actual'] is None)):
                raise ValueError('allocation history is immutable after settlement')

    @staticmethod
    def _append(fd,state):
        raw = (json.dumps(state,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if os.write(fd,raw) != len(raw):
            raise ValueError('allocation journal write incomplete')
        os.fsync(fd)

    def _remaining(self,state):
        charged = [money(r['actual']) if r['status']=='settled' else money(r['reserved']) for r in state['runs'].values()]
        return max(Decimal('0'),money_difference(self.ceiling,money_sum(charged)))

    def remaining(self):
        with self._ledger() as (_,state):
            return self._remaining(state)

    def reserve(self,run_id,amount):
        require_safe_identifier(run_id)
        amount = money(amount)
        with self._ledger() as (fd,state):
            if run_id in state['runs']:
                raise ValueError('run allocation cannot be replayed')
            if any(r['status']=='uncertain' for r in state['runs'].values()):
                raise ValueError('allocation has unresolved cost')
            if amount > self._remaining(state):
                raise ValueError('run bound exceeds remaining allocation')
            state['runs'][run_id] = {'reserved':str(amount),'actual':None,'status':'reserved'}
            self._append(fd,state)

    def assert_ready(self,run_id):
        with self._ledger() as (_,state):
            if (run_id not in state['runs'] or state['runs'][run_id]['status']!='reserved' or
                    any(r['status']=='uncertain' for r in state['runs'].values())):
                raise ValueError('allocation is not available for paid execution')

    def settle(self,run_id,actual):
        actual = None if actual is None else money(actual)
        with self._ledger() as (fd,state):
            reservation = state['runs'].get(run_id)
            if reservation is None or reservation['status'] != 'reserved':
                raise ValueError('run allocation is already final or missing')
            reservation.update(actual=None if actual is None else str(actual),
                               status='uncertain' if actual is None else 'settled')
            self._append(fd,state)
            if actual is not None and actual > money(reservation['reserved']):
                raise ValueError('actual cost exceeded allocated bound')
