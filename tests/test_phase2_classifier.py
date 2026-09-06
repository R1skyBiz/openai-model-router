from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from pydantic import BaseModel, ValidationError
import yaml

from model_router.classification import MockClassifier, OpenAIClassifier, build_output_type, load_classifier_config
from model_router.core.classifier_contracts import ClassificationFailure, ClassificationResult
from model_router.core.contracts import ConfigurationError, EnvironmentSnapshot, FailureType, Request
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.policy.loader import load_bundle
from model_router.router import route


ROOT = Path(__file__).parents[1]


@pytest.fixture
def bundle():
    return load_bundle(ROOT / "config")


@pytest.fixture
def config(bundle):
    return load_classifier_config(ROOT / "config/classifier.yaml", bundle)


def request(text: str = "Analyze this evidence") -> Request:
    return Request(
        task_id="task-1", trace_id="trace-1", input=text,
        requirements=("text_input", "text_output"), consequence="low",
        context={"input_tokens": 20, "expected_output_tokens": 10},
    )


def valid_output(**updates):
    output = {
        "task_family": "analysis",
        "task_subclass": None,
        "components": {
            "reasoning_depth": 5,
            "step_dependency": 4,
            "context_synthesis": 3,
            "technical_precision": 2,
            "ambiguity": 1,
            "tool_orchestration": 0,
            "reliability_requirement": 1,
        },
        "confidence": 0.8,
        "flags": {
            "consequential_multi_system": False,
            "exceptional_end_to_end": False,
            "long_horizon": False,
            "multivariable": False,
            "repository_wide": False,
            "substantive_implementation": False,
        },
    }
    output.update(updates)
    return output


class ScriptedProvider:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def execute(self, provider_request):
        self.requests.append(provider_request)
        return self.outcome(provider_request) if callable(self.outcome) else self.outcome


def result_for(provider_request, structured_output: BaseModel | None):
    return ProviderResult(
        task_id=provider_request.task_id, trace_id=provider_request.trace_id,
        invocation_id=provider_request.invocation_id,
        policy_version=provider_request.policy_version,
        catalog_version=provider_request.catalog_version,
        model_alias=provider_request.model_alias,
        provider_model_id=provider_request.provider_model_id,
        reasoning_effort=provider_request.reasoning_effort,
        purpose="classification", response_id="resp-1", response_status="completed",
        returned_model_id=provider_request.provider_model_id, latency_ms=2.0,
        usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        structured_output=structured_output,
    )


def enabled_config(tmp_path, bundle):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    path = tmp_path / "config/classifier.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["live_enabled"] = True
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_classifier_config(path, bundle)


def test_output_type_is_strict_dynamic_policy_schema(bundle):
    output_type = build_output_type(bundle)
    wire = output_type.model_validate(valid_output())
    assert wire.task_family == "analysis"
    assert set(type(wire.components).model_fields) == set(bundle.policy["complexity"]["components"])
    expected_flags = {
        flag
        for section in ("task_family_floors", "modifiers")
        for rule in bundle.policy[section]
        for flag in rule["match"]["flags_all"]
    }
    assert set(type(wire.flags).model_fields) == expected_flags


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda value: value.update(task_family="invented"), "task_family"),
        (lambda value: value.update(task_subclass="invented"), "task_subclass"),
        (lambda value: value["components"].update(reasoning_depth=26), "components"),
        (lambda value: value["components"].update(reasoning_depth=True), "components"),
        (lambda value: value["flags"].update(repository_wide="yes"), "flags"),
        (lambda value: value["flags"].pop("repository_wide"), "flags"),
        (lambda value: value.update(confidence=1.01), "confidence"),
        (lambda value: value.update(selected_model="astra"), "unknown_field"),
        (lambda value: value.update(total=16), "unknown_field"),
    ],
)
def test_mock_rejects_invalid_output_without_retaining_values(bundle, config, mutate, field):
    output = valid_output()
    mutate(output)
    classified = MockClassifier([output], bundle, config).classify(request("secret task"))
    assert isinstance(classified, ClassificationFailure)
    assert classified.failure_type == FailureType.MALFORMED_OUTPUT
    assert field in classified.diagnostic_fields
    serialized = classified.model_dump_json()
    assert "secret task" not in serialized
    assert "invented" not in serialized
    assert "astra" not in serialized


def test_mock_valid_output_assigns_trusted_provenance_and_recomputes_total(bundle, config):
    result = MockClassifier([valid_output()], bundle, config).classify(request())
    assert isinstance(result, ClassificationResult)
    assert result.classification.components.total == 16
    assert result.classification.supplied_total is None
    assert result.classification.provenance.startswith(config.version)
    for digest in (config.prompt_hash, config.schema_hash, config.configuration_hash, bundle.content_hash):
        assert digest in result.classification.provenance


def test_mock_supports_input_keys_and_reports_unscripted_and_exhausted(bundle, config):
    keyed = MockClassifier({"first": valid_output(task_family="extract")}, bundle, config)
    assert keyed.classify(request("first")).classification.task_family == "extract"
    assert keyed.classify(request("missing")).cause_code == "CLASSIFIER_INPUT_UNSCRIPTED"
    sequential = MockClassifier([valid_output()], bundle, config)
    assert isinstance(sequential.classify(request("one")), ClassificationResult)
    assert sequential.classify(request("two")).cause_code == "CLASSIFIER_SCRIPT_EXHAUSTED"
    assert sequential.call_count == 2


