"""One tiny provider call, only with explicit opt-in and reviewed paid settings."""

import json
import os
from pathlib import Path

import pytest

from evals.live_support import check_input_bound, live_cost_bound, load_live_settings, require_live_access, usage_cost
from model_router.core.provider_contracts import ProviderRequest, ProviderResult
from model_router.policy.loader import load_bundle


@pytest.mark.live_openai
def test_single_openai_text_invocation():
    root = Path(__file__).resolve().parents[2]
    settings = load_live_settings(os.environ.get("OPENAI_LIVE_EVAL_CONFIG", str(root / "config/live-eval.yaml")))
    require_live_access(settings)
    bundle = load_bundle(root / "config")
    canary = settings.provider_canary
    bound = live_cost_bound(settings, bundle, canary.model_alias, canary.max_output_tokens, 1)
    model = bundle.catalog["models"][canary.model_alias]
    request = ProviderRequest(task_id="live-provider-canary", trace_id="live-provider-canary",
        invocation_id="live-provider-canary", policy_version=bundle.policy["version"],
        catalog_version=bundle.catalog["catalog_version"], model_alias=canary.model_alias,
        provider_model_id=model["provider_model_id"], reasoning_effort=canary.reasoning_effort,
        input="Reply with OK.", max_output_tokens=canary.max_output_tokens, timeout_ms=canary.timeout_ms)
    check_input_bound(settings, json.dumps({**request.model_dump(mode="json"), "input": request.input}))
    from model_router.execution.openai_provider import OpenAIProvider

    result = OpenAIProvider(bundle).execute(request)
    report = result.model_dump(mode="json")
    cost = usage_cost(result.usage, model)
    report.update(live_settings_version=settings.version, estimated_upper_cost_usd=str(bound),
                  actual_usage_derived_cost_usd=None if cost is None else str(cost),
                  canary="one_text_response_no_retry", provider_execute_calls=1,
                  response_received=result.response_id is not None)
    output = root / "evals/results/live-provider-canary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    assert isinstance(result, ProviderResult), result
    assert result.response_status == "completed"
    assert result.response_id is not None
    assert cost is not None and cost <= bound
