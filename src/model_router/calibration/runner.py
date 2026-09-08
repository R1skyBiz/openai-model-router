"""Isolated calibration orchestration over the canonical routing boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import random
import subprocess
import time
from uuid import uuid4

from model_router.calibration.contracts import (
    BlindCandidate,
    CalibrationRun,
    CallEvidence,
    Disposition,
    Grade,
    RunManifest,
    StrategyRun,
)
from model_router.calibration.corpus import (
    canonical_case_input,
    canonical_comparison_sha256,
    case_content_sha256,
)
from model_router.calibration.live import LiveCalibrationBlocked
from model_router.calibration.output import compile_output_type
from model_router.calibration.planning import _call_bound, plan_budget
from model_router.calibration.storage import CalibrationStorageError
from model_router.classification.classifier import build_output_type
from model_router.core.classifier_contracts import ClassificationFailure
from model_router.core.contracts import (
    Candidate,
    EnvironmentSnapshot,
    FailureType,
    Limits,
    ModelHealth,
    Request,
    RouteDecision,
    RouteRejection,
    ValidationLevel,
)
from model_router.core.execution_contracts import Counters, ExecutionLimits, Failure, RecoveryContext
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult
from model_router.escalation.recovery import choose_recovery
from model_router.execution.accounting import provider_cost
from model_router.execution.arithmetic import money_sum
from model_router.policy.capabilities import check_capabilities
from model_router.policy.validation import determine_validation
from model_router.router import route


class _StrategyDeadline(RuntimeError):
    pass


def _digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _rubric_snapshot(cases) -> tuple[dict, ...]:
    values = {}
    for case in cases:
        rubric = case.grading.rubric
        if rubric is not None:
            payload = rubric.model_dump(mode="json")
            digest = _digest(payload)
            values[(rubric.rubric_id, rubric.version, digest)] = {
                "rubric_id": rubric.rubric_id,
                "version": rubric.version,
                "sha256": digest,
            }
    return tuple(values[key] for key in sorted(values))


def _software_commit() -> str | None:
    try:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"), capture_output=True, text=True,
            check=True, timeout=2,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ("git", "status", "--porcelain"),
            capture_output=True, text=True, check=True, timeout=2,
        ).stdout.strip())
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def _validation_signature(case, production_validation: str) -> str:
    return _digest(
        {
            "grading": case.grading.model_dump(mode="json"),
            "output_contract": case.output_contract.model_dump(mode="json"),
            "production_validation": production_validation,
            "deadline_ms": case.deadline_ms,
        }
    )


def _output(result: ProviderResult) -> str | None:
    if result.structured_output is not None:
        return json.dumps(
            result.structured_output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
    return result.text


def _wire_bytes(request: ProviderRequest) -> int:
    wire = request.model_dump(mode="json")
    wire.update(input=request.input, instructions=request.instructions)
    if request.output_type is not None:
        wire["output_schema"] = request.output_type.model_json_schema()
    return len(json.dumps(wire, sort_keys=True, ensure_ascii=True).encode("utf-8"))


class _AdmittedProvider:
    """Persist intent, invoke once, and retain normalized cost evidence."""

    def __init__(self, runner, provider, purpose_override: str | None = None):
        self.runner = runner
        self.provider = provider
        self.purpose_override = purpose_override

    def execute(self, request: ProviderRequest):
        return self.runner._provider_action(request, self.provider, self.purpose_override)


class CalibrationRunner:
    """Execute fixed and dynamic strategies without touching production telemetry."""

    def __init__(
        self,
        bundle,
        classifier_config,
        config,
        *,
        provider,
        classifier,
        grader,
        store,
        live_guard=None,
    ):
        self.bundle = bundle
        self.classifier_config = classifier_config
        self.config = config
        self.provider = provider
        self.classifier = classifier
        self.grader = grader
        self.store = store
        self.live_guard = live_guard
        self._source_provider = provider
        self._source_classifier = classifier
        self._source_evaluators = (
            getattr(grader, "evaluator", None), getattr(grader, "adjudicator", None)
        )
        self._manifest = None
        self._active = None
        self._call_records: dict[str, CallEvidence] = {}
        self._started_unsettled: set[str] = set()
        self._spent = Decimal("0")
        self._budget_stopped = False
        self._generation_provider = _AdmittedProvider(self, provider)
        # OpenAIClassifier and ProviderSemanticEvaluator intentionally expose a
        # provider port. Replace only that port, preserving their normalization.
        if hasattr(classifier, "_provider"):
            classifier._provider = _AdmittedProvider(self, classifier._provider)
        for role, purpose in ((getattr(grader, "evaluator", None), "judge"),
                              (getattr(grader, "adjudicator", None), "adjudication")):
            if role is not None and hasattr(role, "provider"):
                role.provider = _AdmittedProvider(self, role.provider, purpose)
                if hasattr(role, "evidence_factory"):
                    role.evidence_factory = self._evaluator_evidence

    def _evaluator_evidence(self, request, outcome, purpose, attempt_number):
        evidence = self._call_records[request.invocation_id]
        if evidence.purpose != purpose:
            raise ValueError("evaluator purpose mismatch")
        return evidence.model_copy(update={"attempt_number": attempt_number})

    def _require_composition(self, offline: bool) -> None:
        """Reject adapters which could bypass the admitted provider wrapper."""
        from model_router.execution.provider import MockProvider
        if offline:
            from model_router.classification import MockClassifier
            from model_router.calibration.offline import OfflineProviderClassifier
            if not isinstance(self._source_provider, MockProvider):
                raise ValueError("offline calibration requires MockProvider")
            if not isinstance(self._source_classifier, (MockClassifier, OfflineProviderClassifier)):
                raise ValueError("offline calibration requires an approved mock classifier")
            for evaluator in self._source_evaluators:
                if evaluator is not None and hasattr(evaluator, "provider"):
                    source = evaluator.provider
                    if isinstance(source, _AdmittedProvider):
                        source = source.provider
                    if not isinstance(source, MockProvider):
                        raise ValueError("offline evaluator requires MockProvider")
            return
        from model_router.classification import OpenAIClassifier
        from model_router.calibration.grading import ProviderSemanticEvaluator
        if getattr(self._source_provider, "calibration_live_authorized", False) is not True:
            raise LiveCalibrationBlocked("live provider adapter is not approved")
        if type(self._source_classifier) is not OpenAIClassifier:
            raise LiveCalibrationBlocked("live classifier adapter is not approved")
        classifier_provider = getattr(self._source_classifier, "_provider", None)
        if (
            not isinstance(classifier_provider, _AdmittedProvider)
            or classifier_provider.provider is not self._source_provider
        ):
            raise LiveCalibrationBlocked("live classifier is not bound to the approved provider")
        for evaluator in self._source_evaluators:
            if evaluator is not None and type(evaluator) is not ProviderSemanticEvaluator:
                raise LiveCalibrationBlocked("live evaluator adapter is not approved")
            if evaluator is not None:
                wrapped = getattr(evaluator, "provider", None)
                if not isinstance(wrapped, _AdmittedProvider) or wrapped.provider is not self._source_provider:
                    raise LiveCalibrationBlocked("live evaluator is not bound to the approved provider")

    def _event(self, event):
        self.store.append_event(self._manifest.run_id, {"run_id": self._manifest.run_id, **event})

    def _environment(self, offline: bool):
        if not offline:
            return self.live_guard.environment_snapshot(self.config)
        now = datetime.now(UTC)
        return EnvironmentSnapshot(
            snapshot_id=f"calibration-{self._manifest.run_id}",
            synthetic=True,
            clock=now,
            pricing_version=self.bundle.catalog["catalog_version"],
            health_snapshot_id=f"health-{self._manifest.run_id}",
            health_observed_at=now,
            health_valid_until=now + timedelta(hours=1),
            models={
                alias: ModelHealth(state="HEALTHY", account_access="verified", usable=True)
                for alias, model in self.bundle.catalog["models"].items()
                if model["availability"]["configured_enabled"]
            },
            budget=Limits(
                task_cost_ceiling_usd=self.config.aggregate_cap_usd,
                task_deadline_ms=self.config.deadline_ms,
                live_execution_enabled=True,
            ),
            remaining_usd=self.config.aggregate_cap_usd,
            validation={ValidationLevel.V0: "configured_mock"},
            requested_validation=ValidationLevel.V0,
            recovery_bounded=True,
            durable_retention=True,
        )

    def _bound(self, request: ProviderRequest, purpose: str) -> Decimal | None:
        model = self.bundle.catalog["models"].get(request.model_alias)
        if model is None:
            return None
        input_tokens = self.config.max_input_tokens
        if purpose == "judge" and self.config.evaluator is not None:
            input_tokens = self.config.evaluator.max_input_tokens
        elif purpose == "adjudication" and self.config.adjudicator is not None:
            input_tokens = self.config.adjudicator.max_input_tokens
        return _call_bound(
            model,
            input_tokens=input_tokens,
            output_tokens=request.max_output_tokens,
        )

    def _case_blocker(self, case, output_type) -> str | None:
        if (
            case.context.input_tokens > self.config.max_input_tokens
            or case.context.expected_output_tokens <= 0
            or case.context.expected_output_tokens > self.config.max_output_tokens
            or case.tool_policy.available
        ):
            return "unsupported_case_envelope"
        canonical = canonical_case_input(case)
        aliases = {
            strategy.model
            for strategy in self.config.strategies
            if strategy.kind == "fixed"
        }
        if any(strategy.kind == "router" for strategy in self.config.strategies):
            aliases.update(
                alias for alias, model in self.bundle.catalog["models"].items()
                if model["availability"]["configured_enabled"]
            )
        for alias in aliases:
            model = self.bundle.catalog["models"].get(alias)
            if model is None:
                return "fixed_route_unsupported"
            request = ProviderRequest(
                task_id="calibration-preflight", trace_id="calibration-preflight",
                invocation_id="generation-preflight", policy_version=self.bundle.policy["version"],
                catalog_version=self.bundle.catalog["catalog_version"], model_alias=alias,
                provider_model_id=model["provider_model_id"],
                reasoning_effort=model["reasoning_efforts"][0], input=canonical,
                output_type=output_type, max_output_tokens=case.context.expected_output_tokens,
                timeout_ms=min(case.deadline_ms, self.config.deadline_ms), purpose="generation",
            )
            if _wire_bytes(request) + self.config.input_overhead_tokens > self.config.max_input_tokens:
                return "serialized_generation_input_exceeds_bound"
        if any(strategy.kind == "router" for strategy in self.config.strategies):
            model = self.bundle.catalog["models"].get(self.classifier_config.model_alias)
            if model is None:
                return "classifier_route_unsupported"
            request = ProviderRequest(
                task_id="calibration-preflight", trace_id="calibration-preflight",
                invocation_id="classifier-preflight", policy_version=self.bundle.policy["version"],
                catalog_version=self.bundle.catalog["catalog_version"],
                model_alias=self.classifier_config.model_alias,
                provider_model_id=model["provider_model_id"],
                reasoning_effort=self.classifier_config.reasoning_effort,
                input=canonical, instructions=self.classifier_config.prompt_text,
                output_type=build_output_type(self.bundle),
                max_output_tokens=self.classifier_config.max_output_tokens,
                timeout_ms=min(self.classifier_config.timeout_ms, case.deadline_ms, self.config.deadline_ms),
                purpose="classification",
            )
            if _wire_bytes(request) + self.config.input_overhead_tokens > self.config.max_input_tokens:
                return "serialized_classifier_input_exceeds_bound"
        rubric = case.grading.rubric
        if rubric is not None:
            grading_bytes = len(json.dumps({
                "task": case.task, "instructions": case.instructions,
                "context": case.context_text,
                "output_contract": case.output_contract.model_dump(mode="json"),
                "rubric": rubric.model_dump(mode="json"),
            }, sort_keys=True, default=str).encode("utf-8"))
            grading_bytes += self.config.max_output_tokens * 4 + self.config.input_overhead_tokens
            for binding in (self.config.evaluator, self.config.adjudicator):
                if binding is not None and grading_bytes > binding.max_input_tokens:
                    return "serialized_evaluator_input_exceeds_bound"
        return None

    def _provider_action(self, request, provider, purpose_override=None):
        if self._active is None:
            raise RuntimeError("provider action outside calibration strategy")
        purpose = purpose_override or request.purpose
        if purpose == "evaluation":
            purpose = "judge"
        def admission_denied():
            if purpose not in {"judge", "adjudication"}:
                return
            self._call_records[request.invocation_id] = CallEvidence(
                call_id=request.invocation_id,
                purpose=purpose,
                model=request.model_alias,
                effort=request.reasoning_effort,
                cost_usd=Decimal("0"),
                status="failed",
                failure_type="calibration_admission_denied",
                pricing_version=self.bundle.catalog["models"].get(
                    request.model_alias, {}
                ).get("pricing", {}).get("version"),
                attempt_number=self._active.get("attempt_number", 1),
            )
        remaining_ms = int((self._active["deadline_at"] - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            admission_denied()
            raise _StrategyDeadline("strategy deadline exhausted")
        request = request.model_copy(update={"timeout_ms": min(request.timeout_ms, remaining_ms)})
        input_limit = self.config.max_input_tokens
        if purpose == "judge" and self.config.evaluator is not None:
            input_limit = self.config.evaluator.max_input_tokens
        elif purpose == "adjudication" and self.config.adjudicator is not None:
            input_limit = self.config.adjudicator.max_input_tokens
        if _wire_bytes(request) + self.config.input_overhead_tokens > input_limit:
            self._budget_stopped = True
            admission_denied()
            raise LiveCalibrationBlocked("serialized action exceeds input bound")
        bound = self._bound(request, purpose)
        if bound is None or money_sum((self._spent, bound)) > self.config.aggregate_cap_usd:
            self._budget_stopped = True
            admission_denied()
            raise LiveCalibrationBlocked("calibration action failed budget admission")
        if self.live_guard is not None:
            try:
                self.live_guard.before_dispatch(request, bound, purpose)
            except LiveCalibrationBlocked:
                admission_denied()
                raise
        journal_call_id = "call-" + sha256(request.invocation_id.encode()).hexdigest()[:24]
        self._event({
            "kind": "action_started",
            "strategy_run_id": self._active["strategy_run_id"],
            "call_id": journal_call_id,
            "purpose": purpose,
            "status": "started",
            "attempt_number": self._active.get("attempt_number", 1),
            "model": request.model_alias,
            "effort": request.reasoning_effort.value,
        })
        started = time.monotonic()
        outcome = None
        self._started_unsettled.add(request.invocation_id)
        try:
            outcome = provider.execute(request)
            if not isinstance(outcome, (ProviderResult, ProviderFailure)) or any(
                getattr(outcome, name) != getattr(request, name)
                for name in (
                    "task_id", "trace_id", "invocation_id", "policy_version",
                    "catalog_version", "model_alias", "provider_model_id",
                    "reasoning_effort", "purpose",
                )
            ):
                raise ValueError("provider correlation mismatch")
        except Exception:
            evidence = CallEvidence(
                call_id=request.invocation_id,
                purpose=purpose,
                model=request.model_alias,
                effort=request.reasoning_effort,
                cost_usd=None,
                latency_ms=max(0, (time.monotonic() - started) * 1000),
                status="unknown",
                failure_type="provider_contract_error",
                pricing_version=self.bundle.catalog["models"][request.model_alias]["pricing"]["version"],
                attempt_number=self._active.get("attempt_number", 1),
            )
            self._call_records[request.invocation_id] = evidence
            self._event({
                "kind": "action_completed", "strategy_run_id": self._active["strategy_run_id"],
                "call_id": journal_call_id, "purpose": purpose, "status": "unknown",
                "failure_type": "provider_contract_error",
            })
            if self.live_guard is not None:
                try:
                    self.live_guard.after_dispatch(None)
                except LiveCalibrationBlocked:
                    pass
            raise
        request_for_cost = self._active["request"]
        live_binding_unknown = bool(
            self.live_guard is not None
            and (
                outcome.returned_model_id != request.provider_model_id
                or outcome.returned_service_tier != "default"
            )
        )
        unsettled = live_binding_unknown or outcome.response_status in {"queued", "in_progress"}
        cost = (
            None if unsettled
            else provider_cost(request_for_cost, outcome, self.bundle, self._active["environment"])
        )
        status = "unknown" if unsettled else (
            "completed" if isinstance(outcome, ProviderResult) else "failed"
        )
        evidence = CallEvidence(
            call_id=request.invocation_id,
            purpose=purpose,
            model=request.model_alias,
            effort=request.reasoning_effort,
            cost_usd=cost,
            latency_ms=outcome.latency_ms,
            usage=outcome.usage,
            status=status,
            failure_type=(
                "live_response_binding_unknown" if live_binding_unknown
                else outcome.failure_type.value if isinstance(outcome, ProviderFailure) else None
            ),
            pricing_version=self.bundle.catalog["models"][request.model_alias]["pricing"]["version"],
            attempt_number=self._active.get("attempt_number", 1),
        )
        self._call_records[request.invocation_id] = evidence
        self._event({
            "kind": "action_completed", "strategy_run_id": self._active["strategy_run_id"],
            "call_id": journal_call_id, "purpose": purpose, "status": status,
            "cost_usd": cost, "failure_type": evidence.failure_type,
            "latency_ms": outcome.latency_ms,
        })
        if cost is not None:
            self._started_unsettled.discard(request.invocation_id)
        if self.live_guard is not None:
            self.live_guard.after_dispatch(cost, bound)
        if cost is not None:
            self._spent = money_sum((self._spent, cost))
            if cost > bound or self._spent > self.config.aggregate_cap_usd:
                self._budget_stopped = True
                raise LiveCalibrationBlocked("actual action cost exceeded budget reservation")
        if time.monotonic() >= self._active["deadline_at"]:
            raise _StrategyDeadline("strategy deadline exhausted")
        return outcome

    def _calls_since(self, before: set[str]) -> tuple[CallEvidence, ...]:
        return tuple(record for key, record in self._call_records.items() if key not in before)

    def _request(self, case, strategy_run_id):
        deadline = min(case.deadline_ms, self.config.deadline_ms)
        requirements = case.requirements
        if case.output_contract.format == "json" and "structured_outputs" not in requirements:
            requirements = (*requirements, "structured_outputs")
        return Request(
            task_id=strategy_run_id,
            trace_id=strategy_run_id,
            input=canonical_case_input(case),
            requirements=requirements,
            consequence=case.consequence,
            context=case.context,
            constraints=Limits(
                task_cost_ceiling_usd=self.config.aggregate_cap_usd,
                task_deadline_ms=deadline,
            ),
            requested_validation=ValidationLevel.V0,
            side_effecting_tool=False,
            policy_version=self.bundle.policy["version"],
        )

    def _invalid(self, case, strategy, strategy_run_id, reason, *, calls=(), classification=None):
        candidate_id = f"candidate-{uuid4().hex}"
        grade = Grade(candidate_id=candidate_id, disposition=Disposition.INVALID,
                      evidence_codes=(reason,))
        return StrategyRun(
            strategy_run_id=strategy_run_id, case_id=case.case_id, strategy=strategy,
            input_sha256=canonical_comparison_sha256(case),
            validation_signature=_validation_signature(case, self.config.production_validation),
            policy_version=self.bundle.policy["version"], calls=calls,
            classification=classification, execution_status="invalid",
            complete=True, grade=grade, source_kind=case.source_kind,
            consequence=case.consequence, tags=case.tags, task_family=case.task_family_hint,
        )

    def _execute_strategy(self, case, strategy, environment, output_type=None):
        strategy_run_id = f"strategy-{uuid4().hex}"
        request = self._request(case, strategy_run_id)
        self._active = {
            "strategy_run_id": strategy_run_id,
            "request": request,
            "environment": environment,
            "attempt_number": 1,
            "deadline_at": time.monotonic() + min(case.deadline_ms, self.config.deadline_ms) / 1000,
        }
        started = time.monotonic()
        validation = determine_validation(request, environment, self.bundle)
        if validation.level != ValidationLevel.V0 or validation.blockers:
            return self._invalid(case, strategy, strategy_run_id, "production_validation_unsupported")

        before = set(self._call_records)
        classification = None
        rationale = ()
        decision = None
        initial_model = strategy.model
        initial_effort = strategy.effort
        recovery_actions = []
        counters = Counters()
        if strategy.kind == "router":
            try:
                classified = self.classifier.classify(request)
            except _StrategyDeadline:
                return self._failed_run(
                    case, strategy, strategy_run_id, self._calls_since(before), started,
                    evidence="strategy_deadline_exhausted", classification=None,
                )
            if isinstance(classified, ClassificationFailure):
                calls = self._calls_since(before)
                return self._failed_run(
                    case, strategy, strategy_run_id, calls, started,
                    evidence="classifier_failure", classification=None,
                )
            classification = classified.classification
            decision = route(request, classification, environment, self.bundle)
            if isinstance(decision, RouteRejection) or not decision.executable:
                return self._invalid(
                    case, strategy, strategy_run_id, "router_rejected_case",
                    calls=self._calls_since(before), classification=classification,
                )
            if decision.validation_level != ValidationLevel.V0:
                return self._invalid(
                    case, strategy, strategy_run_id, "router_requires_stronger_validation",
                    calls=self._calls_since(before), classification=classification,
                )
            initial_model = decision.selected_model_alias
            initial_effort = decision.reasoning_effort
            rationale = decision.rationale_codes
        else:
            model = self.bundle.catalog["models"].get(strategy.model)
            if (
                model is None
                or not model["availability"]["configured_enabled"]
                or strategy.effort.value not in model["reasoning_efforts"]
                or check_capabilities(request, model).violations
                or strategy.model not in environment.models
                or not environment.models[strategy.model].usable
                or environment.models[strategy.model].state == "UNHEALTHY"
            ):
                return self._invalid(case, strategy, strategy_run_id, "fixed_route_unsupported")

        current_model, current_effort = initial_model, initial_effort
        result = None
        terminal_unknown = False
        initial_generation_passed = None
        while True:
            self._active["attempt_number"] = counters.generation_attempts + 1
            model = self.bundle.catalog["models"][current_model]
            provider_request = ProviderRequest(
                task_id=request.task_id, trace_id=request.trace_id,
                invocation_id=f"generation-{uuid4().hex}",
                policy_version=self.bundle.policy["version"],
                catalog_version=self.bundle.catalog["catalog_version"],
                model_alias=current_model, provider_model_id=model["provider_model_id"],
                reasoning_effort=current_effort, input=request.input,
                output_type=output_type,
                max_output_tokens=case.context.expected_output_tokens,
                timeout_ms=min(case.deadline_ms, self.config.deadline_ms),
                purpose="generation",
            )
            counters = counters.model_copy(update={"generation_attempts": counters.generation_attempts + 1})
            try:
                outcome = self._generation_provider.execute(provider_request)
            except _StrategyDeadline:
                break
            except Exception:
                terminal_unknown = True
                break
            if self._call_records[provider_request.invocation_id].status == "unknown":
                terminal_unknown = True
                break
            v0_passed = (
                isinstance(outcome, ProviderResult)
                and outcome.response_status == "completed"
                and not outcome.refused
                and outcome.incomplete_reason is None
            )
            if v0_passed and output_type is not None:
                try:
                    if outcome.structured_output is None:
                        raise ValueError("structured output missing")
                    output_type.model_validate(outcome.structured_output.model_dump(mode="python"))
                except (TypeError, ValueError):
                    v0_passed = False
            if counters.generation_attempts == 1:
                if v0_passed:
                    initial_generation_passed = True
                elif (
                    isinstance(outcome, ProviderResult)
                    and outcome.response_status in {"completed", "incomplete"}
                ):
                    initial_generation_passed = False
                elif isinstance(outcome, ProviderFailure) and outcome.failure_type in {
                    FailureType.QUALITY_FAILURE, FailureType.VALIDATION_FAILURE,
                    FailureType.MALFORMED_OUTPUT,
                }:
                    initial_generation_passed = False
            if v0_passed:
                result = outcome
                break
            if strategy.kind != "router" or not strategy.recovery_enabled:
                break
            failure = (
                Failure(
                    failure_type=outcome.failure_type, source=outcome.source,
                    stage=outcome.stage, cause_code=outcome.cause_code,
                    retryable=outcome.retryable, retry_after_ms=outcome.retry_after_ms,
                )
                if isinstance(outcome, ProviderFailure)
                else Failure(
                    failure_type=FailureType.VALIDATION_FAILURE,
                    source="validation", stage="validation", cause_code="provider_not_completed",
                )
            )
            known = money_sum(tuple(
                call.cost_usd or Decimal("0") for call in self._calls_since(before)
            ))
            live_actions = (
                None if self._manifest.offline
                else self.live_guard.release.config.limits.actions
            )
            live_backoff = (
                None if self._manifest.offline
                else self.live_guard.release.config.limits.backoff
            )
            limits = ExecutionLimits(
                max_total_generation_attempts=(
                    self.config.max_generation_attempts if live_actions is None
                    else min(self.config.max_generation_attempts, live_actions.max_total_generation_attempts)
                ),
                max_quality_escalations=(
                    max(0, self.config.max_generation_attempts - 1) if live_actions is None
                    else live_actions.max_quality_escalations
                ),
                max_infrastructure_retries=(
                    max(0, self.config.max_generation_attempts - 1) if live_actions is None
                    else live_actions.max_infrastructure_retries
                ),
                max_tool_recoveries=0,
                max_elapsed_ms=min(case.deadline_ms, self.config.deadline_ms),
                initial_backoff_ms=0 if live_backoff is None else live_backoff.initial_ms,
                max_backoff_ms=0 if live_backoff is None else live_backoff.maximum_ms,
                task_cost_ceiling_usd=self.config.aggregate_cap_usd,
            )
            action = choose_recovery(
                (RecoveryContext if self._manifest.offline else __import__(
                    "model_router.execution.live", fromlist=["ReleaseRecoveryContext"]
                ).ReleaseRecoveryContext)(
                    decision=decision, failure=failure, counters=counters, limits=limits,
                    environment=environment,
                    remaining_usd=max(Decimal("0"), self.config.aggregate_cap_usd - known),
                    elapsed_ms=min(limits.max_elapsed_ms, int((time.monotonic() - started) * 1000)),
                    validated=failure.failure_type in {
                        FailureType.QUALITY_FAILURE, FailureType.VALIDATION_FAILURE,
                        FailureType.MALFORMED_OUTPUT,
                    },
                ),
                self.bundle,
            )
            recoverable_actions = {
                "increase_effort", "increase_tier", "retry_backoff", "health_aware_fallback"
            }
            if action.action in recoverable_actions and action.backoff_ms:
                remaining_backoff_ms = int(
                    (self._active["deadline_at"] - time.monotonic()) * 1000
                )
                if action.backoff_ms >= remaining_backoff_ms:
                    recovery_actions.append("stop_deadline")
                    break
                time.sleep(action.backoff_ms / 1000)
                if time.monotonic() >= self._active["deadline_at"]:
                    recovery_actions.append("stop_deadline")
                    break
            recovery_actions.append(action.action)
            if action.action not in recoverable_actions or action.route is None:
                break
            if action.action.startswith("increase_"):
                counters = counters.model_copy(update={"quality_escalations": counters.quality_escalations + 1})
            else:
                counters = counters.model_copy(update={"infrastructure_retries": counters.infrastructure_retries + 1})
            constrained = request.model_copy(update={"constraints": request.constraints.model_copy(update={
                "model_tier_floor": self.bundle.catalog["models"][action.route.model]["tier_rank"],
                "model_tier_ceiling": self.bundle.catalog["models"][action.route.model]["tier_rank"],
            })})
            selected = route(
                constrained, classification, environment, self.bundle,
                recovery_candidates=(Candidate(model=action.route.model, effort=action.route.effort, source="fallback"),),
            )
            if isinstance(selected, RouteRejection) or not selected.executable:
                recovery_actions.append("recovery_route_unavailable")
                break
            decision = selected
            current_model, current_effort = selected.selected_model_alias, selected.reasoning_effort

        calls = self._calls_since(before)
        latency = max(0, (time.monotonic() - started) * 1000)
        task_family = classification.task_family if classification else case.task_family_hint
        complexity = None if classification is None else self._complexity_band(classification.components.total)
        base = dict(
            strategy_run_id=strategy_run_id, case_id=case.case_id, strategy=strategy,
            input_sha256=canonical_comparison_sha256(case),
            validation_signature=_validation_signature(case, self.config.production_validation),
            policy_version=self.bundle.policy["version"], calls=calls,
            classification=classification, route_rationale=rationale,
            recovery_actions=tuple(recovery_actions), initial_model=initial_model,
            initial_effort=initial_effort, initial_generation_passed=initial_generation_passed,
            latency_ms=latency, task_family=task_family, complexity_band=complexity,
            source_kind=case.source_kind, consequence=case.consequence, tags=case.tags,
        )
        if terminal_unknown:
            candidate_id = f"candidate-{uuid4().hex}"
            return StrategyRun(**base, execution_status="unknown", complete=False,
                               grade=Grade(candidate_id=candidate_id, disposition=Disposition.UNKNOWN,
                                           evidence_codes=("generation_outcome_unknown",)))
        if result is None:
            candidate_id = f"candidate-{uuid4().hex}"
            return StrategyRun(**base, execution_status="failed", complete=True,
                               grade=Grade(candidate_id=candidate_id, disposition=Disposition.FAIL,
                                           evidence_codes=("generation_failed",)))
        return StrategyRun(**base, execution_status="completed", complete=True, output=_output(result))

    def _failed_run(self, case, strategy, strategy_run_id, calls, started, *, evidence, classification):
        candidate_id = f"candidate-{uuid4().hex}"
        unknown = any(call.status == "unknown" for call in calls)
        disposition = Disposition.UNKNOWN if unknown else Disposition.FAIL
        return StrategyRun(
            strategy_run_id=strategy_run_id, case_id=case.case_id, strategy=strategy,
            input_sha256=canonical_comparison_sha256(case),
            validation_signature=_validation_signature(case, self.config.production_validation),
            policy_version=self.bundle.policy["version"], calls=calls,
            classification=classification, execution_status="unknown" if unknown else "failed",
            complete=not unknown,
            grade=Grade(candidate_id=candidate_id, disposition=disposition, evidence_codes=(evidence,)),
            latency_ms=max(0, (time.monotonic() - started) * 1000),
            task_family=case.task_family_hint, source_kind=case.source_kind,
            consequence=case.consequence, tags=case.tags,
        )

    def _complexity_band(self, score):
        for band in self.bundle.policy["complexity_bands"]:
            if band["min"] <= score <= band["max"]:
                return f'{band["min"]}-{band["max"]}'
        return None

    def _grade(self, case, run, rng, adjudications):
        if run.grade is not None:
            return run, adjudications
        candidate_id = f"candidate-{uuid4().hex}"
        candidate = BlindCandidate(
            candidate_id=candidate_id, task=case.task, instructions=case.instructions,
            context_text=case.context_text, output=run.output,
            output_contract=case.output_contract, grading=case.grading, complete=run.complete,
        )
        adjudicate = (
            self.config.adjudicator is not None
            and adjudications < self.config.max_adjudications
            and rng.random() < self.config.adjudication_sample_rate
        )
        self._active = {
            "strategy_run_id": run.strategy_run_id,
            "request": self._request(case, run.strategy_run_id),
            "environment": self._environment(self._manifest.offline),
            "attempt_number": 1,
            "deadline_at": time.monotonic() + min(case.deadline_ms, self.config.deadline_ms) / 1000,
        }
        grade = self.grader.grade(candidate, adjudicate=adjudicate)
        if grade.candidate_id != candidate_id:
            grade = Grade(candidate_id=candidate_id, disposition=Disposition.UNKNOWN,
                          evidence_codes=("grader_candidate_mismatch",))
        def priced(score):
            if score is None:
                return None
            calls = tuple(
                self._call_records.get(call.call_id, call).model_copy(
                    update={"attempt_number": call.attempt_number}
                )
                for call in score.calls
            )
            return score.model_copy(update={"calls": calls})
        grade = grade.model_copy(update={"primary": priced(grade.primary),
                                         "adjudicator": priced(grade.adjudicator)})
        review_needed = (
            grade.disposition in {Disposition.UNKNOWN, Disposition.NEEDS_REVIEW}
            or grade.disagreement
            or grade.human_review_needed
        )
        if self.config.capture_review_outputs and run.output is not None and review_needed:
            try:
                reference = self.store.save_review_output(
                    self._manifest.run_id, candidate_id, run.output
                )
                grade = grade.model_copy(update={"output_reference": reference})
            except CalibrationStorageError:
                grade = grade.model_copy(update={
                    "evidence_codes": (*grade.evidence_codes, "review_output_not_saved")
                })
        elif run.output is not None and review_needed:
            grade = grade.model_copy(update={
                "evidence_codes": (*grade.evidence_codes, "review_output_not_retained")
            })
        added = ()
        for score in (grade.primary, grade.adjudicator):
            if score is not None:
                added += score.calls
        return run.model_copy(update={"grade": grade, "calls": (*run.calls, *added)}), adjudications + int(adjudicate)

    def _segment_case_runs(self, case, case_runs):
        """Attach one post-execution Router analysis to every comparison row."""
        router = next(
            (item for item in case_runs if item.strategy.kind == "router" and item.classification is not None),
            None,
        )
        classification = None if router is None else router.classification
        family = case.task_family_hint or (
            None if classification is None else classification.task_family
        )
        complexity = None if classification is None else self._complexity_band(
            classification.components.total
        )
        return [
            item.model_copy(update={"task_family": family, "complexity_band": complexity})
            for item in case_runs
        ]

    @staticmethod
    def _validate_corpus(cases, corpus_manifest, config) -> None:
        ids = [case.case_id for case in cases]
        expected_hashes = {case.case_id: case_content_sha256(case) for case in cases}
        privacy_order = {"public": 0, "internal": 1, "sensitive": 2, "restricted": 3}
        if (
            not cases
            or len(ids) != len(set(ids))
            or corpus_manifest.case_count != len(cases)
            or any(case.corpus_version != corpus_manifest.corpus_version for case in cases)
            or dict(corpus_manifest.case_hashes) != expected_hashes
            or corpus_manifest.privacy != max(
                (case.privacy for case in cases), key=privacy_order.__getitem__
            )
        ):
            raise ValueError("corpus does not match its manifest")
        if config.privacy_policy_version != "calibration-privacy-v1":
            raise ValueError("unsupported calibration privacy policy")
        if any(case.privacy not in config.allowed_privacy for case in cases):
            raise ValueError("corpus privacy is not allowed by the experiment")

    def run(self, cases, corpus_manifest, offline=True):
        cases = tuple(cases)
        self._validate_corpus(cases, corpus_manifest, self.config)
        plan = plan_budget(cases, self.config, self.bundle, self.classifier_config)
        rng = random.Random(self.config.seed)
        order = {}
        for case in cases:
            strategies = list(self.config.strategies)
            rng.shuffle(strategies)
            order[case.case_id] = tuple(strategy.name for strategy in strategies)
        run_id = f"calibration-{uuid4().hex}"
        classifier = self.classifier_config.model_dump(mode="json")
        classifier["adapter"] = "offline-injected" if offline else "live-release"
        if not offline and self.live_guard is not None:
            release = self.live_guard.release
            classifier["release_sha256"] = release.release_sha256
            if release.config.live.evidence is not None:
                classifier["live_evidence_sha256"] = release.config.live.evidence.sha256
                classifier["live_evidence_id"] = release.config.live.evidence.version
            if release.live_evidence is not None:
                classifier["credential_evidence_sha256"] = release.live_evidence.credential_sha256
        software_commit = _software_commit()
        self._manifest = RunManifest(
            run_id=run_id, created_at=datetime.now(UTC), corpus=corpus_manifest,
            policy_version=self.bundle.policy["version"], policy_sha256=self.bundle.content_hash,
            model_catalog=dict(self.bundle.catalog),
            pricing_snapshot={alias: dict(model["pricing"]) for alias, model in self.bundle.catalog["models"].items()},
            classifier=classifier, rubrics=_rubric_snapshot(cases), config=self.config,
            software_commit=software_commit,
            offline=offline, strategy_order=order,
        )
        self.store.start(self._manifest)
        self._event({"kind": "run_started"})
        self._call_records = {}
        self._started_unsettled = set()
        self._spent = Decimal("0")
        self._budget_stopped = False
        runs = []
        stopped = False
        reason = None
        adjudications = 0
        try:
            if not plan.admissible:
                raise LiveCalibrationBlocked("experiment has no admissible conservative budget")
            if not offline:
                if self.live_guard is None:
                    raise LiveCalibrationBlocked("live calibration guard is required")
                self._require_composition(False)
                self.live_guard.require_ready(
                    self.config, plan, self.bundle, self.classifier_config,
                    run_id=run_id, software_commit=software_commit,
                )
            else:
                self._require_composition(True)
            environment = self._environment(offline)
            by_name = {strategy.name: strategy for strategy in self.config.strategies}
            for case in cases:
                case_runs = []
                try:
                    output_type = compile_output_type(case.output_contract)
                except ValueError:
                    output_type = None
                    blocker = "output_contract_unsupported"
                else:
                    blocker = self._case_blocker(case, output_type)
                if blocker is not None:
                    for name in order[case.case_id]:
                        invalid = self._invalid(
                            case, by_name[name], f"strategy-{uuid4().hex}",
                            blocker,
                        )
                        case_runs.append(invalid)
                        self._event({
                            "kind": "strategy_completed",
                            "strategy_run_id": invalid.strategy_run_id,
                            "case_id": case.case_id, "strategy": name,
                            "execution_status": "invalid",
                        })
                    runs.extend(case_runs)
                    continue
                for name in order[case.case_id]:
                    if self._budget_stopped or (
                        not offline and self.live_guard.stopped
                    ):
                        stopped, reason = True, "budget_or_live_guard_stopped"
                        break
                    before = set(self._call_records)
                    attempt_started = time.monotonic()
                    try:
                        executed = self._execute_strategy(
                            case, by_name[name], environment, output_type
                        )
                    except LiveCalibrationBlocked:
                        active = self._active or {}
                        executed = self._failed_run(
                            case, by_name[name], active.get(
                                "strategy_run_id", f"strategy-{uuid4().hex}"
                            ), self._calls_since(before), attempt_started,
                            evidence="calibration_admission_stopped", classification=None,
                        )
                        stopped, reason = True, "budget_or_live_guard_stopped"
                    except CalibrationStorageError:
                        raise
                    except Exception:
                        active = self._active or {}
                        executed = self._failed_run(
                            case, by_name[name], active.get(
                                "strategy_run_id", f"strategy-{uuid4().hex}"
                            ), self._calls_since(before), attempt_started,
                            evidence="strategy_orchestration_error", classification=None,
                        )
                    case_runs.append(executed)
                    self._event({
                        "kind": "strategy_completed", "strategy_run_id": executed.strategy_run_id,
                        "case_id": case.case_id, "strategy": name,
                        "execution_status": executed.execution_status,
                    })
                    if stopped or self._budget_stopped or (
                        not offline and self.live_guard.stopped
                    ):
                        stopped = True
                        reason = reason or "budget_or_live_guard_stopped"
                        break
                case_runs = self._segment_case_runs(case, case_runs)
                grade_order = list(range(len(case_runs)))
                rng.shuffle(grade_order)
                for index in grade_order:
                    if stopped or self._budget_stopped or (
                        not offline and self.live_guard.stopped
                    ):
                        stopped, reason = True, reason or "budget_or_live_guard_stopped"
                        break
                    grade_before = set(self._call_records)
                    try:
                        case_runs[index], adjudications = self._grade(
                            case, case_runs[index], rng, adjudications
                        )
                    except CalibrationStorageError:
                        raise
                    except Exception as error:
                        added = self._calls_since(grade_before)
                        unknown = any(call.status == "unknown" for call in added)
                        grade = Grade(
                            candidate_id=f"candidate-{uuid4().hex}",
                            disposition=Disposition.UNKNOWN,
                            evidence_codes=("grading_outcome_unknown",),
                        )
                        case_runs[index] = case_runs[index].model_copy(update={
                            "grade": grade,
                            "calls": (*case_runs[index].calls, *added),
                        })
                        if isinstance(error, LiveCalibrationBlocked) or (
                            not offline and unknown
                        ):
                            stopped, reason = True, "budget_or_live_guard_stopped"
                            break
                    if self._budget_stopped or (
                        not offline and self.live_guard.stopped
                    ):
                        stopped, reason = True, "budget_or_live_guard_stopped"
                        break
                runs.extend(case_runs)
                if stopped:
                    break
        except LiveCalibrationBlocked:
            stopped, reason = True, "live_calibration_blocked"
        finally:
            self._active = None
        if not offline and self.live_guard is not None:
            known_total = None if self._started_unsettled or any(
                call.status == "unknown" or call.cost_usd is None
                for call in self._call_records.values()
            ) else money_sum(tuple(
                call.cost_usd for call in self._call_records.values()
                if call.cost_usd is not None
            ))
            try:
                self.live_guard.finish_run(known_total)
            except LiveCalibrationBlocked:
                stopped, reason = True, "allocation_settlement_failed"
        result = CalibrationRun(
            manifest=self._manifest, strategy_runs=tuple(runs),
            status="stopped" if stopped else "completed", stop_reason=reason,
        )
        if stopped:
            self._event({"kind": "run_stopped", "reason": reason})
        self.store.finish(result)
        return result


__all__ = ["CalibrationRunner"]
