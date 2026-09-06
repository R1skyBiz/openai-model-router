from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, getcontext
from types import SimpleNamespace

import pytest

from model_router.core.contracts import (
    Context,
    EnvironmentSnapshot,
    Limits,
    Request,
    ValidationLevel,
    ValidationRequirements,
)
from model_router.policy.budgets import check_budget, resolve_limits
from model_router.policy.capabilities import check_capabilities
from model_router.policy.costs import estimate_cost


def request(**changes) -> Request:
    values = {
        "task_id": "task",
        "trace_id": "trace",
        "requirements": ("text_input", "text_output"),
        "consequence": "low",
        "context": Context(input_tokens=1_000, expected_output_tokens=1_000),
    }
    values.update(changes)
    return Request(**values)


def environment(**changes) -> EnvironmentSnapshot:
    values = {
        "snapshot_id": "offline-v1",
        "synthetic": True,
        "clock": datetime(2026, 9, 6, 20, tzinfo=UTC),
        "pricing_version": "approved-standard-text-2026-09-06",
        "budget": Limits(
            task_cost_ceiling_usd=Decimal("10.00"),
            task_deadline_ms=30_000,
            live_execution_enabled=True,
        ),
        "remaining_usd": Decimal("10.00"),
    }
    values.update(changes)
    return EnvironmentSnapshot(**values)


def validation(**changes) -> ValidationRequirements:
    values = {
        "level": ValidationLevel.V0,
        "profiles": (ValidationLevel.V0,),
        "checks": (),
        "evidence": "task_checks",
    }
    values.update(changes)
    return ValidationRequirements(**values)


def luna_model() -> dict:
    return {
        "provider_model_id": "fixture-text-model",
        "tier": "L0",
        "tier_rank": 0,
        "capabilities": {
            "text_input": True,
            "text_output": True,
            "audio_input": False,
            "unverified": None,
        },
        "context_window_tokens": 1_050_000,
        "max_output_tokens": 128_000,
        "pricing": {
            "version": "luna-standard-2026-09-06",
            "unit_tokens": 1_000_000,
            "input_usd": Decimal("0.20"),
            "cached_input_usd": Decimal("0.02"),
            "output_usd": Decimal("1.20"),
            "cache_write_input_multiplier": Decimal("1.25"),
            "long_context": {
                "input_tokens_gt": 272_000,
                "input_multiplier": Decimal("2"),
                "output_multiplier": Decimal("1.5"),
                "cached_input_multiplier": None,
                "cache_write_multiplier": None,
            },
        },
    }


def bundle(*, applications=None):
    return SimpleNamespace(
        catalog={
            "currency": "USD",
            "models": {
                "luna": {"tier": "L0", "tier_rank": 0},
                "terra": {"tier": "L1", "tier_rank": 1},
                "sol": {"tier": "L2", "tier_rank": 2},
                "astra": {"tier": "L3", "tier_rank": 3},
            },
        },
        budgets={
            "defaults": {
                "model_tier_floor": "L0",
                "model_tier_ceiling": "L3",
                "task_cost_ceiling_usd": None,
                "task_deadline_ms": None,
                "period_spend_ceiling_usd": None,
                "period": None,
                "live_execution_enabled": False,
            },
            "applications": applications or {},
        },
    )


def quote(req=None, env=None, requirements=None):
    return estimate_cost(
        req or request(),
        luna_model(),
        env or environment(),
        requirements or validation(),
        currency="USD",
    )


def test_capabilities_treat_false_missing_and_unverified_as_unsupported():
    result = check_capabilities(
        request(requirements=("audio_input", "unknown", "unverified")), luna_model()
    )

    assert result.violations == ("audio_input", "unknown", "unverified")
    assert result.rationale_codes == ("CAPABILITY_FILTER",)


@pytest.mark.parametrize(
    ("context", "violations"),
    [
        (Context(input_tokens=1, expected_output_tokens=128_001), ("output_allowance",)),
        (
            Context(input_tokens=1_000_000, expected_output_tokens=60_000),
            ("combined_context",),
        ),
    ],
)
def test_capabilities_enforce_output_and_combined_context(context, violations):
    result = check_capabilities(request(context=context), luna_model())

    assert result.violations == violations
    assert result.rationale_codes == ("CONTEXT_CONSTRAINT",)


@pytest.mark.parametrize(
    ("input_tokens", "amount", "long_context"),
    [
        (271_999, Decimal("0.0555998"), False),
        (272_000, Decimal("0.0556"), False),
        (272_001, Decimal("0.1106004"), True),
    ],
)
def test_long_context_is_strict_and_applies_to_full_request(
    input_tokens, amount, long_context
):
    result = quote(request(context=Context(input_tokens=input_tokens, expected_output_tokens=1_000)))

    assert result.amount == amount
    assert result.long_context is long_context


def test_cache_reads_require_evidence_and_write_bucket_is_disjoint():
    evidenced = quote(
        request(
            context=Context(
                input_tokens=100_000,
                expected_output_tokens=1_000,
                cached_input_tokens=90_000,
                cache_write_tokens=5_000,
                cache_evidence=True,
            )
        )
    )
    unevidenced = quote(
        request(
            context=Context(
                input_tokens=100_000,
                expected_output_tokens=1_000,
                cached_input_tokens=90_000,
                cache_write_tokens=5_000,
            )
        )
    )

    assert evidenced.cache_read_tokens == 90_000
    assert evidenced.breakdown == {
        "uncached_input": Decimal("0.001"),
        "cache_read_input": Decimal("0.0018"),
        "cache_write_input": Decimal("0.00125"),
        "output": Decimal("0.0012"),
    }
    assert unevidenced.cache_read_tokens == 0
    assert unevidenced.breakdown["uncached_input"] == Decimal("0.019")
    assert unevidenced.breakdown["cache_write_input"] == Decimal("0.00125")


