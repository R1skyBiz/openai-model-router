# ADR 0006: Shared engine and provider boundary

Status: Accepted

## Context

Embedded callers and HTTP clients need consistent routing, while provider SDKs and
service frameworks evolve independently.

## Decision

Use one application-independent routing engine for embedded library and HTTP service
modes. The core depends on neither FastAPI, SQLAlchemy, the OpenAI SDK, a dashboard nor
telemetry transport. Define a core-owned ModelProvider contract; later OpenAIProvider
and MockProvider implement it. MockProvider supports deterministic, credential-free
tests. Cross-provider routing remains outside v1.

## Consequences

[architecture.md](../architecture.md) owns normalized contracts. Adapters translate
SDK/framework/persistence types. Orchestration owns execution and recovery; provider
adapters do not choose escalation policy.

## Unresolved implementation details

Concrete Python signatures, asynchronous/streaming conventions and SDK mapping details
are implementation choices to resolve in their designated phases.
