from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from model_router.calibration.budget import CalibrationAllocation
from model_router.calibration.contracts import BudgetPlan, CalibrationCase, ExperimentConfig
from model_router.calibration.live import LiveCalibrationBlocked, LiveCalibrationGuard
from model_router.calibration.planning import plan_budget
from model_router.classification import load_classifier_config
from model_router.policy.loader import load_bundle


def _case():
    return CalibrationCase(
        case_id="budget-case", corpus_version="v1", source_kind="synthetic_control",
        task="Return 1.", context={"input_tokens": 100, "expected_output_tokens": 10},
        grading={"deterministic": ({"kind": "exact", "expected": "1"},)},
        privacy="public",
    )


def test_plan_is_conservative_finite_and_makes_no_calls():
    bundle = load_bundle("config")
    classifier = load_classifier_config("config/classifier.yaml", bundle)
    config = ExperimentConfig(
        version="budget-v1",
        strategies=(
            {"name": "ROUTER", "kind": "router", "recovery_enabled": True},
            {"name": "TERRA", "kind": "fixed", "model": "terra", "effort": "medium"},
            {"name": "SOL", "kind": "fixed", "model": "sol", "effort": "medium"},
        ),
        aggregate_cap_usd="100",
        max_input_tokens=8192,
        max_output_tokens=1024,
        max_generation_attempts=3,
    )

    plan = plan_budget((_case(),), config, bundle, classifier)

    assert plan.maximum_generation_calls == 5
    assert plan.maximum_classifier_calls == 1
    assert plan.maximum_evaluator_calls == 0
    assert plan.estimated_upper_bound_usd is not None
    assert plan.estimated_upper_bound_usd > 0
    assert plan.admissible
    assert plan.blockers == ()


def test_plan_rejects_aggregate_cap_without_rounding_money():
    bundle = load_bundle("config")
    classifier = load_classifier_config("config/classifier.yaml", bundle)
    config = ExperimentConfig(
        version="budget-v1",
        strategies=(
            {"name": "ROUTER", "kind": "router"},
            {"name": "SOL", "kind": "fixed", "model": "sol", "effort": "medium"},
        ),
        aggregate_cap_usd="0.000000000000000001",
        max_input_tokens=8192,
        max_output_tokens=1024,
    )

    plan = plan_budget((_case(),), config, bundle, classifier)

    assert not plan.admissible
    assert plan.estimated_upper_bound_usd > plan.configured_cap_usd
    assert plan.blockers == ("aggregate_cap_exceeded",)


def test_plan_counts_every_evaluator_and_adjudicator_retry():
    bundle = load_bundle("config")
    classifier = load_classifier_config("config/classifier.yaml", bundle)
    binding = {"model": "terra", "effort": "medium", "max_input_tokens": 2048,
               "max_output_tokens": 128, "timeout_ms": 1000, "retries": 2}
    config = ExperimentConfig(
        version="budget-evaluators",
        strategies=(
            {"name": "ROUTER", "kind": "router"},
            {"name": "SOL", "kind": "fixed", "model": "sol", "effort": "medium"},
        ),
        aggregate_cap_usd="100", max_input_tokens=8192, max_output_tokens=1024,
        evaluator=binding,
        adjudicator={**binding, "model": "sol", "retries": 1},
        adjudication_sample_rate="0.01", max_adjudications=2,
    )

    plan = plan_budget((_case(),), config, bundle, classifier)

    # Two candidates * three primary attempts, plus two candidates * two
    # adjudicator attempts: sampling rate is not a deterministic upper bound.
    assert plan.maximum_evaluator_calls == 10


