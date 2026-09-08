from decimal import Decimal
import time

import pytest

from model_router.calibration.contracts import (
    CalibrationCase,
    CorpusManifest,
    DeterministicRule,
    Disposition,
    ExperimentConfig,
    Grade,
)
from model_router.calibration.corpus import canonical_case_input, case_content_sha256
from model_router.calibration.grading import BlindGrader
from model_router.calibration.output import compile_output_type
from model_router.calibration.runner import CalibrationRunner
from model_router.calibration.storage import CalibrationStore
from model_router.classification import MockClassifier, load_classifier_config
from model_router.core.contracts import FailureType
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.execution.provider import MockProvider, request_evidence
from model_router.policy.loader import load_bundle


def _case(case_id="case-1"):
    return CalibrationCase(
        case_id=case_id,
        corpus_version="corpus-v1",
        source_kind="synthetic_control",
        task="Return ok.",
        instructions="Use lowercase.",
        context_text="Public fixture.",
        context={"input_tokens": 64, "expected_output_tokens": 8},
        output_contract={"format": "text"},
        tool_policy={},
        grading={"deterministic": ({"kind": "exact", "expected": "ok"},)},
        privacy="public",
    )


def _classification(bundle=None):
    flags = {}
    if bundle is not None:
        flags = {
            flag: False
            for section in ("task_family_floors", "modifiers")
            for rule in bundle.policy[section]
            for flag in rule["match"]["flags_all"]
        }
    return {
        "task_family": "transform",
        "task_subclass": None,
        "components": {
            "reasoning_depth": 0,
            "step_dependency": 0,
            "context_synthesis": 0,
            "technical_precision": 0,
            "ambiguity": 0,
            "tool_orchestration": 0,
            "reliability_requirement": 0,
        },
        "confidence": 1.0,
        "flags": flags,
    }


def _config(*, recovery=False):
    return ExperimentConfig(
        version="experiment-v1",
        strategies=(
            {"name": "ROUTER", "kind": "router", "recovery_enabled": recovery},
            {"name": "SOL_BASELINE", "kind": "fixed", "model": "sol", "effort": "medium"},
        ),
        seed=17,
        aggregate_cap_usd="20",
        max_input_tokens=8192,
        max_output_tokens=64,
        max_generation_attempts=3,
    )


class RecordingProvider(MockProvider):
    def __init__(self, failure_first=False):
        super().__init__(())
        self.requests = []
        self.failure_first = failure_first
        self.failed = False

    def execute(self, request):
        self.requests.append(request)
        usage = ProviderUsage(input_tokens=10, cached_input_tokens=0,
                              cache_write_input_tokens=0, output_tokens=2,
                              reasoning_tokens=0, total_tokens=12)
        if self.failure_first and request.model_alias != "sol" and not self.failed:
            self.failed = True
            return ProviderFailure(
                **request_evidence(request), usage=usage,
                failure_type=FailureType.RATE_LIMIT, source="provider",
                stage="invocation", cause_code="rate_limited", retryable=True,
            )
        return ProviderResult(**request_evidence(request), response_status="completed",
                              text="ok", usage=usage)


def _runner(tmp_path, case, config, provider):
    bundle = load_bundle("config")
    classifier_config = load_classifier_config("config/classifier.yaml", bundle)
    classifier = MockClassifier({canonical_case_input(case): _classification(bundle)}, bundle, classifier_config)
    return CalibrationRunner(
        bundle, classifier_config, config, provider=provider,
        classifier=classifier, grader=BlindGrader(config=config),
        store=CalibrationStore(tmp_path / "runs"),
    )


def _manifest(case, corpus_sha256="a" * 64):
    return CorpusManifest(
        corpus_version=case.corpus_version,
        corpus_sha256=corpus_sha256,
        case_count=1,
        privacy=case.privacy,
        case_hashes={case.case_id: case_content_sha256(case)},
    )


