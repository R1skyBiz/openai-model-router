"""Explicit, bounded paid-eval preflight; never production task admission."""

from datetime import date
from decimal import Decimal, localcontext
import os
from pathlib import Path
from typing import Literal

from pydantic import StrictBool
import yaml

from model_router.core.contracts import Count, Duration, Effort, Money, Name, Record
from model_router.core.provider_contracts import ProviderUsage


class LiveEvalError(ValueError):
    """Safe setup diagnostic; never includes environment or provider content."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise LiveEvalError("duplicate live-eval setting")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


class CanarySettings(Record):
    model_alias: Name
    reasoning_effort: Effort
    max_output_tokens: Duration
    timeout_ms: Duration


class LiveEvalSettings(Record):
    schema_version: Literal[1]
    version: Name
    enabled: StrictBool
    account_access_verified: StrictBool
    pricing_verified: StrictBool
    verified_on: date | None
    max_total_cost_usd: Money | None
    max_input_tokens_per_call: Duration
    input_overhead_tokens: Count
    provider_canary: CanarySettings


def load_live_settings(path: str | Path) -> LiveEvalSettings:
    try:
        document = yaml.load(Path(path).read_text(), Loader=_UniqueLoader)
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int:
            raise LiveEvalError("invalid live-eval schema version")
        return LiveEvalSettings.model_validate(document)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        raise LiveEvalError("invalid live-eval settings") from None


def require_live_access(settings: LiveEvalSettings) -> None:
    if os.environ.get("RUN_LIVE_OPENAI_TESTS") != "1":
        raise LiveEvalError("RUN_LIVE_OPENAI_TESTS=1 is required")
    if not settings.enabled:
        raise LiveEvalError("live-eval settings remain disabled")
    if not settings.account_access_verified or not settings.pricing_verified:
        raise LiveEvalError("verify account access and current prices before paid evals")
    if settings.verified_on != date.today():
        raise LiveEvalError("live-eval verification must be current for today's run")
    if settings.max_total_cost_usd is None or settings.max_total_cost_usd <= 0:
        raise LiveEvalError("a positive finite total eval cost cap is required")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise LiveEvalError("OPENAI_API_KEY is required for explicitly paid evals")


def live_cost_bound(settings: LiveEvalSettings, bundle, model_alias: str,
                    max_output_tokens: int, calls: int) -> Decimal:
    """Conservative no-retry allocation for small standard-text eval calls."""
    if type(calls) is not int or calls <= 0:
        raise LiveEvalError("live eval must have a positive finite call count")
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise LiveEvalError("live eval must have a positive output bound")
    model = bundle.catalog["models"].get(model_alias)
    if model is None or not model["availability"]["configured_enabled"]:
        raise LiveEvalError("eval model is not configured and enabled")
    pricing = model["pricing"]
    if pricing["service_tier"] != "standard":
        raise LiveEvalError("live eval supports reviewed standard-text prices only")
    fields = ("input_usd", "cached_input_usd", "output_usd", "cache_write_input_multiplier")
    if any(pricing[field] is None for field in fields):
        raise LiveEvalError("live eval requires complete text and cache prices")
    if settings.max_input_tokens_per_call > pricing["long_context"]["input_tokens_gt"]:
        raise LiveEvalError("live eval input cap must remain below long-context pricing")
    if (max_output_tokens > model["max_output_tokens"] or
            settings.max_input_tokens_per_call + max_output_tokens > model["context_window_tokens"]):
        raise LiveEvalError("live eval bounds exceed configured model limits")
    with localcontext() as context:
        context.prec = 40
        max_input_rate = max(pricing["input_usd"], pricing["cached_input_usd"],
                             pricing["input_usd"] * pricing["cache_write_input_multiplier"])
        bound = calls * (settings.max_input_tokens_per_call * max_input_rate +
                         max_output_tokens * pricing["output_usd"]) / pricing["unit_tokens"]
    if settings.max_total_cost_usd is None or bound > settings.max_total_cost_usd:
        raise LiveEvalError("conservative allocation exceeds total live-eval cost cap")
    return bound


def check_input_bound(settings: LiveEvalSettings, serialized_request: str) -> None:
    # UTF-8 byte count is a conservative text-token allowance, plus configured
    # framing margin. It is not a tokenizer or a production admission guarantee.
    if len(serialized_request.encode("utf-8")) + settings.input_overhead_tokens > settings.max_input_tokens_per_call:
        raise LiveEvalError("serialized eval request exceeds conservative input allowance")


def usage_cost(usage: ProviderUsage, model) -> Decimal | None:
    if usage.uncached_input_tokens is None or usage.output_tokens is None:
        return None
    pricing = model["pricing"]
    if usage.input_tokens > pricing["long_context"]["input_tokens_gt"]:
        return None
    with localcontext() as context:
        context.prec = 40
        return (usage.uncached_input_tokens * pricing["input_usd"] +
                usage.cached_input_tokens * pricing["cached_input_usd"] +
                usage.cache_write_input_tokens * pricing["input_usd"] * pricing["cache_write_input_multiplier"] +
                usage.output_tokens * pricing["output_usd"]) / pricing["unit_tokens"]
