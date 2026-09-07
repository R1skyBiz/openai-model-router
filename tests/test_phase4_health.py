from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from model_router.core.contracts import EnvironmentSnapshot, FailureType
from model_router.core.phase4_contracts import HealthConfig
from model_router.execution.clock import MockClock
from model_router.health import (
    HealthProbeResult,
    HealthService,
    SyntheticHealthSource,
)


NOW = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)


def config(**updates):
    values = dict(
        version="health-test-v1",
        freshness_ms=1_000,
        failure_window_ms=500,
        failure_threshold=3,
        cooldown_ms=200,
        half_open_max_probes=1,
        recovery_success_threshold=1,
        max_probes_per_run=2,
        probe_timeout_ms=50,
        live_probes_enabled=False,
        required_components=("configuration", "database", "telemetry"),
    )
    values.update(updates)
    return HealthConfig(**values)


def service(**updates):
    clock = MockClock(NOW)
    return clock, HealthService(clock, config(**updates))


def environment():
    return EnvironmentSnapshot(
        snapshot_id="before-health",
        synthetic=True,
        clock=NOW,
        pricing_version="test-pricing",
        models={
            "luna": {"state": "HEALTHY", "account_access": "verified"},
            "terra": {"state": "HEALTHY", "account_access": "verified"},
        },
    )


def test_snapshots_are_frozen_versioned_deterministic_and_reads_do_not_probe():
    _, health = service()
    seed = SyntheticHealthSource(health).seed(models=("luna", "terra"))

    assert seed == health.snapshot()
    assert seed.snapshot_id.startswith("health-") and len(seed.snapshot_id) == 71
    assert seed.config_version == "health-test-v1"
    assert [row["component"] for row in health.components()] == sorted(
        row["component"] for row in health.components()
    )
    with pytest.raises(Exception):
        seed.observations += ()


def test_missing_and_stale_required_checks_are_explicitly_unavailable():
    clock, health = service()
    initial = health.snapshot()
    assert {item.check_status for item in initial.observations} == {"missing"}
    assert health.dependency_readiness().ready is False

    SyntheticHealthSource(health).seed()
    assert health.dependency_readiness().ready is True
    clock.advance(1_000)
    stale = health.snapshot()
    assert {item.check_status for item in stale.observations} == {"stale"}
    assert health.dependency_readiness().blockers == (
        "configuration:stale",
        "database:stale",
        "telemetry:stale",
    )


def test_snapshot_reads_do_not_extend_source_expiry_or_identity():
    clock, health = service()
    first = SyntheticHealthSource(health).seed(models=("luna",))
    clock.advance(500)
    second = health.snapshot()
    assert second.snapshot_id == first.snapshot_id
    assert second.observed_at == first.observed_at
    assert second.valid_until == first.valid_until == NOW + timedelta(seconds=1)

    clock.advance(500)
    stale = health.snapshot()
    assert stale.snapshot_id != first.snapshot_id
    assert stale.valid_until == first.valid_until
    assert {item.check_status for item in stale.observations} == {"stale"}


def test_disabled_optional_component_stays_explicitly_disabled():
    clock, health = service()
    health.observe("optional_evaluator", required=False)
    clock.advance(2_000)
    item = next(
        item
        for item in health.snapshot().observations
        if item.component == "optional_evaluator"
    )
    assert item.check_status == "disabled"
    assert item.required is False


def test_failure_window_and_explicit_bounded_half_open_recovery():
    clock, health = service()
    SyntheticHealthSource(health).seed(models=("luna",))
    for _ in range(2):
        result = health.observe("provider", model="luna", failure="RATE_LIMIT")
        assert result.circuit_state == "closed"

    clock.advance(501)
    first_in_new_window = health.observe("provider", model="luna", failure="TIMEOUT")
    assert first_in_new_window.failure_count == 1
    health.observe("provider", model="luna", failure="TIMEOUT")
    opened = health.observe("provider", model="luna", failure="TIMEOUT")
    assert opened.circuit_state == "open"
    assert not health.available("provider", model="luna")

    assert health.admit_probe("provider", model="luna") is False
    clock.advance(200)
    assert health.admit_probe("provider", model="luna") is True
    assert health.admit_probe("provider", model="luna") is False
    provider = next(
        item
        for item in health.snapshot().observations
        if item.component == "provider" and item.model == "luna"
    )
    assert provider.circuit_state == "half_open"

    recovered = health.observe("provider", model="luna", success=True)
    assert recovered.circuit_state == "closed"
    assert recovered.failure_count == 0
    assert health.available("provider", model="luna")


def test_open_circuit_reopens_on_failed_probe_and_general_success_cannot_close_it():
    clock, health = service(failure_threshold=1)
    health.observe("provider", model="luna", failure="PROVIDER_FAILURE")
    health.observe("provider", model="luna", success=True)
    assert not health.available("provider", model="luna")

    clock.advance(200)
    assert health.admit_probe("provider", model="luna")
    failed = health.observe("provider", model="luna", failure="RATE_LIMIT")
    assert failed.circuit_state == "open"
    assert not health.admit_probe("provider", model="luna")