def test_runner_uses_identical_canonical_input_and_blind_ids(tmp_path):
    case = _case()
    provider = RecordingProvider()
    runner = _runner(tmp_path, case, _config(), provider)
    manifest = _manifest(case)

    result = runner.run((case,), manifest)

    assert result.status == "completed"
    assert len(result.strategy_runs) == 2
    assert {request.input for request in provider.requests} == {canonical_case_input(case)}
    assert all(item.input_sha256 == result.strategy_runs[0].input_sha256
               for item in result.strategy_runs)
    assert all(item.grade.disposition == "PASS" for item in result.strategy_runs)
    assert all(item.grade.candidate_id.startswith("candidate-") for item in result.strategy_runs)
    assert all(item.strategy.name not in item.grade.candidate_id for item in result.strategy_runs)
    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    fixed = next(item for item in result.strategy_runs if item.strategy.kind == "fixed")
    assert router.classification is not None
    assert fixed.classification is None
    assert fixed.task_family == router.task_family == "transform"
    assert fixed.complexity_band == router.complexity_band
    assert all(call.purpose == "generation" for call in fixed.calls)


def test_router_recovery_retains_failed_attempt_and_cost(tmp_path):
    case = _case()
    provider = RecordingProvider(failure_first=True)
    runner = _runner(tmp_path, case, _config(recovery=True), provider)
    manifest = _manifest(case, "b" * 64)

    result = runner.run((case,), manifest)

    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    generation = [call for call in router.calls if call.purpose == "generation"]
    assert [call.status for call in generation] == ["failed", "completed"]
    assert all(call.cost_usd is not None for call in generation)
    assert router.recovery_actions == ("retry_backoff",)
    assert router.initial_generation_passed is None
    assert router.grade.disposition == "PASS"


