"""Fail-closed offline preflight and explicit release activation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import TypeAdapter, ValidationError

from model_router.core.contracts import thaw

from .loader import LoadedRelease
from .schema import (
    ActivationReport,
    AuthApplicationSource,
    PreflightCheck,
    PreflightReport,
    RuntimeEvidence,
)


class ActivationBlocked(RuntimeError):
    """Activation was refused; ``report`` contains only sanitized blockers."""

    def __init__(self, report: PreflightReport):
        super().__init__("release activation blocked: " + ", ".join(report.blockers))
        self.report = report


class CredentialConfigurationError(ValueError):
    """External credential sources are absent or invalid; details stay secret."""


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CredentialConfigurationError("invalid application credential configuration")
        result[key] = value
    return result


def parse_application_credentials(
    release: LoadedRelease, environment: Mapping[str, str] | None = None
) -> tuple[Mapping[str, Any], ...]:
    """Resolve external bearer sources into safe application/digest/scope records.

    The manifest names one environment variable containing a JSON mapping of
    application IDs to ``token_env`` and ``scopes``.  Actual bearer values live
    in those second-level environment variables and are never returned.
    """

    env = os.environ if environment is None else environment
    encoded = env.get(release.config.auth.credentials_env)
    if not isinstance(encoded, str) or not encoded.strip():
        raise CredentialConfigurationError("application credential source is missing")
    try:
        raw = json.loads(encoded, object_pairs_hook=_unique_json_object)
        parsed = TypeAdapter(dict[str, AuthApplicationSource]).validate_python(raw)
    except (CredentialConfigurationError, ValidationError, TypeError, ValueError, json.JSONDecodeError):
        raise CredentialConfigurationError("invalid application credential configuration") from None
    if not parsed:
        raise CredentialConfigurationError("invalid application credential configuration")

    from model_router.service.auth import credential_digest

    records: list[Mapping[str, Any]] = []
    digests: set[str] = set()
    covered: set[str] = set()
    permitted = set(release.config.auth.required_scopes)
    for application_id, source in parsed.items():
        if not application_id.strip() or application_id != application_id.strip():
            raise CredentialConfigurationError("invalid application credential configuration")
        if not set(source.scopes).issubset(permitted):
            raise CredentialConfigurationError("invalid application credential configuration")
        token = env.get(source.token_env)
        if (
            not isinstance(token, str)
            or len(token.encode("utf-8")) < release.config.auth.minimum_token_bytes
            or any(ord(character) < 33 or ord(character) > 126 for character in token)
        ):
            raise CredentialConfigurationError("application credential token is missing or too short")
        digest = credential_digest(token)
        if digest in digests:
            raise CredentialConfigurationError("application credential digests must be unique")
        digests.add(digest)
        covered.update(source.scopes)
        records.append(
            MappingProxyType(
                {
                    "application_id": application_id,
                    "credential_digest": digest,
                    "scopes": tuple(source.scopes),
                }
            )
        )
    if not permitted.issubset(covered):
        raise CredentialConfigurationError("configured credentials do not cover enabled scopes")
    return tuple(records)


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.utcoffset() is None:
        raise ValueError("preflight time must include a timezone")
    return current.astimezone(UTC)


def _enabled_operations(release: LoadedRelease) -> tuple[str, ...]:
    operations = release.config.operations
    return tuple(
        name
        for name in (
            "route",
            "classify_route",
            "read",
            "execute",
            "health",
            "live_provider",
            "live_classifier",
            "tools",
            "shadow",
        )
        if getattr(operations, name)
    )


def _check(checks: list[PreflightCheck], name: str, passed: bool, detail: str) -> None:
    checks.append(PreflightCheck(name=name, passed=passed, detail=detail))


def _present(environment: Mapping[str, str], name: str) -> bool:
    value = environment.get(name)
    return isinstance(value, str) and bool(value.strip())


def _policy_is_active(release: LoadedRelease) -> bool:
    bundle = release.policy_bundle
    return all(
        document["status"] == "active"
        for document in (bundle.policy, bundle.catalog, bundle.budgets, bundle.validation)
    )


def _recovery_is_finite(release: LoadedRelease) -> bool:
    escalation = release.policy_bundle.policy["escalation"]
    limits = escalation["limits"]
    backoff = escalation["infrastructure"]["backoff"]
    values = (
        limits["max_total_generation_attempts"],
        limits["max_quality_escalations"],
        limits["max_infrastructure_retries"],
        limits["max_tool_recoveries"],
        limits["max_elapsed_ms"],
        backoff["initial_ms"],
        backoff["max_ms"],
        backoff["jitter"],
    )
    return all(value is not None for value in values)


def _policy_limits_match_runtime(
    release: LoadedRelease, credentials: tuple[Mapping[str, Any], ...]
) -> bool:
    config = release.config
    policy = release.policy_bundle.policy["escalation"]
    limits = policy["limits"]
    backoff = policy["infrastructure"]["backoff"]
    budget = release.policy_bundle.budgets["defaults"]
    base_matches = (
        limits["max_total_generation_attempts"]
        == config.limits.actions.max_total_generation_attempts
        and limits["max_quality_escalations"]
        == config.limits.actions.max_quality_escalations
        and limits["max_infrastructure_retries"]
        == config.limits.actions.max_infrastructure_retries
        and limits["max_tool_recoveries"]
        == config.limits.actions.max_tool_recoveries
        and limits["max_elapsed_ms"] == config.limits.task_deadline_ms
        and backoff["initial_ms"] == config.limits.backoff.initial_ms
        and backoff["max_ms"] == config.limits.backoff.maximum_ms
        and backoff["jitter"] == 0.0
        and backoff["honor_retry_after"] is config.limits.backoff.honor_retry_after
        and _money_equal(
            config.limits.task_cost_ceiling_usd,
            budget["task_cost_ceiling_usd"],
        )
        and _money_equal(
            config.limits.application_cost_ceiling_usd,
            budget["period_spend_ceiling_usd"],
        )
    )
    applications = release.policy_bundle.budgets["applications"]
    for credential in credentials:
        overlay = applications.get(credential["application_id"], {})
        task_ceiling = overlay.get("task_cost_ceiling_usd")
        task_ceiling = budget["task_cost_ceiling_usd"] if task_ceiling is None else task_ceiling
        deadline = overlay.get("task_deadline_ms")
        deadline = budget["task_deadline_ms"] if deadline is None else deadline
        period_ceiling = overlay.get("period_spend_ceiling_usd")
        period_ceiling = budget["period_spend_ceiling_usd"] if period_ceiling is None else period_ceiling
        overlay_live = overlay.get("live_execution_enabled")
        live_enabled = budget["live_execution_enabled"] and overlay_live is not False
        base_matches = base_matches and (
            live_enabled is True
            and _money_equal(config.limits.task_cost_ceiling_usd, task_ceiling)
            and _money_equal(config.limits.application_cost_ceiling_usd, period_ceiling)
            and config.limits.task_deadline_ms == deadline
        )
    return base_matches


def _money_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return False


def _check_live_evidence(
    release: LoadedRelease, checks: list[PreflightCheck], current: datetime
) -> None:
    evidence = release.live_evidence
    if evidence is None:
        _check(checks, "live_evidence", False, "immutable live evidence is missing")
        return
    age = current - evidence.verified_at.astimezone(UTC)
    fresh = timedelta(0) <= age <= timedelta(hours=release.config.live.evidence_max_age_hours)
    _check(
        checks,
        "live_evidence_freshness",
        fresh,
        "live evidence is current" if fresh else "live evidence is stale or future-dated",
    )
    health_fresh = timedelta(0) <= age <= timedelta(
        milliseconds=release.config.health.freshness_ms
    )
    _check(
        checks,
        "live_health_evidence_freshness",
        health_fresh,
        "live access evidence is fresh enough for provider readiness"
        if health_fresh
        else "live access evidence is too old for provider readiness",
    )

    catalog_models = release.policy_bundle.catalog["models"]
    required_aliases = tuple(
        alias
        for alias, model in catalog_models.items()
        if model["availability"]["configured_enabled"]
    )
    missing_or_mismatched: list[str] = []
    for alias in required_aliases:
        model = catalog_models[alias]
        item = evidence.models.get(alias)
        pricing = model["pricing"]
        if (
            item is None
            or item.provider_model_id != model["provider_model_id"]
            or item.pricing_version != pricing["version"]
            or not _money_equal(item.input_usd, pricing["input_usd"])
            or not _money_equal(item.cached_input_usd, pricing["cached_input_usd"])
            or not _money_equal(item.output_usd, pricing["output_usd"])
            or not _money_equal(
                item.cache_write_input_multiplier,
                pricing["cache_write_input_multiplier"],
            )
            or tuple(item.reasoning_efforts) != tuple(model["reasoning_efforts"])
            or item.source_url != model["source_url"]
            or model["availability"]["account_status"] != "verified"
            or pricing["status"] != "verified"
        ):
            missing_or_mismatched.append(alias)
    _check(
        checks,
        "live_model_access_and_pricing",
        not missing_or_mismatched,
        (
            "all enabled model access and standard prices match the active catalog"
            if not missing_or_mismatched
            else "missing or mismatched live evidence for: " + ",".join(sorted(missing_or_mismatched))
        ),
    )


def preflight(
    release: LoadedRelease,
    *,
    environment: Mapping[str, str] | None = None,
    evidence: RuntimeEvidence | None = None,
    now: datetime | None = None,
) -> PreflightReport:
    """Evaluate release prerequisites without network calls or state changes."""

    env = os.environ if environment is None else environment
    runtime = evidence or RuntimeEvidence()
    current = _now(now)
    checks: list[PreflightCheck] = []
    config = release.config
    operations = config.operations

    _check(checks, "manifest", True, "strict release manifest and immutable references loaded")
    _check(checks, "policy_reference", True, "policy hash and all four versions match")

    active_required = operations.execute or operations.live_provider or operations.live_classifier
    policy_active = _policy_is_active(release)
    _check(
        checks,
        "policy_activation_status",
        not active_required or policy_active,
        (
            "active policy snapshots verified"
            if policy_active
            else "draft policy accepted only for the route-only surface"
            if not active_required
            else "execution requires separately active policy snapshots"
        ),
    )

    scopes = set(config.auth.required_scopes)
    enabled_scopes = {
        name for name in ("route", "read", "execute", "health", "classify_route") if getattr(operations, name)
    }
    _check(
        checks,
        "auth_configuration",
        enabled_scopes.issubset(scopes),
        "server-side auth scopes cover enabled operations",
    )
    try:
        credentials = parse_application_credentials(release, env)
    except CredentialConfigurationError:
        credentials = ()
    _check(
        checks,
        "auth_credentials",
        bool(credentials),
        f"{len(credentials)} application credential set(s) resolved"
        if credentials
        else "valid external application credentials are required",
    )

    database_url_present = _present(env, config.database.url_env)
    _check(
        checks,
        "database_url",
        database_url_present,
        "database URL source is present" if database_url_present else "database URL source is missing",
    )
    dialect_ok = runtime.database_dialect in config.database.allowed_dialects
    _check(
        checks,
        "database_connectivity",
        runtime.database_reachable and dialect_ok,
        "database is reachable with an allowed dialect"
        if runtime.database_reachable and dialect_ok
        else "database reachability and allowed dialect evidence are required",
    )
    revision_ok = runtime.database_revision == config.database.required_migration_revision
    _check(
        checks,
        "database_migration",
        revision_ok,
        "database is at the required migration revision"
        if revision_ok
        else "database migration revision does not match",
    )
    _check(
        checks,
        "outbox",
        runtime.outbox_ready,
        "leased at-least-once outbox is ready" if runtime.outbox_ready else "outbox readiness evidence is missing",
    )

    healthy = set(runtime.healthy_components)
    required_components = set(config.health.required_components)
    health_age = (
        current - runtime.health_observed_at.astimezone(UTC)
        if runtime.health_observed_at is not None and runtime.health_observed_at.utcoffset() is not None
        else None
    )
    health_fresh = (
        health_age is not None
        and timedelta(0) <= health_age <= timedelta(milliseconds=config.health.freshness_ms)
    )
    health_ok = (
        runtime.health_ready
        and runtime.health_config_version == config.health.config_version
        and health_fresh
        and required_components.issubset(healthy)
    )
    _check(
        checks,
        "health",
        health_ok,
        "required health components are fresh and ready"
        if health_ok
        else "fresh matching health readiness evidence is required",
    )
    evaluator_ok = set(config.evaluators.required_refs).issubset(runtime.evaluator_refs)
    _check(
        checks,
        "evaluators",
        evaluator_ok,
        "deterministic V0 evaluator dependencies are available"
        if evaluator_ok
        else "required evaluator dependencies are missing",
    )
    retention_ok = (
        not config.retention.raw_prompt_storage
        and not config.retention.raw_response_storage
        and not config.retention.automatic_destructive_pruning
    )
    _check(
        checks,
        "retention",
        retention_ok,
        "content-free indefinite policy, pricing, and budget evidence retention configured",
    )

    limits = config.limits
    bounded = (
        limits.task_cost_ceiling_usd <= limits.application_cost_ceiling_usd
        and limits.provider_timeout_ms <= limits.task_deadline_ms
        and limits.actions.max_total_generation_attempts > 0
        and limits.backoff.maximum_ms >= limits.backoff.initial_ms
    )
    _check(checks, "operational_limits", bounded, "finite budgets, time, actions, and backoff configured")

    if operations.execute:
        policy_live = release.policy_bundle.budgets["defaults"]["live_execution_enabled"] is True
        _check(
            checks,
            "policy_execution_authorization",
            policy_live,
            "active policy authorizes bounded live execution"
            if policy_live
            else "policy budget snapshot does not authorize live execution",
        )
        _check(
            checks,
            "policy_recovery_limits",
            _recovery_is_finite(release),
            "active policy recovery is finite"
            if _recovery_is_finite(release)
            else "active policy recovery limits are unresolved",
        )
        runtime_limits_match = _policy_limits_match_runtime(release, credentials)
        _check(
            checks,
            "policy_runtime_limits",
            runtime_limits_match,
            "runtime budgets, actions, deadlines, and deterministic backoff match policy"
            if runtime_limits_match
            else "runtime limits do not exactly match active policy",
        )

    live_enabled = operations.live_provider or operations.live_classifier
    if live_enabled:
        _check(checks, "live_runtime_opt_in", env.get("RUN_LIVE_OPENAI_TESTS") == "1",
            "explicit provider runtime opt-in is present" if env.get("RUN_LIVE_OPENAI_TESTS") == "1"
            else "explicit provider runtime opt-in is absent")
        credential_matches = (release.live_evidence is not None
            and isinstance(env.get(config.live.credential_env), str)
            and sha256(env[config.live.credential_env].encode()).hexdigest() == release.live_evidence.credential_sha256)
        _check(checks, 'live_credential_evidence', credential_matches,
            'credential matches account-access evidence' if credential_matches else 'credential does not match account-access evidence')
        _check(
            checks,
            "provider_credentials",
            _present(env, config.live.credential_env),
            "provider credential source is present"
            if _present(env, config.live.credential_env)
            else "provider credential source is missing",
        )
        _check_live_evidence(release, checks, current)
        catalog_probe = release.policy_bundle.catalog["verification"]["live_account_probe_performed"] is True
        _check(
            checks,
            "catalog_live_verification",
            catalog_probe,
            "active catalog records an account access probe"
            if catalog_probe
            else "active catalog lacks account access probe evidence",
        )
        enabled_aliases = {
            alias
            for alias, model in release.policy_bundle.catalog["models"].items()
            if model["availability"]["configured_enabled"]
        }
        required_live_health = {f"provider:{alias}" for alias in enabled_aliases}
        if operations.live_classifier:
            required_live_health.add("classifier")
        live_health_ok = required_live_health.issubset(set(runtime.healthy_components))
        _check(
            checks,
            "live_health",
            live_health_ok,
            "fresh health evidence covers every live dependency"
            if live_health_ok
            else "live dependency health evidence is missing",
        )
        output_bounds = all(
            config.limits.max_output_tokens <= model["max_output_tokens"]
            and config.limits.max_input_tokens + config.limits.max_output_tokens <= model["context_window_tokens"]
            and config.limits.max_input_tokens <= model['pricing']['long_context']['input_tokens_gt']
            for model in release.policy_bundle.catalog["models"].values()
            if model["availability"]["configured_enabled"]
        )
        _check(
            checks,
            "model_token_bounds",
            output_bounds,
            "release token bounds fit every enabled model"
            if output_bounds
            else "release token bounds exceed an enabled model",
        )
    else:
        _check(checks, "live_execution", True, "live provider and classifier are disabled")

    if operations.live_classifier:
        classifier = release.classifier_config
        classifier_ok = (
            classifier is not None
            and classifier.status == "active"
            and classifier.live_enabled
            and classifier.max_output_tokens <= config.limits.max_output_tokens
            and classifier.timeout_ms <= config.limits.provider_timeout_ms
        )
        _check(
            checks,
            "classifier",
            classifier_ok,
            "active classifier configuration is bound to this policy"
            if classifier_ok
            else "active policy-bound live classifier configuration is required",
        )

    blockers = tuple(check.name for check in checks if not check.passed)
    return PreflightReport(
        release_id=config.release_id,
        release_sha256=release.release_sha256,
        checked_at=current,
        ready=not blockers,
        enabled_operations=_enabled_operations(release),
        checks=tuple(checks),
        blockers=blockers,
    )


def _portable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_portable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _report_payload(report: ActivationReport) -> bytes:
    return (
        json.dumps(
            _portable(report.model_dump(mode="python")),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _persist_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = -1
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def activate(
    release: LoadedRelease,
    *,
    environment: Mapping[str, str] | None = None,
    evidence: RuntimeEvidence | None = None,
    report_path: str | Path | None = None,
    now: datetime | None = None,
) -> ActivationReport:
    """Rerun preflight and return a deeply immutable activation snapshot.

    If ``report_path`` is supplied the report is created once, fsynced, and made
    read-only.  Existing paths are never overwritten.
    """

    result = preflight(release, environment=environment, evidence=evidence, now=now)
    if not result.ready:
        raise ActivationBlocked(result)
    live = release.config.operations.live_provider
    scope = (
        "paid classifier-only routing preview; generation disabled"
        if release.config.operations.classify_route and not live
        else "standard-text V0 live classifier and generation"
        if release.config.operations.live_classifier
        else "standard-text V0 live generation"
        if live
        else "authenticated route/read/health service; provider execution disabled"
    )
    manifest = dict(thaw(release.canonical_manifest))
    identity_payload = {
        "release_sha256": release.release_sha256,
        "activated_at": result.checked_at.isoformat(),
        "enabled_operations": list(result.enabled_operations),
        "checks": [check.model_dump(mode="json") for check in result.checks],
    }
    activation_id = "activation-" + sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report = ActivationReport(
        activation_id=activation_id,
        release_id=release.config.release_id,
        release_sha256=release.release_sha256,
        activated_at=result.checked_at,
        enabled_operations=result.enabled_operations,
        operation_scope=scope,
        live_execution_enabled=live,
        paid_classifier_enabled=release.config.operations.live_classifier,
        manifest=manifest,
        checks=result.checks,
    )
    if report_path is not None:
        _persist_immutable(Path(report_path), _report_payload(report))
    return report


__all__ = [
    "ActivationBlocked",
    "CredentialConfigurationError",
    "activate",
    "parse_application_credentials",
    "preflight",
]
