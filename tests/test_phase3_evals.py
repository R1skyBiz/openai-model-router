from __future__ import annotations

from pathlib import Path

import pytest

from evals.grader import grade
from evals.phase3_adapter import (
    DEFERRED_CASE,
    DEFERRED_REASON,
    observe,
    observe_deferred,
)
from evals.run_local import load_cases, load_contract
from evals.run_phase3 import run
from model_router.policy.loader import load_bundle


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(ROOT / "config")


@pytest.fixture(scope="module")
def cases():
    return {case.id: case for case in load_cases()}


def test_all_supported_recovery_scenarios_execute_and_grade(bundle, cases):
    manifest, catalog, vocabulary = load_contract()
    executed = 0
    for case in cases.values():
        if case.scenario is None or case.id == DEFERRED_CASE:
            continue
        observation, execution = observe(case, bundle)
        assert grade(
            case, observation, catalog, manifest["policy_version"], vocabulary
        ) == [], case.id
        assert execution.task.attempts, case.id
        assert execution.task.recovery_actions, case.id
        executed += 1
    assert executed == 17


def test_quality_sequence_uses_real_dispatch_targets(bundle, cases):
    observation, execution = observe(cases["quality_tier_success"], bundle)
    assert [
        (request["model_alias"], request["reasoning_effort"])
        for request in execution.provider_requests
    ] == [
        ("terra", "medium"),
        ("terra", "high"),
        ("sol", "medium"),
    ]
    assert [step.action for step in observation.recovery] == [
        "increase_effort",
        "increase_tier",
        "stop_success",
    ]


def test_partial_scripts_execute_follow_on_work_but_project_authored_horizon(
    bundle, cases
):
    outage_observation, outage = observe(cases["provider_outage_fallback"], bundle)
    assert [request["model_alias"] for request in outage.provider_requests] == [
        "terra",
        "luna",
    ]
    assert [action.action for action in outage.task.recovery_actions] == [
        "health_aware_fallback",
        "stop_success",
    ]
    assert [step.action for step in outage_observation.recovery] == [
        "health_aware_fallback"
    ]
    assert outage_observation.facts["projection_horizon"] == 1
    assert outage_observation.facts["recorded_recovery_actions"] == 2

    alternate_observation, alternate = observe(cases["alternate_tool"], bundle)
    assert [call["tool"] for call in alternate.tool_calls] == [
        "primary_reader",
        "backup_reader",
    ]
    assert [action.action for action in alternate.task.recovery_actions] == [
        "alternate_tool",
        "stop_success",
    ]
    assert [step.action for step in alternate_observation.recovery] == [
        "alternate_tool"
    ]


def test_adapter_never_reads_expected_envelope(bundle, cases):
    class PoisonExpected:
        def __init__(self, case):
            self._case = case

        def __getattr__(self, name):
            if name == "expected":
                raise AssertionError("adapter read the independent expected envelope")
            return getattr(self._case, name)

    observation, execution = observe(
        PoisonExpected(cases["provider_timeout"]), bundle
    )
    assert observation.case_id == "provider_timeout"
    assert execution.task.counters.infrastructure_retries == 1


def test_evaluator_infrastructure_is_explicitly_deferred_and_blocks_generation(
    bundle, cases
):
    case = cases[DEFERRED_CASE]
    task, provider = observe_deferred(case, bundle)
    assert "Phase 4" in DEFERRED_REASON
    assert task.status.value == "blocked"
    assert task.failure.cause_code == "stronger_validation_unavailable"
    assert task.attempts == ()
    assert provider.call_count == 0


def test_phase3_report_covers_178_of_179_without_fabricating_evaluator_success():
    report, observations = run()
    assert report["total_corpus"] == 179
    assert report["applicable"] == 178
    assert report["passed"] == 178
    assert report["failed"] == 0
    assert report["recovery_scenarios_executed"] == 17
    assert report["recovery_scenarios_total"] == 18
    assert report["skipped"] == {DEFERRED_CASE: DEFERRED_REASON}
    assert report["evaluator_gate"] == {
        "case_id": DEFERRED_CASE,
        "blocked_before_generation": True,
        "provider_dispatches": 0,
        "cause_code": "stronger_validation_unavailable",
    }
    assert len(observations) == 178