def test_retry_backoff_waits_before_second_generation(tmp_path, monkeypatch):
    import importlib

    runner_module = importlib.import_module("model_router.calibration.runner")
    real_choose_recovery = runner_module.choose_recovery
    case = _case().model_copy(update={"deadline_ms": 1000})

    clock = {"now": 100.0}
    sleeps = []
    def advance(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(runner_module.time, "sleep", advance)
    monkeypatch.setattr(
        runner_module, "choose_recovery",
        lambda context, bundle: real_choose_recovery(context, bundle).model_copy(
            update={"backoff_ms": 25}
        ),
    )
    provider = RecordingProvider(failure_first=True)
    result = _runner(
        tmp_path, case, _config(recovery=True), provider
    ).run((case,), _manifest(case))

    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    assert sleeps == [0.025]
    assert router.recovery_actions == ("retry_backoff",)
    assert router.latency_ms >= 25
    assert len([call for call in router.calls if call.purpose == "generation"]) == 2


def test_retry_backoff_rechecks_deadline_before_sleep(tmp_path, monkeypatch):
    import importlib

    runner_module = importlib.import_module("model_router.calibration.runner")
    real_choose_recovery = runner_module.choose_recovery
    clock = {"now": 100.0}
    sleeps = []

    def choose_then_consume_deadline(context, bundle):
        action = real_choose_recovery(context, bundle).model_copy(
            update={"backoff_ms": 25}
        )
        clock["now"] += 0.080
        return action

    monkeypatch.setattr(runner_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(runner_module, "choose_recovery", choose_then_consume_deadline)
    case = _case().model_copy(update={"deadline_ms": 100})
    provider = RecordingProvider(failure_first=True)
    result = _runner(
        tmp_path, case, _config(recovery=True), provider
    ).run((case,), _manifest(case))

    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    assert sleeps == []
    assert router.recovery_actions == ("stop_deadline",)
    assert len([call for call in router.calls if call.purpose == "generation"]) == 1


def test_unsupported_tool_case_is_invalid_before_provider(tmp_path):
    case = _case().model_copy(update={"tool_policy": _case().tool_policy.model_copy(
        update={"available": ("shell",)})})
    provider = RecordingProvider()
    runner = _runner(tmp_path, case, _config(), provider)
    manifest = _manifest(case, "c" * 64)

    result = runner.run((case,), manifest)

    assert provider.requests == []
    assert {item.execution_status for item in result.strategy_runs} == {"invalid"}
    assert {item.grade.disposition for item in result.strategy_runs} == {"INVALID"}


def test_seeded_strategy_order_is_reproducible_and_seeded(tmp_path):
    case = _case()
    manifest = _manifest(case, "d" * 64)
    orders = []
    for seed in (2, 2, 7):
        config = _config().model_copy(update={
            "seed": seed,
            "strategies": (
                *_config().strategies,
                _config().strategies[1].model_copy(update={"name": "SOL_SECOND"}),
            ),
        })
        runner = _runner(tmp_path / str(seed) / str(len(orders)), case, config, RecordingProvider())
        orders.append(runner.run((case,), manifest).manifest.strategy_order[case.case_id])
    assert orders[0] == orders[1]
    assert orders[0] != orders[2]


def test_openai_classifier_cost_is_attached_only_to_router(tmp_path):
    case = _case()
    bundle = load_bundle("config")
    from tests.test_phase2_classifier import enabled_config
    classifier_config = enabled_config(tmp_path, bundle)

    def classified(request):
        return ProviderResult(
            **request_evidence(request), response_status="completed",
            structured_output=request.output_type.model_validate(_classification(bundle)),
            usage=ProviderUsage(input_tokens=12, cached_input_tokens=0,
                                cache_write_input_tokens=0, output_tokens=8,
                                reasoning_tokens=0, total_tokens=20),
        )

    from model_router.calibration.offline import OfflineProviderClassifier
    classifier = OfflineProviderClassifier(
        MockProvider((classified,)), bundle,
        classifier_config,
    )
    runner = CalibrationRunner(
        bundle, classifier_config, _config(), provider=RecordingProvider(),
        classifier=classifier, grader=BlindGrader(config=_config()),
        store=CalibrationStore(tmp_path / "runs"),
    )
    manifest = _manifest(case, "e" * 64)

    result = runner.run((case,), manifest)

    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    fixed = next(item for item in result.strategy_runs if item.strategy.kind == "fixed")
    assert [call.purpose for call in router.calls].count("classification") == 1
    assert next(call for call in router.calls if call.purpose == "classification").cost_usd > 0
    assert all(call.purpose != "classification" for call in fixed.calls)


def test_json_contract_uses_one_output_type_and_v0_rejects_missing_structure(tmp_path):
    schema = {"type": "object", "properties": {"count": {"type": "integer"}},
              "required": ["count"], "additionalProperties": False}
    case = _case().model_copy(update={
        "output_contract": _case().output_contract.model_copy(
            update={"format": "json", "json_schema": schema}),
        "grading": _case().grading.model_copy(update={
            "deterministic": (DeterministicRule(kind="schema", expected=schema),)
        }),
    })

    class StructuredProvider(RecordingProvider):
        def execute(self, request):
            self.requests.append(request)
            usage = ProviderUsage(input_tokens=10, cached_input_tokens=0,
                                  cache_write_input_tokens=0, output_tokens=2,
                                  reasoning_tokens=0, total_tokens=12)
            return ProviderResult(
                **request_evidence(request), response_status="completed",
                structured_output=request.output_type.model_validate({"count": 3}), usage=usage,
            )

    provider = StructuredProvider()
    runner = _runner(tmp_path, case, _config(), provider)
    manifest = _manifest(case, "f" * 64)
    result = runner.run((case,), manifest)

    assert len({id(request.output_type) for request in provider.requests}) == 1
    assert provider.requests[0].output_type.model_json_schema() == schema
    assert all(item.initial_generation_passed is True for item in result.strategy_runs)
    assert all(item.grade.disposition == "PASS" for item in result.strategy_runs)


def test_actual_cost_above_reservation_stops_future_dispatch(tmp_path):
    case = _case()

    class ExcessiveUsage(RecordingProvider):
        def execute(self, request):
            self.requests.append(request)
            usage = ProviderUsage(input_tokens=10_000_000, cached_input_tokens=0,
                                  cache_write_input_tokens=0, output_tokens=10_000_000,
                                  reasoning_tokens=0, total_tokens=20_000_000)
            return ProviderResult(**request_evidence(request), response_status="completed",
                                  text="ok", usage=usage)

    provider = ExcessiveUsage()
    runner = _runner(tmp_path, case, _config(), provider)
    manifest = _manifest(case, "1" * 64)
    result = runner.run((case,), manifest)

    assert result.status == "stopped"
    assert len(provider.requests) == 1
    assert len(result.strategy_runs) == 1
    assert result.strategy_runs[0].calls[0].cost_usd is not None


def test_live_mode_without_explicit_guard_records_stopped_run_and_calls_nothing(tmp_path):
    case = _case()
    provider = RecordingProvider()
    config = _config().model_copy(update={"live_enabled": True, "release_manifest": "release.yaml"})
    runner = _runner(tmp_path, case, config, provider)
    manifest = _manifest(case, "2" * 64)

    result = runner.run((case,), manifest, offline=False)

    assert result.status == "stopped"
    assert result.stop_reason == "live_calibration_blocked"
    assert provider.requests == []


def test_one_strategy_deadline_does_not_stop_later_strategies(tmp_path):
    case = _case().model_copy(update={"deadline_ms": 20})

    class SlowProvider(RecordingProvider):
        def execute(self, request):
            time.sleep(0.03)
            return super().execute(request)

    provider = SlowProvider()
    runner = _runner(tmp_path, case, _config(), provider)
    manifest = _manifest(case, "3" * 64)
    result = runner.run((case,), manifest)

    assert result.status == "completed"
    assert len(provider.requests) == 2
    assert len(result.strategy_runs) == 2
    assert {item.execution_status for item in result.strategy_runs} == {"failed"}


@pytest.mark.parametrize("as_failure", [False, True])
def test_in_progress_result_is_unknown_and_never_recovered(tmp_path, as_failure):
    case = _case()

    class InProgressProvider(RecordingProvider):
        def execute(self, request):
            self.requests.append(request)
            values = dict(
                request_evidence(request), response_status="in_progress",
                usage=ProviderUsage(input_tokens=10, cached_input_tokens=0,
                                    cache_write_input_tokens=0, output_tokens=0,
                                    reasoning_tokens=0, total_tokens=10),
            )
            if as_failure:
                return ProviderFailure(
                    **values, failure_type=FailureType.RATE_LIMIT,
                    source="provider", stage="invocation",
                    cause_code="queued", retryable=True,
                )
            return ProviderResult(**values)

    provider = InProgressProvider()
    result = _runner(
        tmp_path, case, _config(recovery=True), provider
    ).run((case,), _manifest(case))

    router = next(item for item in result.strategy_runs if item.strategy.kind == "router")
    assert router.execution_status == "unknown"
    assert router.grade.disposition == "UNKNOWN"
    assert router.recovery_actions == ()
    assert len([call for call in router.calls if call.purpose == "generation"]) == 1
    assert next(call for call in router.calls if call.purpose == "generation").cost_usd is None


def test_manifest_hash_and_privacy_are_checked_before_provider(tmp_path):
    case = _case()
    provider = RecordingProvider()
    runner = _runner(tmp_path / "hash", case, _config(), provider)
    bad = _manifest(case).model_copy(update={"case_hashes": {case.case_id: "f" * 64}})
    with pytest.raises(ValueError, match="manifest"):
        runner.run((case,), bad)
    assert provider.requests == []

    private = case.model_copy(update={"privacy": "internal"})
    runner = _runner(tmp_path / "privacy", private, _config(), provider)
    with pytest.raises(ValueError, match="privacy"):
        runner.run((private,), _manifest(private))
    assert provider.requests == []


def test_opted_in_review_output_is_stored_by_opaque_candidate_id(tmp_path):
    case = _case()
    config = _config().model_copy(update={"capture_review_outputs": True})

    class ReviewGrader:
        evaluator = None
        adjudicator = None

        def grade(self, candidate, *, adjudicate=False):
            return Grade(
                candidate_id=candidate.candidate_id,
                disposition=Disposition.NEEDS_REVIEW,
                human_review_needed=True,
            )

    runner = _runner(tmp_path, case, config, RecordingProvider())
    runner.grader = ReviewGrader()
    result = runner.run((case,), _manifest(case))

    assert all(item.grade.output_reference for item in result.strategy_runs)
    for item in result.strategy_runs:
        assert runner.store.load_review_output(
            result.manifest.run_id, item.grade.candidate_id
        ) == "ok"