def _live_guard(tmp_path, *, age=timedelta(0), credential="present-but-never-called"):
    from tests.test_phase6_release import _active_release, NOW
    from model_router.release import load_release
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest_path = _active_release(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text())
    evidence_path = Path(manifest["live"]["evidence"]["path"])
    evidence = yaml.safe_load(evidence_path.read_text())
    evidence["verified_at"] = (NOW - age).isoformat()
    evidence["credential_sha256"] = sha256(credential.encode()).hexdigest()
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False))
    manifest["live"]["evidence"]["sha256"] = sha256(evidence_path.read_bytes()).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    release = load_release(manifest_path)
    allocation_root = (tmp_path / "allocations").resolve()
    allocation = CalibrationAllocation(allocation_root, "live-test-allocation", "0.2")
    guard = LiveCalibrationGuard(
        release, allocation=allocation,
        environment={"RUN_LIVE_CALIBRATION": "1", "OPENAI_API_KEY": credential},
        now=NOW,
    )
    config = ExperimentConfig(
        version="live-gate-v1",
        strategies=(
            {"name": "TERRA", "kind": "fixed", "model": "terra", "effort": "medium"},
            {"name": "SOL", "kind": "fixed", "model": "sol", "effort": "medium"},
        ),
        aggregate_cap_usd="0.2", max_input_tokens=1024, max_output_tokens=64,
        max_generation_attempts=1, live_enabled=True,
        release_manifest=str(release.source),
        allocation_id="live-test-allocation", allocation_cap_usd="0.2",
        allocation_directory=str(allocation_root),
    )
    plan = BudgetPlan(cases=1, strategies=2, maximum_generation_calls=2,
                      maximum_classifier_calls=0, maximum_evaluator_calls=0,
                      estimated_upper_bound_usd="0.1", configured_cap_usd="0.2",
                      admissible=True)
    return guard, release, config, plan


def test_live_gate_requires_fresh_credential_bound_evidence(tmp_path):
    guard, release, config, plan = _live_guard(tmp_path / "stale", age=timedelta(minutes=2))
    with pytest.raises(LiveCalibrationBlocked, match="readiness evidence is stale"):
        guard.require_ready(config, plan, release.policy_bundle, release.classifier_config,
                            run_id="run-stale", software_commit="a" * 40)

    guard, release, config, plan = _live_guard(tmp_path / "credential", credential="expected")
    guard.environment = {"RUN_LIVE_CALIBRATION": "1", "OPENAI_API_KEY": "different"}
    with pytest.raises(LiveCalibrationBlocked, match="credential does not match"):
        guard.require_ready(config, plan, release.policy_bundle, release.classifier_config,
                            run_id="run-credential", software_commit="a" * 40)


def test_live_gate_is_single_use_and_unknown_cost_stops(tmp_path):
    guard, release, config, plan = _live_guard(tmp_path)
    guard.require_ready(config, plan, release.policy_bundle, release.classifier_config,
                        run_id="run-unknown", software_commit="a" * 40)
    with pytest.raises(LiveCalibrationBlocked, match="cost is unknown"):
        guard.after_dispatch(None, Decimal("0.1"))
    assert guard.stopped
    guard.finish_run(None)
    assert guard.allocation.remaining() == Decimal("0.1")
    with pytest.raises(ValueError, match="unresolved cost"):
        guard.allocation.reserve("another-run", Decimal("0.01"))
    with pytest.raises(LiveCalibrationBlocked, match="cannot be reused"):
        guard.require_ready(config, plan, release.policy_bundle, release.classifier_config,
                            run_id="run-repeat", software_commit="a" * 40)


def test_live_gate_stops_when_actual_exceeds_reserved_bound(tmp_path):
    guard, release, config, plan = _live_guard(tmp_path)
    guard.require_ready(config, plan, release.policy_bundle, release.classifier_config,
                        run_id="run-excess", software_commit="a" * 40)
    with pytest.raises(LiveCalibrationBlocked, match="exceeded its reservation"):
        guard.after_dispatch(Decimal("0.11"), Decimal("0.1"))
    assert guard.stopped
    with pytest.raises(LiveCalibrationBlocked, match="settlement failed"):
        guard.finish_run(Decimal("0.11"))
    assert guard.allocation.remaining() == Decimal("0.09")


def test_live_gate_rejects_dirty_source_and_release_limit_overrides(tmp_path):
    guard, release, config, plan = _live_guard(tmp_path / "dirty")
    with pytest.raises(LiveCalibrationBlocked, match="clean pinned"):
        guard.require_ready(
            config, plan, release.policy_bundle, release.classifier_config,
            run_id="run-dirty", software_commit="a" * 40 + "-dirty",
        )
    assert guard.allocation.remaining() == Decimal("0.2")

    guard, release, config, plan = _live_guard(tmp_path / "limits")
    excessive = config.model_copy(update={"max_input_tokens": 9000})
    with pytest.raises(LiveCalibrationBlocked, match="release limits"):
        guard.require_ready(
            excessive, plan, release.policy_bundle, release.classifier_config,
            run_id="run-limits", software_commit="a" * 40,
        )
    assert guard.allocation.remaining() == Decimal("0.2")
