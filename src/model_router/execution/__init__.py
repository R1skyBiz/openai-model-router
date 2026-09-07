"""Execution boundary exports; importing this package performs no I/O."""
from .provider import MockProvider, ModelProvider, ProviderEvidence, ProviderFailure, ProviderRequest, ProviderResult, ProviderUsage
__all__ = ["MockProvider", "ModelProvider", "ProviderEvidence", "ProviderFailure", "ProviderRequest", "ProviderResult", "ProviderUsage"]

# Lazy exports avoid cycles while preserving the single-invocation provider API.
def __getattr__(name):
    if name in {'execute', 'ExecutionDependencies'}:
        from .orchestrator import execute, ExecutionDependencies
        return {'execute': execute, 'ExecutionDependencies': ExecutionDependencies}[name]
    raise AttributeError(name)

__all__ += ['execute', 'ExecutionDependencies']