def test_low_confidence_is_preserved_and_phase1_does_not_directly_jump_tiers(bundle, config):
    classified = MockClassifier([valid_output(confidence=0.05)], bundle, config).classify(request())
    assert classified.classification.confidence == 0.05
    decision = route(
        request(), classified.classification,
        EnvironmentSnapshot(
            snapshot_id="offline", synthetic=True, clock="2026-09-06T20:00:00Z",
            pricing_version="offline", validation={"V0": "configured_mock"},
        ),
        bundle,
    )
    assert decision.selected_model_alias == "luna"
    assert "LOW_CLASSIFIER_CONFIDENCE" in decision.rationale_codes


def test_openai_classifier_invokes_provider_once_with_output_type_and_accounting(tmp_path, bundle):
    config = enabled_config(tmp_path, bundle)
    output_type = build_output_type(bundle)
    provider = ScriptedProvider(lambda call: result_for(call, output_type.model_validate(valid_output())))
    classified = OpenAIClassifier(provider, bundle, config).classify(request("private input"))
    assert isinstance(classified, ClassificationResult)
    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert sent.input == "private input"
    assert sent.output_type.model_json_schema() == output_type.model_json_schema()
    assert sent.reasoning_effort.value == "low"
    assert sent.purpose == "classification"
    assert sent.truncation == "disabled"
    assert classified.provider_result.usage.total_tokens == 15
    assert "private input" not in classified.model_dump_json()


def test_separate_classifier_instances_do_not_reuse_invocation_ids(tmp_path, bundle):
    config = enabled_config(tmp_path, bundle)
    output_type = build_output_type(bundle)
    provider = ScriptedProvider(lambda call: result_for(call, output_type.model_validate(valid_output())))
    first = OpenAIClassifier(provider, bundle, config).classify(request())
    second = OpenAIClassifier(provider, bundle, config).classify(request())
    assert first.provider_result.invocation_id != second.provider_result.invocation_id
    assert first.provider_result.task_id == second.provider_result.task_id


def test_openai_classifier_preserves_provider_failure_and_incomplete_accounting(tmp_path, bundle):
    config = enabled_config(tmp_path, bundle)
    def failure(call):
        return ProviderFailure(
            task_id=call.task_id, trace_id=call.trace_id, invocation_id=call.invocation_id,
            policy_version=call.policy_version, catalog_version=call.catalog_version,
            model_alias=call.model_alias, provider_model_id=call.provider_model_id,
            reasoning_effort=call.reasoning_effort, purpose="classification", latency_ms=1.0,
            failure_type="RATE_LIMIT", source="provider", stage="invocation",
            cause_code="RATE_LIMITED", retryable=True, retry_after_ms=100,
        )
    failed = OpenAIClassifier(ScriptedProvider(failure), bundle, config).classify(request())
    assert failed.failure_type == FailureType.RATE_LIMIT
    assert failed.provider_result.retry_after_ms == 100

    def incomplete(call):
        result = result_for(call, None)
        return result.model_copy(update={
            "response_status": "incomplete", "incomplete_reason": "max_output_tokens",
        })
    failed = OpenAIClassifier(ScriptedProvider(incomplete), bundle, config).classify(request())
    assert failed.cause_code == "CLASSIFIER_PROVIDER_INCOMPLETE"
    assert failed.provider_result.usage.total_tokens == 15


def test_live_disabled_returns_without_provider_invocation(bundle, config):
    provider = ScriptedProvider(None)
    failed = OpenAIClassifier(provider, bundle, config).classify(request())
    assert failed.failure_type == FailureType.CAPABILITY_FAILURE
    assert failed.cause_code == "CLASSIFIER_LIVE_DISABLED"
    assert provider.requests == []


def test_config_hash_changes_with_prompt_and_rejects_bad_model_settings(tmp_path, bundle, config):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    prompt = tmp_path / "config/prompts/task-properties-v1.txt"
    prompt.write_text(prompt.read_text() + "\nAdditional factual guidance.\n")
    changed = load_classifier_config(tmp_path / "config/classifier.yaml", bundle)
    assert changed.prompt_hash != config.prompt_hash
    assert changed.configuration_hash != config.configuration_hash

    path = tmp_path / "config/classifier.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["model_alias"] = "astra"
    raw["reasoning_effort"] = "none"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ConfigurationError, match="unsupported"):
        load_classifier_config(path, bundle)


def test_config_and_schema_reject_unknown_fields(bundle, config, tmp_path):
    with pytest.raises(ValidationError):
        build_output_type(bundle).model_validate({**valid_output(), "model": "luna"})
    shutil.copytree(ROOT / "config", tmp_path / "config")
    path = tmp_path / "config/classifier.yaml"
    path.write_text(path.read_text() + "\nmodel_recommendation: luna\n")
    with pytest.raises(ConfigurationError, match="invalid classifier configuration"):
        load_classifier_config(path, bundle)
