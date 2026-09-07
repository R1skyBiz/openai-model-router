"""Explicit, injected admission for the deliberately small release live path.

This boundary does not enable itself from environment variables. The release
composition supplies a fresh fail-closed guard and a reviewed input allowance.
"""
from dataclasses import dataclass
from typing import Callable
import json

from model_router.core.contracts import Context, Request
from model_router.core.provider_contracts import ProviderRequest


@dataclass(frozen=True)
class LiveExecutionAuthorization:
    release_version: str
    max_input_tokens: int
    input_overhead_tokens: int
    check: Callable[[], bool]
    classifier_factory: Callable | None = None
    max_output_tokens: int = 4096
    provider_timeout_ms: int = 30000
    durable_allocation_verified: Callable[[str], bool] | None = None

    def allocation_ready(self, task_id: str) -> bool:
        try:
            return self.durable_allocation_verified is not None and self.durable_allocation_verified(task_id) is True
        except Exception:
            return False

    def __post_init__(self):
        if (not self.release_version or type(self.max_input_tokens) is not int
                or self.max_input_tokens <= 0 or type(self.input_overhead_tokens) is not int
                or self.input_overhead_tokens < 0 or not callable(self.check)):
            raise ValueError('invalid live execution authorization')

    def ready(self) -> bool:
        try:
            return self.check() is True
        except Exception:
            return False

    def bound_request(self, request: Request) -> Request:
        # Paid ingress never trusts client token/cache estimates for admission.
        return request.model_copy(update={'context': Context(
            input_tokens=self.max_input_tokens,
            expected_output_tokens=request.context.expected_output_tokens)})

    def allows(self, request: ProviderRequest) -> bool:
        wire = request.model_dump(mode='json')
        wire.update(input=request.input, instructions=request.instructions)
        if request.output_type is not None:
            wire['output_schema'] = request.output_type.model_json_schema()
        size = len(json.dumps(wire, ensure_ascii=True, sort_keys=True).encode('utf-8'))
        return (size + self.input_overhead_tokens <= self.max_input_tokens
                and request.max_output_tokens <= self.max_output_tokens and self.ready())

    def upper_cost(self, model, max_output_tokens: int):
        from decimal import Decimal, localcontext
        pricing = model['pricing']
        if (self.max_input_tokens > pricing['long_context']['input_tokens_gt']
                or pricing['service_tier'] != 'standard'
                or max_output_tokens > model['max_output_tokens']
                or max_output_tokens + self.max_input_tokens > model['context_window_tokens']):
            raise ValueError('live request exceeds supported bounds')
        if any(pricing[name] is None for name in ('input_usd','cached_input_usd','output_usd','cache_write_input_multiplier')):
            raise ValueError('live price evidence incomplete')
        with localcontext() as context:
            context.prec = 80
            rate = max(pricing['input_usd'], pricing['cached_input_usd'],
                       pricing['input_usd'] * pricing['cache_write_input_multiplier'])
            return (Decimal(self.max_input_tokens) * rate + Decimal(max_output_tokens) * pricing['output_usd']) / pricing['unit_tokens']


from pydantic import model_validator
from model_router.core.contracts import EnvironmentSnapshot, Name


class ReleaseEnvironmentSnapshot(EnvironmentSnapshot):
    """Trusted release evidence; original synthetic-only fixture contract is unchanged."""
    release_version: Name

    @model_validator(mode='after')
    def provenance(self):
        if self.synthetic or self.validation:
            raise ValueError('release snapshots cannot carry mock evidence')
        if (self.application_overlay is None) != (self.application_overlay_version is None):
            raise ValueError('application overlay and version must accompany each other')
        for stamp in (self.clock,self.health_observed_at,self.health_valid_until):
            if stamp is not None and stamp.utcoffset() is None:
                raise ValueError('snapshot timestamps must be timezone-aware')
        return self


from model_router.core.execution_contracts import RecoveryContext


class ReleaseRecoveryContext(RecoveryContext):
    environment: ReleaseEnvironmentSnapshot
