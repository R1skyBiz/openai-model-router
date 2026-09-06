"""Runtime normalization and immutability, independent of routing priors."""

from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from model_router.core.contracts import Classification, Context, EnvironmentSnapshot, FrozenDict, Limits, Request


def classification_data():
    return dict(task_family="analysis", components=dict(reasoning_depth=1, step_dependency=2,
        context_synthesis=3, technical_precision=4, ambiguity=1, tool_orchestration=0,
        reliability_requirement=1), confidence=0.9, provenance="test-v1")


@pytest.mark.parametrize("value", [True, 1.5, "2", -1])
def test_component_requires_nonnegative_integer(value):
    data = classification_data()
    data["components"]["reasoning_depth"] = value
    with pytest.raises(ValidationError):
        Classification(**data)


def test_total_is_recomputed_and_supplied_total_verified():
    data = classification_data()
    assert Classification(**data).components.total == 12
    with pytest.raises(ValidationError):
        Classification(**data, supplied_total=11)


def test_missing_components_and_classifier_route_injection_are_invalid():
    data = classification_data()
    data["components"].pop("ambiguity")
    with pytest.raises(ValidationError):
        Classification(**data)
    with pytest.raises(ValidationError):
        Classification(**classification_data(), selected_model="anything")


@pytest.mark.parametrize("amount", [1.0, 1, True, "NaN", "Infinity", "-1", "invalid"])
def test_money_never_accepts_binary_float_or_invalid_values(amount):
    with pytest.raises(ValidationError):
        Limits(task_cost_ceiling_usd=amount)


def test_money_is_decimal():
    assert Limits(task_cost_ceiling_usd="0.12").task_cost_ceiling_usd == Decimal("0.12")


def test_cache_buckets_cannot_overlap_total():
    with pytest.raises(ValidationError):
        Context(input_tokens=100, expected_output_tokens=1, cached_input_tokens=90, cache_write_tokens=11)


def test_classification_snapshot_is_detached_and_deeply_immutable():
    flags = {"repository_wide": True}
    c = Classification(**classification_data(), flags=flags)
    flags["repository_wide"] = False
    assert c.flags["repository_wide"] is True
    with pytest.raises(TypeError):
        c.flags["repository_wide"] = False
    with pytest.raises(ValidationError):
        c.confidence = 0.5
    assert c.model_dump(mode="json")["flags"] == {"repository_wide": True}


def test_mapping_snapshot_blocks_dict_descriptor_bypass_and_serializes():
    c = Classification(**classification_data(), flags={"repository_wide": True})

    with pytest.raises(TypeError):
        dict.__setitem__(c.flags, "repository_wide", False)
    payload = c.model_dump(mode="json")
    assert json.loads(c.model_dump_json()) == payload
    assert json.loads(json.dumps(payload)) == payload


def test_direct_frozen_mapping_freezes_children_and_cannot_be_reinitialized_or_rebound():
    source = {"nested": {"value": 1}}
    frozen = FrozenDict(source)
    source["nested"]["value"] = 2

    assert frozen["nested"]["value"] == 1
    with pytest.raises(TypeError):
        frozen["nested"]["value"] = 3
    with pytest.raises(TypeError):
        frozen._FrozenDict__data = {}
    with pytest.raises(TypeError, match="reinitialized"):
        frozen.__init__({"replacement": True})


def test_request_requires_explicit_consequence_and_excludes_raw_content():
    data = dict(task_id="task", trace_id="trace", requirements=["text_input"],
                context={"input_tokens": 1, "expected_output_tokens": 1}, input="secret-sentinel")
    with pytest.raises(ValidationError):
        Request(**data)
    request = Request(**data, consequence="low")
    assert "secret-sentinel" not in request.model_dump_json()
    assert "secret-sentinel" not in repr(request)


def test_mock_readiness_is_only_accepted_for_synthetic_environments():
    with pytest.raises(ValidationError):
        EnvironmentSnapshot(snapshot_id="test", clock="2026-09-06T20:00:00Z", pricing_version="quote-v1",
                            validation={"V0": "configured_mock"})


def test_snapshot_clock_requires_timezone():
    with pytest.raises(ValidationError):
        EnvironmentSnapshot(snapshot_id="test", clock="2026-09-06T20:00:00", pricing_version="quote-v1")
