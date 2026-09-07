"""Explicit deterministic tool adapter, without external integrations."""
from uuid import uuid4
from model_router.core.execution_contracts import ToolOutcome, Failure
from model_router.core.contracts import FailureType

class MockToolExecutor:
    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)
        self.call_count = 0
        self.calls = []

    def execute(self, call, *, task_id, trace_id, event_id):
        self.call_count += 1
        self.calls.append({'tool': call.tool, 'operation': call.operation, 'event_id': event_id,
                           'task_id': task_id, 'trace_id': trace_id})
        try:
            scripted = next(self._outcomes)
            result = scripted(call) if callable(scripted) else scripted
            if not isinstance(result, ToolOutcome):
                raise ValueError('invalid tool result')
            return result.model_copy(update={'tool_event_id': event_id, 'tool': call.tool,
                'operation': call.operation, 'side_effecting': call.side_effecting,
                'replay_safe': bool(call.idempotency_key or call.reconciliation_evidence)})
        except StopIteration:
            return ToolOutcome(tool_event_id=event_id, tool=call.tool, operation=call.operation,
                status='failed', failure=Failure(failure_type=FailureType.TOOL_FAILURE,
                    source='tool', stage='execution', cause_code='mock_script_exhausted'))
