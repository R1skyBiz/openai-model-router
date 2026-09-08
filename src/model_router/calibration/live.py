"""Explicit fail-closed authorization for paid calibration work."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

from model_router.calibration.budget import CalibrationAllocation
from model_router.calibration.contracts import BudgetPlan, ExperimentConfig
from model_router.core.contracts import Limits, ModelHealth
from model_router.core.provider_contracts import ProviderRequest
from model_router.release.loader import LoadedRelease, load_release
from model_router.execution.live import ReleaseEnvironmentSnapshot


class LiveCalibrationBlocked(ValueError):
    """Safe diagnostic for a calibration run that must make no paid calls."""


@dataclass
class LiveCalibrationGuard:
    """Bind a paid experiment to fresh release evidence and a finite allocation.

    The separately locked allocation ledger is the durable authority.  A whole
    run bound is reserved before the first paid action; construction performs no
    provider action.
    """

    release: LoadedRelease | str | Path
    allocation: CalibrationAllocation
    environment: Mapping[str, str] | None = None
    now: datetime | None = None
    _cap: Decimal | None = field(default=None, init=False, repr=False)
    _spent: Decimal = field(default=Decimal("0"), init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    _authorized_once: bool = field(default=False, init=False, repr=False)
    _run_id: str | None = field(default=None, init=False, repr=False)
    _finished: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.release, LoadedRelease):
            self.release = load_release(self.release)
        if not isinstance(self.allocation, CalibrationAllocation):
            raise LiveCalibrationBlocked("a durable calibration allocation is required")

    @property
    def stopped(self) -> bool:
        return self._stopped

    def require_ready(self, config: ExperimentConfig, plan: BudgetPlan, bundle=None,
                      classifier_config=None, *, run_id: str,
                      software_commit: str | None) -> None:
        if self._authorized_once:
            raise LiveCalibrationBlocked("live authorization cannot be reused")
        self._authorized_once = True
        self._validate_current_release(config, bundle, classifier_config)
        release = self.release
        assert isinstance(release, LoadedRelease)
        if not plan.admissible or plan.estimated_upper_bound_usd is None:
            raise LiveCalibrationBlocked("experiment lacks an admissible finite cost bound")
        if plan.estimated_upper_bound_usd > config.aggregate_cap_usd:
            raise LiveCalibrationBlocked("experiment bound exceeds aggregate cap")
        if config.aggregate_cap_usd > release.config.limits.application_cost_ceiling_usd:
            raise LiveCalibrationBlocked("experiment cap exceeds the release allocation")
        if software_commit is None or software_commit.endswith("-dirty"):
            raise LiveCalibrationBlocked("live calibration requires a clean pinned software commit")
        if config.allocation_id != self.allocation.allocation_id:
            raise LiveCalibrationBlocked("experiment allocation id does not match durable allocation")
        if config.allocation_cap_usd != self.allocation.ceiling:
            raise LiveCalibrationBlocked("experiment allocation cap does not match durable allocation")
        if config.allocation_directory is None:
            raise LiveCalibrationBlocked("experiment allocation directory is not pinned")
        configured_allocation = Path(config.allocation_directory).expanduser()
        if (
            not configured_allocation.is_absolute()
            or configured_allocation != configured_allocation.resolve()
            or configured_allocation != self.allocation.root.expanduser().resolve()
        ):
            raise LiveCalibrationBlocked("experiment allocation directory does not match durable allocation")
        try:
            self.allocation.reserve(run_id, plan.estimated_upper_bound_usd)
        except (OSError, ValueError):
            raise LiveCalibrationBlocked("durable allocation reservation failed") from None
        self._experiment_config = config
        self._classifier_config = classifier_config
        self._run_id = run_id
        self._cap = plan.estimated_upper_bound_usd
        self._spent = Decimal("0")
        self._stopped = False

    def _validate_current_release(self, config: ExperimentConfig, bundle=None,
                                  classifier_config=None) -> None:
        env = os.environ if self.environment is None else self.environment
        current = self.now or datetime.now(UTC)
        if current.utcoffset() is None:
            raise LiveCalibrationBlocked("live calibration clock must be timezone-aware")
        release = self.release
        assert isinstance(release, LoadedRelease)
        try:
            refreshed = load_release(release.source)
        except Exception:
            raise LiveCalibrationBlocked("pinned release cannot be reloaded") from None
        if refreshed.release_sha256 != release.release_sha256:
            raise LiveCalibrationBlocked("pinned release changed after authorization")
        self.release = release = refreshed
        if env.get("RUN_LIVE_CALIBRATION") != "1" or not config.live_enabled:
            raise LiveCalibrationBlocked("explicit live calibration opt-in is required")
        if config.release_manifest is None:
            raise LiveCalibrationBlocked("live calibration requires a pinned release manifest")
        configured_path = Path(config.release_manifest).expanduser().resolve()
        if configured_path != release.source:
            raise LiveCalibrationBlocked("experiment release manifest does not match loaded release")
        if bundle is not None and bundle.content_hash != release.policy_bundle.content_hash:
            raise LiveCalibrationBlocked("experiment policy differs from the pinned release")
        operations = release.config.operations
        needs_classifier = any(strategy.kind == "router" for strategy in config.strategies)
        if not operations.live_provider or (needs_classifier and not operations.live_classifier):
            raise LiveCalibrationBlocked("release does not enable required live operations")
        if needs_classifier and (
            classifier_config is None
            or release.classifier_config is None
            or classifier_config.configuration_hash
            != release.classifier_config.configuration_hash
        ):
            raise LiveCalibrationBlocked("classifier does not match pinned live release")
        limits = release.config.limits
        actions = limits.actions
        if (
            config.deadline_ms > limits.task_deadline_ms
            or config.max_input_tokens > limits.max_input_tokens
            or config.max_output_tokens > limits.max_output_tokens
            or config.max_generation_attempts > actions.max_total_generation_attempts
            or any(
                binding is not None and (
                    binding.timeout_ms > min(limits.provider_timeout_ms, release.config.evaluators.timeout_ms)
                    or binding.max_input_tokens > limits.max_input_tokens
                    or binding.max_output_tokens > limits.max_output_tokens
                    or binding.retries + 1 > release.config.evaluators.max_attempts
                )
                for binding in (config.evaluator, config.adjudicator)
            )
            or (
                classifier_config is not None and (
                    classifier_config.timeout_ms > limits.provider_timeout_ms
                    or classifier_config.max_output_tokens > limits.max_output_tokens
                )
            )
        ):
            raise LiveCalibrationBlocked("experiment invocation bounds exceed pinned release limits")
        evidence = release.live_evidence
        if evidence is None:
            raise LiveCalibrationBlocked("immutable live evidence is missing")
        age = current.astimezone(UTC) - evidence.verified_at.astimezone(UTC)
        if not timedelta(0) <= age <= timedelta(hours=release.config.live.evidence_max_age_hours):
            raise LiveCalibrationBlocked("live access and pricing evidence is stale")
        if age > timedelta(milliseconds=release.config.health.freshness_ms):
            raise LiveCalibrationBlocked("live provider readiness evidence is stale")
        credential = env.get(release.config.live.credential_env)
        if not isinstance(credential, str) or not credential.strip():
            raise LiveCalibrationBlocked("release credential source is unavailable")
        if sha256(credential.encode()).hexdigest() != evidence.credential_sha256:
            raise LiveCalibrationBlocked("credential does not match live access evidence")
        self._verify_catalog_evidence()

    def _verify_catalog_evidence(self) -> None:
        release = self.release
        assert isinstance(release, LoadedRelease)
        evidence = release.live_evidence
        assert evidence is not None
        for alias, model in release.policy_bundle.catalog["models"].items():
            if not model["availability"]["configured_enabled"]:
                continue
            item = evidence.models.get(alias)
            pricing = model["pricing"]
            if (
                item is None
                or item.provider_model_id != model["provider_model_id"]
                or item.pricing_version != pricing["version"]
                or item.reasoning_efforts != tuple(model["reasoning_efforts"])
                or model["availability"]["account_status"] != "verified"
                or pricing["status"] != "verified"
                or any(
                    Decimal(str(actual)) != Decimal(str(expected))
                    for actual, expected in (
                        (item.input_usd, pricing["input_usd"]),
                        (item.cached_input_usd, pricing["cached_input_usd"]),
                        (item.output_usd, pricing["output_usd"]),
                        (item.cache_write_input_multiplier, pricing["cache_write_input_multiplier"]),
                    )
                )
            ):
                raise LiveCalibrationBlocked("live model access or pricing evidence does not match catalog")

    def before_dispatch(self, request: ProviderRequest, upper_bound_usd: Decimal | None,
                        purpose: str | None = None) -> None:
        if self._cap is None or self._stopped:
            raise LiveCalibrationBlocked("live calibration is not authorized")
        if upper_bound_usd is None or not upper_bound_usd.is_finite() or upper_bound_usd < 0:
            self._stopped = True
            raise LiveCalibrationBlocked("paid action has no finite cost bound")
        with localcontext() as context:
            context.prec = 80
            exceeds_cap = self._spent + upper_bound_usd > self._cap
        if exceeds_cap:
            self._stopped = True
            raise LiveCalibrationBlocked("paid action would exceed aggregate cap")
        release = self.release
        assert isinstance(release, LoadedRelease)
        # The immutable manifest, evidence file, freshness, and credential
        # binding are reloaded immediately before every paid action.
        config = getattr(self, "_experiment_config", None)
        if config is None:
            raise LiveCalibrationBlocked("live calibration is not authorized")
        try:
            self._validate_current_release(
                config, classifier_config=getattr(self, "_classifier_config", None)
            )
            assert self._run_id is not None
            self.allocation.assert_ready(self._run_id)
        except LiveCalibrationBlocked:
            self._stopped = True
            raise
        except (OSError, ValueError):
            self._stopped = True
            raise LiveCalibrationBlocked("durable allocation is not ready") from None
        release = self.release
        assert isinstance(release, LoadedRelease)
        model = release.policy_bundle.catalog["models"].get(request.model_alias)
        item = release.live_evidence.models.get(request.model_alias) if release.live_evidence else None
        if (
            model is None
            or not model["availability"]["configured_enabled"]
            or request.reasoning_effort.value not in model["reasoning_efforts"]
            or model["capabilities"].get("text_input") is not True
            or model["capabilities"].get("text_output") is not True
            or (request.output_type is not None and model["capabilities"].get("structured_outputs") is not True)
            or item is None
            or not item.access_verified
            or item.provider_model_id != request.provider_model_id
        ):
            self._stopped = True
            raise LiveCalibrationBlocked("paid action model lacks pinned access or capability evidence")
        wire = request.model_dump(mode="json")
        wire.update(input=request.input, instructions=request.instructions)
        if request.output_type is not None:
            wire["output_schema"] = request.output_type.model_json_schema()
        size = len(json.dumps(wire, sort_keys=True, ensure_ascii=True).encode("utf-8"))
        limits = release.config.limits
        if size + release.config.live.classifier_input_overhead_tokens > limits.max_input_tokens:
            self._stopped = True
            raise LiveCalibrationBlocked("serialized paid request exceeds release input bound")
        if request.max_output_tokens > limits.max_output_tokens or request.timeout_ms > limits.provider_timeout_ms:
            self._stopped = True
            raise LiveCalibrationBlocked("paid request exceeds release invocation bounds")

    def after_dispatch(self, actual_cost_usd: Decimal | None, reserved_cost_usd: Decimal | None = None) -> None:
        if actual_cost_usd is None:
            self._stopped = True
            raise LiveCalibrationBlocked("paid action cost is unknown")
        if not actual_cost_usd.is_finite() or actual_cost_usd < 0:
            self._stopped = True
            raise LiveCalibrationBlocked("paid action cost is invalid")
        with localcontext() as context:
            context.prec = 80
            self._spent += actual_cost_usd
        if reserved_cost_usd is not None and actual_cost_usd > reserved_cost_usd:
            self._stopped = True
            raise LiveCalibrationBlocked("actual paid action exceeded its reservation")
        if self._cap is None or self._spent > self._cap:
            self._stopped = True
            raise LiveCalibrationBlocked("actual experiment spend exceeded aggregate cap")

    def finish_run(self, actual_cost_usd: Decimal | None) -> None:
        """Settle the whole run once; unknown spend deliberately holds its bound."""
        if self._run_id is None or self._finished:
            return
        self._finished = True
        try:
            self.allocation.settle(self._run_id, actual_cost_usd)
        except (OSError, ValueError):
            self._stopped = True
            raise LiveCalibrationBlocked("durable allocation settlement failed") from None

    def environment_snapshot(self, config: ExperimentConfig) -> ReleaseEnvironmentSnapshot:
        release = self.release
        assert isinstance(release, LoadedRelease)
        evidence = release.live_evidence
        if self._cap is None or evidence is None:
            raise LiveCalibrationBlocked("live calibration is not authorized")
        current = self.now or datetime.now(UTC)
        models = {
            alias: ModelHealth(state="HEALTHY", account_access="verified", usable=True)
            for alias, model in release.policy_bundle.catalog["models"].items()
            if model["availability"]["configured_enabled"]
        }
        return ReleaseEnvironmentSnapshot(
            release_version=release.config.release_id,
            snapshot_id=release.release_sha256,
            clock=current,
            pricing_version=evidence.evidence_id,
            health_snapshot_id=evidence.evidence_id,
            health_observed_at=evidence.verified_at,
            health_valid_until=evidence.verified_at
            + timedelta(milliseconds=release.config.health.freshness_ms),
            models=models,
            budget=Limits(
                task_cost_ceiling_usd=config.aggregate_cap_usd,
                task_deadline_ms=config.deadline_ms,
                live_execution_enabled=True,
            ),
            remaining_usd=max(Decimal("0"), config.aggregate_cap_usd - self._spent),
            requested_validation="V0",
            recovery_bounded=True,
            durable_retention=True,
        )


__all__ = ["LiveCalibrationBlocked", "LiveCalibrationGuard"]
