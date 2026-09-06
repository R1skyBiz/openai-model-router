# Health audit v1

Status: Accepted health contract; active probes and circuits are Phase 4 work.

## Components and states

Health covers the router process, database, OpenAI/provider connectivity,
configured model availability, structured-output path, telemetry writer,
evaluator path and required external tools. Checks must be scoped by model and
capability where meaningful; an available text endpoint does not prove that
structured output or a required tool works.

| State | Meaning |
| --- | --- |
| HEALTHY | Required checks are fresh and the component meets its configured operating bounds. |
| DEGRADED | A required path is impaired or uncertain, but a safe constrained alternate path can continue. |
| UNHEALTHY | The required operation cannot safely proceed and no permitted alternate meets its constraints. |

Each check reports component, model/capability scope, state, observed_at,
valid_until, last successful check, latency, sanitized error category, and circuit
state. Disabled optional components report required=false and check_status=disabled,
not a fabricated successful probe. Missing/stale checks are uncertainty, never
HEALTHY; live required paths must verify access or become unavailable.
Catalog availability is versioned baseline data; fresh health is a separate
snapshot and does not mutate the activated registry.

## Startup, readiness and runtime audit

At startup, validate configuration references, immutable snapshots, model/effort
compatibility, budget/validation prerequisites and required adapter bindings.
An invalid new bundle is not activated. Keep the last valid bundle if available;
otherwise readiness fails. Process liveness can succeed even when readiness fails.

`/health/live` checks only the router process; it must not make provider calls.
`/health/ready` assesses configured enabled service operations and their required
dependencies. A safe alternate route can return ready=true with DEGRADED state.
No executable path or no durable telemetry retention yields ready=false.
Component-level reports state which capabilities/operations are unavailable.

Dependency probes include a database operation, connectivity/auth checks,
model access, a structured-output canary, a telemetry write/ack check, an evaluator
canary when enabled, and tool-specific probes. Paid/side-effecting probes require
explicit configuration, budgets, safe fixtures and opt-in credentials; default
offline tests use mocks. A health endpoint reads snapshots rather than launching
a new paid canary for every request.

Runtime auditing checks latency/error trends, timeouts/rate limits, model and
capability coverage, telemetry freshness, required validation availability and
configuration drift. Probe cadence, staleness windows, thresholds and alert
destinations are unresolved deployment configuration, to be set and tested in
Phase 4; they must not become Python constants or silently unlimited probing.

## Circuit breakers and recovery

Design per-model/capability circuits with closed, open and half_open states.
Failure thresholds open a circuit; a configured cooldown permits bounded
half-open probes; successful probes close it and failed probes reopen it.
Circuit state is distinct from HEALTHY/DEGRADED/UNHEALTHY.

Policy excludes an unhealthy required model/capability. Prefer healthy eligible
alternatives; degrade explicitly when a safe alternate continues. Required
tool/evaluator failures are isolated to affected paths where possible.
A provider outage must not become intelligence escalation; respect the
same/lower-tier infrastructure fallback restriction in routing configuration.
If no safe route exists, return a typed recoverable failure. Never bypass hard
floors, budget ceilings, approval requirements or mandatory validation.

Telemetry writer failure may continue only while events can be durably retained
for later delivery. Once that retention path is unavailable/full, stop admitting
new paid work and report UNHEALTHY for execution readiness. In-flight work must
retain final events and reconcile uncertain provider outcomes.

## Acceptance evidence

Phase 4 tests must inject stale checks, provider throttling, per-model outages,
structured-output failure, evaluator errors, database failure, telemetry backlog,
and required-tool timeouts. Verify isolated circuit transitions, bounded probes,
safe DEGRADED continuation and UNHEALTHY rejection with deterministic clocks.
Health audit findings contain observed evidence, severity, affected operation,
remediation and timestamp without secrets. Threshold calibration and alerts
remain configuration work, not settled deployment details.
