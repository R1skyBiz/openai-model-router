"""Deterministic Decimal cost quotes for a single feasible route."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, ROUND_CEILING, localcontext
from hashlib import sha256
import json
from typing import Any

from model_router.core.contracts import (
    CostEstimate,
    EnvironmentSnapshot,
    Request,
    ValidationRequirements,
)


ZERO = Decimal("0")


def estimate_cost(
    request: Request,
    model: Mapping[str, Any],
    environment: EnvironmentSnapshot,
    validation: ValidationRequirements,
    *,
    currency: str,
) -> CostEstimate:
    """Quote generation plus required validation and tool charges.

    The request context buckets are disjoint.  Claimed cache reads are billed
    as ordinary input unless the request carries cache evidence.  An unknown
    required component produces a null total and retains the known subtotal.
    """

    pricing = model.get("pricing", {})
    arithmetic = Context(prec=_required_precision(request, pricing, environment),
                         rounding=ROUND_CEILING, Emin=MIN_EMIN, Emax=MAX_EMAX)
    with localcontext(arithmetic):
        return _estimate_cost(request, model, environment, validation, currency)


def _estimate_cost(
    request: Request,
    model: Mapping[str, Any],
    environment: EnvironmentSnapshot,
    validation: ValidationRequirements,
    currency: str,
) -> CostEstimate:
    pricing = model.get("pricing", {})
    unit_tokens = pricing.get("unit_tokens")
    unit = Decimal(unit_tokens) if isinstance(unit_tokens, int) and unit_tokens > 0 else None

    context = request.context
    cache_read_tokens = context.cached_input_tokens if context.cache_evidence else 0
    cache_write_tokens = context.cache_write_tokens
    uncached_input_tokens = context.input_tokens - cache_read_tokens - cache_write_tokens

    long_config = pricing.get("long_context") or {}
    threshold = long_config.get("input_tokens_gt")
    long_context = isinstance(threshold, int) and context.input_tokens > threshold

    breakdown: dict[str, Decimal | None] = {}
    unknown: list[str] = []

    input_multiplier = _money(long_config.get("input_multiplier")) if long_context else Decimal("1")
    output_multiplier = _money(long_config.get("output_multiplier")) if long_context else Decimal("1")

    breakdown["uncached_input"] = _token_charge(
        uncached_input_tokens,
        _money(pricing.get("input_usd")),
        unit,
        input_multiplier,
    )
    _record_unknown(breakdown, unknown, "uncached_input")

    cache_read_multiplier = (
        _money(long_config.get("cached_input_multiplier")) if long_context else Decimal("1")
    )
    breakdown["cache_read_input"] = _token_charge(
        cache_read_tokens,
        _money(pricing.get("cached_input_usd")),
        unit,
        cache_read_multiplier,
    )
    if breakdown["cache_read_input"] is None and cache_read_tokens:
        unknown.append("long_context_cache_read" if long_context else "cache_read_input")

    cache_write_rate = _multiply(
        _money(pricing.get("input_usd")),
        _money(pricing.get("cache_write_input_multiplier")),
    )
    cache_write_multiplier = (
        _money(long_config.get("cache_write_multiplier")) if long_context else Decimal("1")
    )
    breakdown["cache_write_input"] = _token_charge(
        cache_write_tokens,
        cache_write_rate,
        unit,
        cache_write_multiplier,
    )
    if breakdown["cache_write_input"] is None and cache_write_tokens:
        unknown.append("long_context_cache_write" if long_context else "cache_write_input")

    breakdown["output"] = _token_charge(
        context.expected_output_tokens,
        _money(pricing.get("output_usd")),
        unit,
        output_multiplier,
    )
    _record_unknown(breakdown, unknown, "output")

    generation_subtotal = sum(
        (amount for amount in breakdown.values() if amount is not None),
        ZERO,
    )

    if validation.evaluator_required:
        evaluator_charge = environment.required_evaluator_cost_usd
        breakdown["required_evaluator"] = evaluator_charge
        if evaluator_charge is None:
            unknown.append("required_evaluator")

    if "V3" in validation.profiles:
        if "domain_validator_unconfigured" in validation.blockers:
            breakdown["required_domain_validator"] = None
            unknown.append("required_domain_validator")
        else:
            domain_charge = environment.required_domain_validator_cost_usd
            breakdown["required_domain_validator"] = domain_charge
            if domain_charge is None:
                unknown.append("required_domain_validator")

    if environment.required_tool_charge or request.side_effecting_tool:
        tool_charge = environment.required_tool_charge_usd
        breakdown["required_tool"] = tool_charge
        if tool_charge is None:
            unknown.append("required_tool")

    known_subtotal = sum(
        (amount for amount in breakdown.values() if amount is not None),
        ZERO,
    )
    if unknown:
        status = "partial" if known_subtotal > ZERO else "unavailable"
        amount = None
    else:
        status = "known"
        amount = known_subtotal

    # The supplied environment label is provenance, not a tariff source. Bind
    # the quote identifier to the actual catalog rates and required extra fees.
    quote = {"provider_model_id": model["provider_model_id"], "pricing": pricing, "currency": currency,
             "required_charges": {name: value for name, value in breakdown.items() if name.startswith("required_")}}
    pricing_version = "quote-sha256:" + sha256(json.dumps(
        quote, sort_keys=True, separators=(",", ":"),
        default=lambda item: dict(item) if isinstance(item, Mapping) else str(item)).encode()).hexdigest()

    return CostEstimate(
        status=status,
        amount=amount,
        currency=currency,
        pricing_version=pricing_version,
        model_pricing_version=pricing["version"],
        token_assumptions=request.context,
        known_subtotal=known_subtotal,
        generation_subtotal=generation_subtotal,
        breakdown=breakdown,
        unknown_charges=tuple(unknown),
        cache_read_tokens=cache_read_tokens,
        long_context=long_context,
    )


def _money(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) and value.is_finite() and value >= ZERO else None


def _required_precision(
    request: Request, pricing: Mapping[str, Any], environment: EnvironmentSnapshot
) -> int:
    """Choose enough precision for exact configured fixed-point arithmetic.

    The generous guard digits cover products, division by the configured token
    unit, and addition without inheriting a caller-modified Decimal context.
    """

    token_digits = max(
        len(str(request.context.input_tokens)),
        len(str(request.context.expected_output_tokens)),
        1,
    )
    decimal_digits = 1
    exponent_span = 0

    def visit(value: object) -> None:
        nonlocal decimal_digits, exponent_span
        if isinstance(value, Decimal):
            decimal_digits = max(decimal_digits, len(value.as_tuple().digits))
            exponent_span = max(exponent_span, abs(value.as_tuple().exponent))
        elif isinstance(value, Mapping):
            for child in value.values():
                visit(child)

    visit(pricing)
    visit(environment.required_evaluator_cost_usd)
    visit(environment.required_domain_validator_cost_usd)
    visit(environment.required_tool_charge_usd)
    return max(64, token_digits + (decimal_digits + exponent_span) * 3 + 32)


def _multiply(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left * right


def _token_charge(
    tokens: int,
    rate: Decimal | None,
    unit: Decimal | None,
    multiplier: Decimal | None,
) -> Decimal | None:
    if tokens == 0:
        return ZERO
    if rate is None or unit is None or multiplier is None:
        return None
    return Decimal(tokens) * rate * multiplier / unit


def _record_unknown(
    breakdown: Mapping[str, Decimal | None], unknown: list[str], name: str
) -> None:
    if breakdown[name] is None:
        unknown.append(name)