def test_any_admitted_probe_failure_restarts_cooldown_without_poisoning_count():
    clock, health = service(failure_threshold=1)
    health.observe("provider", model="luna", failure="TIMEOUT")
    clock.advance(200)
    assert health.admit_probe("provider", model="luna")
    failed = health.observe("provider", model="luna", failure="MALFORMED_OUTPUT")
    assert failed.circuit_state == "open"
    assert failed.failure_count == 1
    assert not health.admit_probe("provider", model="luna")


def test_quality_does_not_poison_or_refresh_provider_health():
    clock, health = service()
    initial = health.observe("provider", model="luna", success=True)
    clock.advance(10)
    ignored = health.observe(
        "provider", model="luna", failure=FailureType.QUALITY_FAILURE
    )
    assert ignored.observed_at == initial.observed_at
    assert ignored.failure_count == 0
    assert ignored.state == "HEALTHY"


@pytest.mark.parametrize(
    "failure",
    ("MALFORMED_OUTPUT", "VALIDATION_FAILURE", "UNKNOWN_FAILURE", "TOOL_FAILURE"),
)
def test_non_infrastructure_failures_do_not_poison_provider_circuit(failure):
    _, health = service(failure_threshold=1)
    result = health.observe("provider", model="luna", failure=failure)
    assert result.state == "DEGRADED"
    assert result.circuit_state == "closed"
    assert result.failure_count == 0


def test_tool_failure_only_poison_tool_scope():
    _, health = service(failure_threshold=1)
    tool = health.observe("tool", capability="search", failure="TOOL_FAILURE")
    evaluator = health.observe("evaluator", model="luna", failure="TOOL_FAILURE")
    assert tool.circuit_state == "open"
    assert evaluator.circuit_state == "closed"


def test_tool_and_evaluator_outages_do_not_block_unrelated_readiness():
    _, health = service(failure_threshold=1)
    SyntheticHealthSource(health).seed(models=("luna",))
    health.observe("tool", capability="search", failure="TOOL_FAILURE")
    health.observe("evaluator", model="luna", failure="PROVIDER_FAILURE")
    assert health.readiness().ready is True
    assert not health.available("tool", capability="search")
    assert not health.available("evaluator", model="luna")


def test_apply_projects_only_generation_provider_and_required_capability_scopes():
    _, health = service()
    SyntheticHealthSource(health).seed(
        models=("luna", "terra"), provider_capabilities=("structured_output",)
    )
    health.observe("evaluator", model="luna", failure="PROVIDER_FAILURE")
    for _ in range(3):
        health.observe("tool", capability="search", failure="TOOL_FAILURE")
    for _ in range(3):
        health.observe(
            "provider",
            model="luna",
            capability="structured_output",
            failure="PROVIDER_FAILURE",
        )

    projected = health.apply(environment(), required_capabilities=("structured_output",))
    assert projected.models["luna"].state == "UNHEALTHY"
    assert projected.models["luna"].usable is False
    assert projected.models["terra"].state == "HEALTHY"
    assert projected.models["terra"].usable is True
    assert projected.health_snapshot_id == health.snapshot().snapshot_id

    plain = health.apply(environment())
    assert plain.models["luna"].state == "HEALTHY"
    assert not health.available("evaluator", model="terra")
    assert not health.available("tool", capability="search")


def test_apply_treats_missing_provider_verification_as_unavailable():
    _, health = service()
    SyntheticHealthSource(health).seed()
    projected = health.apply(environment())
    assert all(not model.usable for model in projected.models.values())
    assert {model.state for model in projected.models.values()} == {"UNHEALTHY"}


def test_apply_uses_the_exact_supplied_snapshot():
    clock, health = service()
    snapshot = SyntheticHealthSource(health).seed(models=("luna", "terra"))
    clock.advance(10)
    projected = health.apply(environment(), snapshot=snapshot)
    assert projected.health_snapshot_id == snapshot.snapshot_id
    assert projected.health_observed_at == snapshot.observed_at
    assert projected.health_valid_until == snapshot.valid_until


def test_readiness_allows_safe_degraded_dependency_but_rejects_no_model():
    _, health = service()
    SyntheticHealthSource(health).seed(models=("luna", "terra"))
    health.observe("telemetry", state="DEGRADED")
    for _ in range(3):
        health.observe("provider", model="luna", failure="RATE_LIMIT")
    status = health.readiness()
    assert status.ready and status.state == "DEGRADED"

    for _ in range(3):
        health.observe("provider", model="terra", failure="TIMEOUT")
    status = health.readiness()
    assert not status.ready and status.state == "UNHEALTHY"
    assert status.blockers == ("provider:no_model_ready",)


