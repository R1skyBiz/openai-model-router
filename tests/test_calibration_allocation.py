from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
import pytest
from model_router.calibration.budget import CalibrationAllocation


def test_allocation_survives_restart_and_cannot_reset_spend(tmp_path):
    budget=CalibrationAllocation(tmp_path,'experiment','1')
    budget.reserve('run-a','.7');budget.settle('run-a','.6')
    second=CalibrationAllocation(tmp_path,'experiment','1')
    assert second.remaining()==Decimal('.4')
    with pytest.raises(ValueError,match='remaining'):
        second.reserve('run-b','.5')
    with pytest.raises(ValueError,match='replayed'):
        second.reserve('run-a','.1')
    with pytest.raises(ValueError,match='ceiling'):
        CalibrationAllocation(tmp_path,'experiment','2').remaining()


def test_unknown_holds_reservation_and_blocks_paid_work(tmp_path):
    b=CalibrationAllocation(tmp_path,'experiment','1')
    b.reserve('run-a','.7');b.reserve('run-b','.2')
    b.settle('run-a',None)
    assert b.remaining()==Decimal('.1')
    with pytest.raises(ValueError,match='unresolved'):
        b.reserve('run-c','.01')
    with pytest.raises(ValueError,match='available'):
        b.assert_ready('run-b')


def test_concurrent_run_reservations_never_oversubscribe(tmp_path):
    def attempt(i):
        try:
            CalibrationAllocation(tmp_path,'experiment','1').reserve(f'run-{i}','.6')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt,range(8)))==1
    assert CalibrationAllocation(tmp_path,'experiment','1').remaining()==Decimal('.4')


def test_allocation_precision_and_incomplete_journal_fail_closed(tmp_path):
    with localcontext() as ctx:
        ctx.prec=2
        b=CalibrationAllocation(tmp_path,'experiment','1')
        b.reserve('run-a','.123456789123456789')
        assert b.remaining()==Decimal('.876543210876543211')
    with b.path.open('a') as stream: stream.write('{')
    with pytest.raises(ValueError,match='incomplete'):
        b.remaining()


@pytest.mark.parametrize('mutation',['remove','reset','resize'])
def test_appended_history_cannot_remove_or_reset_spend(tmp_path,mutation):
    import json
    b=CalibrationAllocation(tmp_path,'experiment','1')
    b.reserve('run-a','.7');b.settle('run-a','.6')
    state=json.loads(b.path.read_text().splitlines()[-1])
    if mutation=='remove': state['runs']={}
    elif mutation=='reset': state['runs']['run-a'].update(status='reserved',actual=None)
    else: state['runs']['run-a']['reserved']='.1'
    with b.path.open('a') as stream: stream.write(json.dumps(state)+'\n')
    with pytest.raises(ValueError,match='history'):
        b.remaining()
