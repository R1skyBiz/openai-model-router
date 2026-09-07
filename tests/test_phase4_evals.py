from pathlib import Path

from evals.grader import grade
from evals.phase4_adapter import observe
from evals.phase4_regressions import load_regressions, run_regressions
from evals.run_local import load_cases, load_contract
from evals.run_phase4 import run
from model_router.core.contracts import FailureType
from model_router.policy.loader import load_bundle


ROOT = Path(__file__).parents[1]


def evaluator_case():
    return next(case for case in load_cases() if case.id == "evaluator_infrastructure")


def test_authored_case_uses_real_retry_without_regeneration():
    case = evaluator_case()
    bundle = load_bundle(ROOT / "config")
    observation, execution = observe(case, bundle)
    manifest, catalog, vocabulary = load_contract()
    assert grade(case, observation, catalog, manifest["policy_version"], vocabulary) == []

    task = execution.task
    assert task.status.value == "succeeded"
    assert len(task.attempts) == len(execution.provider_requests) == 1
    assert task.counters.generation_attempts == 1
    assert task.counters.infrastructure_retries == 0
    assert len(task.evaluator_attempts) == len(execution.evaluator_requests) == 2
    assert [attempt.purpose for attempt in task.evaluator_attempts] == [
        "evaluation",
        "evaluation",
    ]
    assert all(
        attempt.parent_attempt_id == task.attempts[0].attempt_id
        for attempt in task.evaluator_attempts
    )
    assert task.evaluator_attempts[0].failure.failure_type == FailureType.TIMEOUT
    assert task.evaluator_attempts[0].failure.source == "evaluator"
    assert task.evaluator_attempts[1].validations[0].status == "passed"
    assert task.evaluator_attempts[1].validations[0].cost_usd == 0
    assert [action.action for action in task.recovery_actions] == [
        "retry_evaluator",
        "stop_success",
    ]
    assert execution.sleep_calls == (100,)
    assert task.production_generation_cost_usd > 0
    assert task.production_validation_cost_usd > 0
    assert task.known_cost_usd == (
        task.production_generation_cost_usd + task.production_validation_cost_usd
    )
    assert task.output == "synthetic-success"


def test_adapter_never_reads_expected_envelope():
    case = evaluator_case()

    class PoisonExpected:
        def __getattr__(self, name):
            if name == "expected":
                raise AssertionError("adapter read the independent expected envelope")
            return getattr(case, name)

    observation, execution = observe(PoisonExpected(), load_bundle(ROOT / "config"))
    assert observation.case_id == case.id
    assert len(execution.evaluator_requests) == 2


def test_runner_covers_remaining_case_and_combined_corpus():
    report, observations = run()
    assert report["total_corpus"] == 179
    assert report["applicable"] == report["passed"] == 1
    assert report["failed"] == 0
    assert report["previously_covered"] == 178
    assert report["evaluator_gate"] == {
        "case_id": "evaluator_infrastructure",
        "executed": True,
        "generation_dispatches": 1,
        "evaluator_dispatches": 2,
        "evaluator_attempts": 2,
        "task_status": "succeeded",
    }
    assert len(observations) == 1

    combined, combined_observations = run(combined=True)
    assert combined["applicable"] == combined["passed"] == 179
    assert combined["failed"] == 0
    assert combined["previously_covered"] == 0
    assert len(combined_observations) == 179


def test_separate_declarative_operational_regressions_cover_all_22_cases():
    cases = load_regressions()
    assert [case["id"] for case in cases] == [
        "v1_pass",
        "v1_quality_fail",
        "v1_timeout",
        "v2_independent_pass",
        "v2_failure",
        "required_evaluator_unavailable",
        "v3_mock_pass",
        "v3_missing",
        "high_consequence_simple_no_tier_jump",
        "stale_health",
        "circuit_opens_infra",
        "quality_no_circuit",
        "half_open_recovery",
        "degraded_usable",
        "unhealthy_excluded",
        "all_permitted_unavailable",
        "shadow_selected",
        "shadow_not_selected",
        "shadow_budget_exhausted",
        "shadow_output_hidden",
        "shadow_failure_production_success",
        "side_effects_forbidden",
    ]
    report, results = run_regressions()
    assert report == {"total": 22, "passed": 22, "failed": 0, "failures": {}}
    assert len(results) == 22
    assert all("checks" not in result for result in results)
    assert "private" not in str(results)
