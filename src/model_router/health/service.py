"""Deterministic Phase 4 health snapshots and scoped circuit breakers.

The service is an in-memory operational projection.  It accepts already
normalized failures; it never calls a provider while serving a snapshot.
Applications may run the optional bounded probe protocol from their own
scheduler.  Live probes are disabled by the shipped Phase 4 configuration.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import islice
import json
from threading import RLock
from typing import Literal, Protocol, runtime_checkable

from model_router.core.contracts import EnvironmentSnapshot, FailureType, ModelHealth
from model_router.core.phase4_contracts import (
    HealthConfig,
    HealthObservation,
    HealthSnapshot,
)


HealthState = Literal["HEALTHY", "DEGRADED", "UNHEALTHY"]
CircuitState = Literal["closed", "open", "half_open"]
_NON_HEALTH_FAILURES = {FailureType.QUALITY_FAILURE, FailureType.BUDGET_FAILURE}
_INFRASTRUCTURE_FAILURES = {
    FailureType.TIMEOUT,
    FailureType.RATE_LIMIT,
    FailureType.PROVIDER_FAILURE,
}


@dataclass(frozen=True, slots=True)
class HealthReadiness:
    """Readiness of enabled operations at one deterministic instant."""

    ready: bool
    state: HealthState
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    """Sanitized result returned by a configured probe implementation."""

    success: bool
    state: HealthState | None = None
    failure: FailureType | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.success and self.failure is not None:
            raise ValueError("a successful probe cannot contain a failure")
        if not self.success and self.failure is None and self.state is None:
            raise ValueError("a failed probe requires failure or state evidence")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool) or self.latency_ms < 0
        ):
            raise ValueError("probe latency must be a nonnegative integer")


@runtime_checkable
class HealthProbe(Protocol):
    """Optional adapter-owned probe.  Implementations enforce their timeout."""

    component: str
    model: str | None
    capability: str | None
    required: bool
    cost_upper_bound_usd: Decimal | str

    def run(self, timeout_ms: int) -> HealthProbeResult: ...


@dataclass(slots=True)
class _Circuit:
    failures: deque[datetime]
    state: CircuitState = "closed"
    opened_at: datetime | None = None
    admitted_probes: int = 0
    pending_probes: int = 0
    recovery_successes: int = 0


class HealthService:
    """Record health evidence and project it without hidden I/O."""

    def __init__(self, clock, config: HealthConfig) -> None:
        if not hasattr(clock, "now"):
            raise TypeError("health clock must provide now()")
        self.clock = clock
        self.config = config
        self._observations: dict[tuple[str, str | None, str | None], HealthObservation] = {}
        self._circuits: dict[tuple[str, str | None, str | None], _Circuit] = {}
        self._lock = RLock()
        initialized_at = _aware(self.clock.now())
        self._missing_observed_at = {
            (component, None, None): initialized_at
            for component in self.config.required_components
        }

    def observe(
        self,
        component: str,
        *,
        model: str | None = None,
        capability: str | None = None,
        failure: FailureType | str | None = None,
        success: bool = False,
        state: HealthState | None = None,
        required: bool = True,
        latency_ms: int | None = None,
    ) -> HealthObservation:
        """Record one sanitized observation for an exact component scope.

        An open circuit only recovers from results admitted by ``admit_probe``.
        General traffic cannot accidentally close it.  Task quality and budget
        outcomes are returned without refreshing or poisoning health evidence.
        """

        component = _name(component, "component")
        model = _optional_name(model, "model")
        capability = _optional_name(capability, "capability")
        if not isinstance(success, bool) or not isinstance(required, bool):
            raise TypeError("success and required must be booleans")
        normalized_failure = FailureType(failure) if failure is not None else None
        if success and normalized_failure is not None:
            raise ValueError("success and failure are mutually exclusive")
        if state not in {None, "HEALTHY", "DEGRADED", "UNHEALTHY"}:
            raise ValueError("invalid health state")
        if latency_ms is not None and (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, int)
            or latency_ms < 0
        ):
            raise ValueError("latency_ms must be a nonnegative integer")

        key = (component, model, capability)
        now = _aware(self.clock.now())
        with self._lock:
            previous = self._observations.get(key)
            if normalized_failure in _NON_HEALTH_FAILURES:
                return self._view(previous, key, now, required=required)

            circuit = self._circuits.setdefault(key, _Circuit(deque()))
            self._prune(circuit, now)
            probe_result = circuit.state == "half_open" and circuit.pending_probes > 0
            if probe_result:
                circuit.pending_probes -= 1

            poisons_circuit = _poisons_circuit(component, normalized_failure)
            if probe_result:
                if success:
                    circuit.recovery_successes += 1
                    if circuit.recovery_successes >= self.config.recovery_success_threshold:
                        circuit.state = "closed"
                        circuit.opened_at = None
                        circuit.admitted_probes = 0
                        circuit.pending_probes = 0
                        circuit.recovery_successes = 0
                        circuit.failures.clear()
                else:
                    if poisons_circuit:
                        circuit.failures.append(now)
                    self._open(circuit, now)
            elif normalized_failure is not None or state == "UNHEALTHY":
                if poisons_circuit:
                    circuit.failures.append(now)
                if (
                    circuit.state == "closed"
                    and poisons_circuit
                    and len(circuit.failures) >= self.config.failure_threshold
                ):
                    self._open(circuit, now)

            derived_state: HealthState
            if circuit.state == "open":
                derived_state = "UNHEALTHY"
            elif circuit.state == "half_open":
                derived_state = "DEGRADED"
            elif state is not None:
                derived_state = state
            elif success:
                derived_state = "HEALTHY"
            elif normalized_failure is not None:
                derived_state = "DEGRADED" if component in {"provider", "evaluator", "tool"} else "UNHEALTHY"
            elif not required:
                derived_state = "DEGRADED"
            else:
                raise ValueError("an observation requires success, failure, or state")

            check_status = "disabled" if not required and not success and state is None else "observed"
            last_success = now if success else (previous.last_success_at if previous else None)
            observation = HealthObservation(
                component=component,
                model=model,
                capability=capability,
                state=derived_state,
                observed_at=now,
                valid_until=now + _ms(self.config.freshness_ms),
                last_success_at=last_success,
                required=required,
                check_status=check_status,
                failure=normalized_failure,
                failure_count=len(circuit.failures),
                circuit_state=circuit.state,
                latency_ms=latency_ms,
            )
            self._observations[key] = observation
            return observation

    def admit_probe(
        self,
        component: str,
        *,
        model: str | None = None,
        capability: str | None = None,
    ) -> bool:
        """Admit one recovery probe after cooldown, within the configured bound."""

        key = (
            _name(component, "component"),
            _optional_name(model, "model"),
            _optional_name(capability, "capability"),
        )
        now = _aware(self.clock.now())
        with self._lock:
            circuit = self._circuits.setdefault(key, _Circuit(deque()))
            self._prune(circuit, now)
            if circuit.state == "closed":
                return True
            if circuit.state == "open":
                if circuit.opened_at is None or now < circuit.opened_at + _ms(self.config.cooldown_ms):
                    return False
                circuit.state = "half_open"
                circuit.admitted_probes = 0
                circuit.pending_probes = 0
                circuit.recovery_successes = 0
            if circuit.admitted_probes >= self.config.half_open_max_probes:
                return False
            circuit.admitted_probes += 1
            circuit.pending_probes += 1
            return True

    def snapshot(self) -> HealthSnapshot:
        """Return immutable current evidence; this method never runs probes."""

        now = _aware(self.clock.now())
        with self._lock:
            observations = self._current_observations(now)
            relevant = tuple(
                item for item in observations if item.check_status != "disabled"
            )
            observed_at = (
                max(item.observed_at for item in relevant) if relevant else now
            )
            valid_until = (
                min(item.valid_until for item in relevant) if relevant else now
            )
            payload = {
                "config_version": self.config.version,
                "observed_at": observed_at.isoformat(),
                "valid_until": valid_until.isoformat(),
                "observations": [
                    item.model_dump(mode="json", exclude_none=False) for item in observations
                ],
            }
            digest = sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            return HealthSnapshot(
                snapshot_id=f"health-{digest}",
                config_version=self.config.version,
                observed_at=observed_at,
                valid_until=valid_until,
                synthetic=not self.config.live_probes_enabled,
                observations=observations,
            )

    def components(
        self, snapshot: HealthSnapshot | None = None
    ) -> list[dict[str, object]]:
        """Return JSON-safe component observations for the HTTP boundary."""

        current = snapshot or self.snapshot()
        self._validate_snapshot(current)
        return [item.model_dump(mode="json") for item in current.observations]

    def available(
        self,
        component: str,
        *,
        model: str | None = None,
        capability: str | None = None,
    ) -> bool:
        """Return whether an exact scope has fresh, closed, usable evidence."""

        key = (
            _name(component, "component"),
            _optional_name(model, "model"),
            _optional_name(capability, "capability"),
        )
        now = _aware(self.clock.now())
        with self._lock:
            observation = self._observations.get(key)
            if observation is None:
                return False
            return _available(self._view(observation, key, now, required=observation.required))

    def dependency_readiness(
        self, snapshot: HealthSnapshot | None = None
    ) -> HealthReadiness:
        """Assess only the globally required configuration/runtime dependencies."""

        current_snapshot = snapshot or self.snapshot()
        self._validate_snapshot(current_snapshot)
        current = current_snapshot.observations
        by_component = {
            item.component: item
            for item in current
            if item.model is None and item.capability is None
        }
        blockers: list[str] = []
        degraded = False
        for component in self.config.required_components:
            item = by_component.get(component)
            if item is None:
                blockers.append(f"{component}:missing")
            elif not _available(item):
                blockers.append(f"{component}:{_unavailable_reason(item)}")
            elif item.state == "DEGRADED":
                degraded = True
        ordered = tuple(sorted(set(blockers)))
        if ordered:
            return HealthReadiness(False, "UNHEALTHY", ordered)
        return HealthReadiness(True, "DEGRADED" if degraded else "HEALTHY", ())

    def operation_readiness(
        self,
        environment: EnvironmentSnapshot,
        *,
        execution_authorized: bool,
        finite_limits: bool,
        synthetic_provider: bool,
        snapshot: HealthSnapshot | None = None,
    ) -> HealthReadiness:
        """Compose health with the safe prerequisites for offline execution.

        Adapter-specific facts are supplied as booleans so health remains free
        of FastAPI, provider SDK, repository, and orchestration dependencies.
        Evaluator and tool scopes are checked by their operations and therefore
        do not block an unrelated generation path here.
        """

        if not all(
            isinstance(value, bool)
            for value in (execution_authorized, finite_limits, synthetic_provider)
        ):
            raise TypeError("operation readiness facts must be booleans")
        dependency = self.dependency_readiness(snapshot)
        blockers = list(dependency.blockers)
        degraded = dependency.state == "DEGRADED"
        now = _aware(self.clock.now())

        if not execution_authorized:
            blockers.append("approval_required")
        if not finite_limits:
            blockers.append("finite_execution_limits_required")
        if not environment.synthetic:
            blockers.append("production_execution_disabled")
        if not synthetic_provider:
            blockers.append("mock_provider_required")
        if not environment.durable_retention:
            blockers.append("durable_retention_unavailable")
        if not environment.recovery_bounded:
            blockers.append("recovery_unconfigured")
        if (
            environment.health_snapshot_id is None
            or environment.health_observed_at is None
            or environment.health_valid_until is None
            or environment.health_observed_at > now
            or environment.health_valid_until <= now
        ):
            blockers.append("stale_snapshot")

        models = tuple(environment.models.values())
        available_models = tuple(
            model
            for model in models
            if model.usable
            and model.state in {"HEALTHY", "DEGRADED"}
            and model.account_access == "verified"
        )
        if not available_models:
            blockers.append("no_permitted_model_ready")
        elif any(
            not model.usable
            or model.state != "HEALTHY"
            or model.account_access != "verified"
            for model in models
        ):
            degraded = True

        ordered = tuple(sorted(set(blockers)))
        if ordered:
            return HealthReadiness(False, "UNHEALTHY", ordered)
        return HealthReadiness(True, "DEGRADED" if degraded else "HEALTHY", ())

    def readiness(self, snapshot: HealthSnapshot | None = None) -> HealthReadiness:
        """Assess required dependencies and known provider model coverage."""

        current_snapshot = snapshot or self.snapshot()
        self._validate_snapshot(current_snapshot)
        current = current_snapshot.observations
        dependency = self.dependency_readiness(current_snapshot)
        blockers = list(dependency.blockers)
        degraded = dependency.state == "DEGRADED"

        provider = [item for item in current if item.component == "provider" and item.model is not None and item.required]
        if provider:
            model_level = [item for item in provider if item.capability is None]
            candidates = model_level or provider
            if not any(_available(item) for item in candidates):
                blockers.append("provider:no_model_ready")
            elif any(not _available(item) or item.state == "DEGRADED" for item in candidates):
                degraded = True

        ordered = tuple(sorted(set(blockers)))
        if ordered:
            return HealthReadiness(False, "UNHEALTHY", ordered)
        return HealthReadiness(True, "DEGRADED" if degraded else "HEALTHY", ())

    def apply(
        self,
        environment: EnvironmentSnapshot,
        required_capabilities: Iterable[str] = (),
        *,
        snapshot: HealthSnapshot | None = None,
    ) -> EnvironmentSnapshot:
        """Project provider generation evidence onto an environment snapshot.

        Evaluator and tool scopes are deliberately excluded from the routing
        model projection.  Callers gate those operations with ``readiness`` or
        their scoped component observations.
        """

        capabilities = tuple(sorted({_name(value, "capability") for value in required_capabilities}))
        health = snapshot or self.snapshot()
        self._validate_snapshot(health)
        observations = health.observations
        models: dict[str, ModelHealth] = {}
        routing_evidence = [item for item in observations if item.component in self.config.required_components
            and item.model is None and item.capability is None]
        for alias, existing in environment.models.items():
            relevant = [
                item
                for item in observations
                if item.component == "provider"
                and item.model in {None, alias}
                and item.capability is None
            ]
            for capability in capabilities:
                scoped = [
                    item
                    for item in observations
                    if item.component == "provider"
                    and item.model in {None, alias}
                    and item.capability == capability
                ]
                if scoped:
                    relevant.extend(scoped)
                else:
                    relevant.append(self._missing(("provider", alias, capability), health.observed_at, True))

            if not relevant:
                relevant.append(self._missing(("provider", alias, None), health.observed_at, True))
            unavailable = not existing.usable or existing.state == "UNHEALTHY" or any(not _available(item) for item in relevant)
            degraded = existing.state == "DEGRADED" or any(item.state == "DEGRADED" for item in relevant)
            if not unavailable:
                routing_evidence.extend(relevant)
            models[alias] = ModelHealth(
                state="UNHEALTHY" if unavailable else ("DEGRADED" if degraded else "HEALTHY"),
                account_access=existing.account_access,
                usable=not unavailable,
            )

        values = environment.model_dump(mode="python")
        values.update(
            models=models,
            health_snapshot_id=health.snapshot_id,
            # The full snapshot retains stale unrelated paths; this projection
            # certifies only global prerequisites and usable generation paths.
            health_observed_at=max((item.observed_at for item in routing_evidence), default=health.observed_at),
            health_valid_until=min((item.valid_until for item in routing_evidence), default=health.valid_until),
        )
        return EnvironmentSnapshot.model_validate(values)

    def run_probes(
        self,
        probes: Iterable[HealthProbe],
        *,
        authorized: bool = False,
        budget_cap_usd: Decimal | str | None = None,
    ) -> tuple[HealthObservation, ...]:
        """Run explicitly authorized probes within count, timeout, and cost bounds.

        The bounded batch and its declared maximum cost are validated before
        dispatch.  Adapter exceptions become sanitized failure observations;
        exception text and return payloads are never retained.
        """

        if not self.config.live_probes_enabled or not authorized:
            return ()
        cap = _probe_money(budget_cap_usd, "probe budget cap", positive=True)
        batch = tuple(islice(iter(probes), self.config.max_probes_per_run))
        costs: list[Decimal] = []
        for probe in batch:
            if not isinstance(probe, HealthProbe):
                raise TypeError("probe does not implement the health probe protocol")
            costs.append(
                _probe_money(
                    probe.cost_upper_bound_usd,
                    "probe cost upper bound",
                    positive=False,
                )
            )
        if sum(costs, Decimal("0")) > cap:
            raise ValueError("probe batch exceeds its explicit budget cap")

        observations: list[HealthObservation] = []
        for probe in batch:
            key = (probe.component, probe.model, probe.capability)
            circuit = self._circuits.get(key)
            if circuit is not None and circuit.state != "closed" and not self.admit_probe(
                probe.component, model=probe.model, capability=probe.capability
            ):
                continue
            try:
                result = probe.run(self.config.probe_timeout_ms)
                if not isinstance(result, HealthProbeResult):
                    raise TypeError("probe returned an invalid result")
            except Exception:
                result = HealthProbeResult(
                    success=False,
                    state="UNHEALTHY",
                    failure=FailureType.PROVIDER_FAILURE,
                )
            observations.append(
                self.observe(
                    probe.component,
                    model=probe.model,
                    capability=probe.capability,
                    failure=result.failure,
                    success=result.success,
                    state=result.state,
                    required=probe.required,
                    latency_ms=result.latency_ms,
                )
            )
        return tuple(observations)

    def _current_observations(self, now: datetime) -> tuple[HealthObservation, ...]:
        keys = set(self._observations)
        keys.update((component, None, None) for component in self.config.required_components)
        return tuple(
            self._view(self._observations.get(key), key, now, required=key[0] in self.config.required_components)
            for key in sorted(keys, key=lambda value: tuple(part or "" for part in value))
        )

    def _view(
        self,
        observation: HealthObservation | None,
        key: tuple[str, str | None, str | None],
        now: datetime,
        *,
        required: bool,
    ) -> HealthObservation:
        if observation is None:
            return self._missing(key, now, required)
        circuit = self._circuits.get(key)
        circuit_state: CircuitState = circuit.state if circuit else observation.circuit_state
        if observation.check_status == "disabled":
            return observation.model_copy(
                update={
                    "circuit_state": circuit_state,
                    "failure_count": self._failure_count(circuit, now),
                }
            )
        last_success_invalid = observation.last_success_at is not None and (
            observation.last_success_at.utcoffset() is None
            or observation.last_success_at > observation.observed_at
        )
        stale = (
            observation.observed_at > now
            or now >= observation.valid_until
            or last_success_invalid
        )
        state: HealthState
        if stale or circuit_state == "open":
            state = "UNHEALTHY"
        elif circuit_state == "half_open":
            state = "DEGRADED"
        else:
            state = observation.state
        return observation.model_copy(
            update={
                "state": state,
                "check_status": "stale" if stale else observation.check_status,
                "circuit_state": circuit_state,
                "failure_count": self._failure_count(circuit, now),
            }
        )

    def _missing(
        self,
        key: tuple[str, str | None, str | None],
        now: datetime,
        required: bool,
    ) -> HealthObservation:
        observed_at = self._missing_observed_at.get(key, now)
        return HealthObservation(
            component=key[0],
            model=key[1],
            capability=key[2],
            state="UNHEALTHY",
            observed_at=observed_at,
            valid_until=observed_at + _ms(self.config.freshness_ms),
            required=required,
            check_status="missing",
        )

    def _validate_snapshot(self, snapshot: HealthSnapshot) -> None:
        if not isinstance(snapshot, HealthSnapshot):
            raise TypeError("snapshot must be a HealthSnapshot")
        if snapshot.config_version != self.config.version:
            raise ValueError("health snapshot config version mismatch")

    def _failure_count(self, circuit: _Circuit | None, now: datetime) -> int:
        if circuit is None:
            return 0
        cutoff = now - _ms(self.config.failure_window_ms)
        return sum(stamp >= cutoff for stamp in circuit.failures)

    def _prune(self, circuit: _Circuit, now: datetime) -> None:
        cutoff = now - _ms(self.config.failure_window_ms)
        while circuit.failures and circuit.failures[0] < cutoff:
            circuit.failures.popleft()

    @staticmethod
    def _open(circuit: _Circuit, now: datetime) -> None:
        circuit.state = "open"
        circuit.opened_at = now
        circuit.admitted_probes = 0
        circuit.pending_probes = 0
        circuit.recovery_successes = 0


class SyntheticHealthSource:
    """Explicit offline source for deterministic startup/checkpoint evidence."""

    def __init__(self, service: HealthService) -> None:
        self.service = service

    def seed(
        self,
        *,
        models: Iterable[str] = (),
        provider_capabilities: Iterable[str] = (),
        optional_disabled: Iterable[str] = (),
    ) -> HealthSnapshot:
        for component in self.service.config.required_components:
            self.service.observe(component, success=True)
        capabilities = tuple(provider_capabilities)
        for model in models:
            self.service.observe("provider", model=model, success=True)
            for capability in capabilities:
                self.service.observe(
                    "provider", model=model, capability=capability, success=True
                )
        for component in optional_disabled:
            self.service.observe(component, required=False)
        return self.service.snapshot()


def _available(observation: HealthObservation) -> bool:
    return (
        observation.check_status == "observed"
        and observation.circuit_state == "closed"
        and observation.state in {"HEALTHY", "DEGRADED"}
    )


def _poisons_circuit(component: str, failure: FailureType | None) -> bool:
    if failure is None:
        return False
    if component == "tool":
        return failure in _INFRASTRUCTURE_FAILURES | {FailureType.TOOL_FAILURE}
    return failure in _INFRASTRUCTURE_FAILURES


def _unavailable_reason(observation: HealthObservation) -> str:
    if observation.check_status in {"missing", "stale", "disabled"}:
        return observation.check_status
    if observation.circuit_state != "closed":
        return observation.circuit_state
    return "unhealthy"


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _optional_name(value: str | None, label: str) -> str | None:
    return None if value is None else _name(value, label)


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("health clock must return an aware datetime")
    return value


def _ms(value: int) -> timedelta:
    return timedelta(milliseconds=value)


def _probe_money(
    value: Decimal | str | None,
    label: str,
    *,
    positive: bool,
) -> Decimal:
    if not isinstance(value, (Decimal, str)):
        raise ValueError(f"{label} must be an explicit decimal string or Decimal")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} is invalid") from error
    if not amount.is_finite() or amount < 0 or (positive and amount <= 0):
        qualifier = "positive and finite" if positive else "nonnegative and finite"
        raise ValueError(f"{label} must be {qualifier}")
    return amount


__all__ = [
    "HealthProbe",
    "HealthProbeResult",
    "HealthReadiness",
    "HealthService",
    "SyntheticHealthSource",
]