class _Probe:
    model = None
    capability = None
    required = True
    cost_upper_bound_usd = "0.01"

    def __init__(self, component):
        self.component = component
        self.timeouts = []

    def run(self, timeout_ms):
        self.timeouts.append(timeout_ms)
        return HealthProbeResult(success=True, latency_ms=2)


def test_probe_source_is_opt_in_timeout_bounded_and_count_bounded():
    _, offline = service()
    assert offline.run_probes((_Probe("one"),)) == ()

    _, live = service(live_probes_enabled=True)
    probes = (_Probe("one"), _Probe("two"), _Probe("three"))
    assert live.run_probes(probes) == ()
    observed = live.run_probes(
        probes, authorized=True, budget_cap_usd="0.02"
    )
    assert len(observed) == 2
    assert probes[0].timeouts == [50] and probes[1].timeouts == [50]
    assert probes[2].timeouts == []


def test_probe_batch_validates_budget_before_dispatch():
    _, health = service(live_probes_enabled=True)
    probes = (_Probe("one"), _Probe("two"))
    with pytest.raises(ValueError, match="exceeds"):
        health.run_probes(probes, authorized=True, budget_cap_usd="0.019")
    assert all(not probe.timeouts for probe in probes)
    with pytest.raises(ValueError, match="positive and finite"):
        health.run_probes(probes, authorized=True, budget_cap_usd="0")


def test_probe_iteration_is_bounded_even_when_every_circuit_is_blocked():
    _, health = service(live_probes_enabled=True, failure_threshold=1)
    health.observe("provider", model="luna", failure="TIMEOUT")
    inspected = []

    def infinite_blocked_probes():
        while True:
            inspected.append(len(inspected))
            probe = _Probe("provider")
            probe.model = "luna"
            yield probe

    assert health.run_probes(
        infinite_blocked_probes(), authorized=True, budget_cap_usd="1"
    ) == ()
    assert len(inspected) == health.config.max_probes_per_run


def test_probe_exceptions_are_sanitized_without_raw_response_data():
    class FailingProbe(_Probe):
        def run(self, timeout_ms):
            raise RuntimeError("raw-provider-secret")

    _, health = service(live_probes_enabled=True)
    observed = health.run_probes(
        (FailingProbe("provider"),),
        authorized=True,
        budget_cap_usd="0.01",
    )
    assert observed[0].failure == FailureType.PROVIDER_FAILURE
    assert observed[0].state == "UNHEALTHY"
    assert "raw-provider-secret" not in observed[0].model_dump_json()


def test_future_observation_and_invalid_last_success_are_unavailable():
    clock, health = service()
    observed = health.observe("provider", model="luna", success=True)
    assert observed.last_success_at is not None
    assert observed.last_success_at.utcoffset() is not None

    clock._now = NOW - timedelta(milliseconds=1)
    future = next(
        item
        for item in health.snapshot().observations
        if item.component == "provider"
    )
    assert future.check_status == "stale"
    assert future.state == "UNHEALTHY"
    assert not health.available("provider", model="luna")

    clock._now = NOW
    health._observations[("provider", "luna", None)] = observed.model_copy(
        update={"last_success_at": observed.observed_at + timedelta(milliseconds=1)}
    )
    invalid = next(
        item
        for item in health.snapshot().observations
        if item.component == "provider"
    )
    assert invalid.check_status == "stale"
    assert invalid.state == "UNHEALTHY"


def test_fresh_health_cannot_relax_trusted_model_restrictions():
    _, health=service()
    SyntheticHealthSource(health).seed(models=('luna','terra'))
    env=environment()
    models=dict(env.models)
    models['luna']=models['luna'].model_copy(update={'state':'UNHEALTHY','usable':False})
    models['terra']=models['terra'].model_copy(update={'state':'DEGRADED'})
    projected=health.apply(env.model_copy(update={'models':models}))
    assert not projected.models['luna'].usable and projected.models['luna'].state=='UNHEALTHY'
    assert projected.models['terra'].state=='DEGRADED'


def test_stale_unrelated_evaluator_or_model_does_not_expire_safe_generation_path():
    clock, health=service()
    SyntheticHealthSource(health).seed(models=('luna','terra'))
    health.observe('evaluator',model='terra',success=True)
    clock.advance(900)
    SyntheticHealthSource(health).seed(models=('luna',))
    clock.advance(101)
    snapshot=health.snapshot()
    projected=health.apply(environment(),snapshot=snapshot)
    assert snapshot.valid_until<clock.now()
    assert projected.health_snapshot_id==snapshot.snapshot_id
    assert projected.health_valid_until>clock.now()
    assert projected.models['luna'].usable and not projected.models['terra'].usable
    assert not health.available('evaluator',model='terra')


def test_required_database_failure_is_not_ready_without_explicit_safe_alternate():
    _, health=service()
    SyntheticHealthSource(health).seed(models=('luna',))
    health.observe('database',failure=FailureType.PROVIDER_FAILURE)
    assert not health.dependency_readiness().ready
    health.observe('database',state='DEGRADED')
    assert health.dependency_readiness().ready
