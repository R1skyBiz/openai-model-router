"""Paid-eval setup stays explicitly disabled during ordinary verification."""

from decimal import Decimal
from pathlib import Path

import pytest

from evals.live_support import LiveEvalError, check_input_bound, live_cost_bound, load_live_settings, require_live_access, usage_cost
from model_router.core.provider_contracts import ProviderUsage
from model_router.policy.loader import load_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_paid_eval_is_disabled_and_has_no_implicit_spending_cap():
    settings = load_live_settings(ROOT / "config/live-eval.yaml")
    assert not settings.enabled
    assert settings.max_total_cost_usd is None
    with pytest.raises(LiveEvalError, match="RUN_LIVE_OPENAI_TESTS"):
        require_live_access(settings)


def test_env_opt_in_alone_does_not_enable_paid_evaluation(monkeypatch):
    settings = load_live_settings(ROOT / "config/live-eval.yaml")
    monkeypatch.setenv("RUN_LIVE_OPENAI_TESTS", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    with pytest.raises(LiveEvalError, match="disabled"):
        require_live_access(settings)


def test_live_budget_accounts_for_cache_write_rate_and_output_once():
    bundle = load_bundle(ROOT / "config")
    settings = load_live_settings(ROOT / "config/live-eval.yaml").model_copy(
        update={"max_total_cost_usd": Decimal("1")})
    model = bundle.catalog["models"][settings.provider_canary.model_alias]
    price = model["pricing"]
    bound = live_cost_bound(settings, bundle, settings.provider_canary.model_alias, 100, 19)
    assert bound == 19 * (8192 * price["input_usd"] * price["cache_write_input_multiplier"] +
                          100 * price["output_usd"]) / price["unit_tokens"]
    usage = ProviderUsage(input_tokens=100, cached_input_tokens=10, cache_write_input_tokens=20,
                          output_tokens=30, reasoning_tokens=25, total_tokens=130)
    assert usage_cost(usage, model) == (70 * price["input_usd"] + 10 * price["cached_input_usd"] +
        20 * price["input_usd"] * price["cache_write_input_multiplier"] + 30 * price["output_usd"]) / price["unit_tokens"]
    assert usage_cost(ProviderUsage(input_tokens=100), model) is None
    with pytest.raises(LiveEvalError, match="exceeds total"):
        live_cost_bound(settings.model_copy(update={"max_total_cost_usd": Decimal("0.000001")}),
                        bundle, settings.provider_canary.model_alias, 100, 19)


def test_request_size_is_bounded_before_paid_dispatch():
    settings = load_live_settings(ROOT / "config/live-eval.yaml")
    with pytest.raises(LiveEvalError, match="input allowance"):
        check_input_bound(settings, "x" * settings.max_input_tokens_per_call)