def test_unknown_long_context_cache_write_produces_partial_null_total():
    result = quote(
        request(
            context=Context(
                input_tokens=300_000,
                expected_output_tokens=1_000,
                cache_write_tokens=10_000,
            )
        )
    )

    assert result.status == "partial"
    assert result.amount is None
    assert result.unknown_charges == ("long_context_cache_write",)
    assert result.breakdown["cache_write_input"] is None


def test_required_evaluator_tool_and_domain_charges_are_not_assumed_free():
    env = environment(required_tool_charge=True, required_tool_charge_usd=None)
    requirements = validation(
        level=ValidationLevel.V3,
        profiles=(ValidationLevel.V0, ValidationLevel.V3),
        evaluator_required=True,
        blockers=("domain_validator_unconfigured",),
    )
    result = quote(env=env, requirements=requirements)

    assert result.status == "partial"
    assert result.amount is None
    assert set(result.unknown_charges) == {
        "required_evaluator",
        "required_domain_validator",
        "required_tool",
    }


def test_decimal_quote_is_isolated_from_ambient_context():
    original_precision = getcontext().prec
    try:
        getcontext().prec = 4
        result = quote(
            request(context=Context(input_tokens=272_001, expected_output_tokens=1_000))
        )
    finally:
        getcontext().prec = original_precision

    assert result.amount == Decimal("0.1106004")


def test_synthetic_environment_supplies_fixture_defaults_and_caller_tightens():
    req = request(
        constraints=Limits(
            model_tier_ceiling=3,
            task_cost_ceiling_usd=Decimal("10.00"),
            task_deadline_ms=30_000,
            live_execution_enabled=True,
        )
    )
    env = environment(
        application_overlay=Limits(
            model_tier_ceiling=1,
            task_cost_ceiling_usd=Decimal("0.02"),
            task_deadline_ms=1_000,
            live_execution_enabled=False,
        ),
        application_overlay_version="trusted-overlay-v1",
    )

    result = resolve_limits(req, env, bundle())

    assert result == Limits(
        model_tier_floor=0,
        model_tier_ceiling=1,
        task_cost_ceiling_usd=Decimal("0.02"),
        task_deadline_ms=1_000,
        live_execution_enabled=False,
    )


def test_only_trusted_environment_identity_selects_configured_application():
    applications = {
        "trusted": {"model_tier_floor": "L2", "model_tier_ceiling": "L2"},
        "caller_claim": {"model_tier_ceiling": "L0"},
    }
    req = request(application_id="caller_claim")
    env = environment(trusted_application_id="trusted")

    result = resolve_limits(req, env, bundle(applications=applications))

    assert result.model_tier_floor == 2
    assert result.model_tier_ceiling == 2


def test_non_synthetic_environment_cannot_enable_config_disabled_execution():
    env = environment(
        synthetic=False,
        budget=Limits(
            task_cost_ceiling_usd=Decimal("10"),
            task_deadline_ms=30_000,
            live_execution_enabled=True,
        ),
    )

    result = resolve_limits(request(), env, bundle())

    assert result.live_execution_enabled is False


def test_budget_preserves_evaluator_shortfall_as_preview_blocker():
    result = check_budget(
        quote(
            env=environment(required_evaluator_cost_usd=Decimal("0.05")),
            requirements=validation(evaluator_required=True),
        ),
        Limits(
            task_cost_ceiling_usd=Decimal("10"),
            task_deadline_ms=30_000,
            live_execution_enabled=True,
        ),
        environment(
            remaining_usd=Decimal("0.02"),
            required_evaluator_cost_usd=Decimal("0.05"),
        ),
    )

    assert result.violations == ()
    assert "required_evaluator_budget" in result.blockers


def test_zero_remaining_rejects_generation_and_deadline_blocks_only_when_exceeded():
    cost = quote()
    limits = Limits(
        task_cost_ceiling_usd=Decimal("10"),
        task_deadline_ms=20,
        live_execution_enabled=True,
    )
    equal = check_budget(cost, limits, environment(remaining_usd=Decimal("0"), minimum_next_action_ms=20))
    exceeded = check_budget(cost, limits, environment(minimum_next_action_ms=21))

    assert "remaining_budget" in equal.violations
    assert "deadline" not in equal.blockers
    assert "deadline" in exceeded.blockers


def test_partial_cost_blocks_and_known_subtotal_still_enforces_ceiling():
    cost = quote(env=environment(required_tool_charge=True))
    result = check_budget(
        cost,
        Limits(
            task_cost_ceiling_usd=Decimal("0.001"),
            task_deadline_ms=30_000,
            live_execution_enabled=True,
        ),
        environment(required_tool_charge=True),
    )

    assert "required_tool" in result.blockers
    assert "task_cost_ceiling_usd" in result.violations
    assert result.rationale_codes == ("ESTIMATE_UNAVAILABLE",)


def test_missing_finite_cost_and_deadline_limits_block_execution():
    result = check_budget(
        quote(), Limits(live_execution_enabled=True), environment()
    )

    assert "finite_task_cost_ceiling_required" in result.blockers
    assert "task_deadline_required" in result.blockers
