"""Paid classification followed by deterministic routing, with no executor path."""
from dataclasses import dataclass
from decimal import Context as DecimalContext, Decimal, localcontext
from time import monotonic
from typing import Callable
from uuid import uuid4

from model_router.classification.classifier import ClassifierConfig, OpenAIClassifier
from model_router.core.classifier_contracts import ClassificationFailure
from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import EnvironmentSnapshot, Request, thaw
from model_router.core.execution_contracts import BudgetAuthority, Clock, ExecutionControls, RepositoryUnavailable
from model_router.core.preview_contracts import RoutingPreview, PreviewRepository
from model_router.core.provider_contracts import ModelProvider, ProviderEvidence, ProviderFailure
from model_router.execution.accounting import provider_cost
from model_router.execution.live import LiveExecutionAuthorization
from model_router.execution.safety import request_digest, scoped_key_digest
from model_router.router import route


@dataclass(frozen=True)
class PreviewDependencies:
    application_id: str
    release_sha256: str
    activation_id: str
    account_evidence_id: str
    bundle: PolicyBundle
    environment: Callable[[], EnvironmentSnapshot]
    classifier_config: ClassifierConfig
    classifier_provider: ModelProvider
    authorization: LiveExecutionAuthorization
    repository: PreviewRepository
    budget: BudgetAuthority
    clock: Clock
    deadline_ms: int

    def __post_init__(self):
        if (not self.application_id or type(self.deadline_ms) is not int
                or self.deadline_ms <= 0
                or self.classifier_config.timeout_ms > self.deadline_ms
                or self.classifier_config.timeout_ms > self.authorization.provider_timeout_ms):
            raise ValueError('finite preview timeout is required')


class PreviewUnavailable(Exception):
    """No paid work admitted; safe to report without dependency details."""


class _Stopped(Exception):
    pass


def classify_route(request: Request, key: str, dependencies: PreviewDependencies):
    with localcontext(DecimalContext(prec=80)):
        return _Preview(request, key, dependencies).run()


class _Preview:
    def __init__(self, request, key, dependencies):
        self.d = dependencies
        self.request, self.key = request, key
        self.started = monotonic()
        self.deadline_ms = min(dependencies.deadline_ms,
            request.constraints.task_deadline_ms or dependencies.deadline_ms)
        self.calls = 0
        self.value = None

    def save(self, **changes):
        current = self.value.model_copy(update={**changes, 'updated_at': self.d.clock.now()})
        self.d.repository.save(self.value, current)
        self.value = current

    def stop(self, code, *, uncertain=False):
        self.save(status='uncertain' if uncertain else 'blocked', cause_code=code)
        raise _Stopped()

    def run(self):
        d = self.d
        if self.request.policy_version not in (None, d.bundle.policy["version"]):
            raise PreviewUnavailable()
        if (self.request.application_id != d.application_id or not self.key.strip()
                or not d.authorization.ready()):
            raise PreviewUnavailable()
        self.environment = d.environment()
        if (self.environment.synthetic
                or self.environment.trusted_application_id != d.application_id):
            raise PreviewUnavailable()
        config = d.classifier_config
        if config.status != 'active' or not config.live_enabled:
            raise PreviewUnavailable()
        # Validate classifier binding before claiming or reserving anything.
        classifier = OpenAIClassifier(self, d.bundle, config)
        now = d.clock.now()
        model = d.bundle.catalog['models'][config.model_alias]
        self.value = RoutingPreview(
            preview_id='preview:' + uuid4().hex, application_id=d.application_id,
            task_id=self.request.task_id, trace_id=self.request.trace_id,
            status='claimed', created_at=now, updated_at=now,
            release_version=d.authorization.release_version,
            release_sha256=d.release_sha256, activation_id=d.activation_id,
            account_evidence_id=d.account_evidence_id,
            policy_version=d.bundle.policy['version'],
            catalog_version=d.bundle.catalog['catalog_version'],
            pricing_version=model['pricing']['version'], classifier_version=config.version,
            classifier_configuration_hash=config.configuration_hash)
        retained = d.repository.claim(self.value,
            scoped_key_digest(d.application_id, self.key),
            request_digest(self.request, ExecutionControls()))
        if retained is not None:
            # Even a pre-dispatch crash is conservatively retained. Never restart
            # paid work from claimed/started/accounted states on an HTTP retry.
            return retained
        try:
            d.repository.pin_versions(policy_version=self.value.policy_version,
                policy_snapshot=thaw({'policy': d.bundle.policy, 'budgets': d.bundle.budgets,
                    'validation': d.bundle.validation, 'content_hash': d.bundle.content_hash}),
                catalog_version=self.value.catalog_version, catalog_snapshot=thaw(d.bundle.catalog))
            classified = classifier.classify(self.request)
            if isinstance(classified, ClassificationFailure):
                self.stop('classifier_failed')
            self.save(classification=classified.classification)
            if self.value.actual_cost_usd is None:
                self.stop('classifier_cost_unknown', uncertain=True)
            if self.value.actual_cost_usd > self.value.reserved_cost_usd:
                self.stop('classifier_reservation_exceeded')
            if self.expired():
                self.stop('preview_deadline_exceeded')
            if not d.authorization.ready():
                self.stop('preview_readiness_changed')
            # Pass the unchanged classification and normal request facts to the
            # canonical router. Its executable flag is evidence, never a dispatch.
            decision = route(self.request, classified.classification, self.environment, d.bundle)
            self.save(status='completed', route=decision)
        except _Stopped:
            pass
        except RepositoryUnavailable:
            # No settlement may follow an unpersisted result. Started intent and
            # its reservation survive; recovery never guesses whether a call ran.
            raise
        except Exception:
            self.save(status='uncertain' if self.calls else 'blocked',
                cause_code='preview_dependency_failure')
        return self.value

    def expired(self):
        return (monotonic() - self.started) * 1000 >= self.deadline_ms

    def execute(self, invocation):
        """The classifier's sole provider port: admission precedes dispatch."""
        d = self.d
        config = d.classifier_config
        if (self.calls or invocation.purpose != 'classification'
                or invocation.model_alias != config.model_alias
                or invocation.reasoning_effort != config.reasoning_effort
                or invocation.timeout_ms != config.timeout_ms
                or invocation.max_output_tokens != config.max_output_tokens):
            self.stop('classifier_invocation_forbidden')
        if self.expired() or not d.authorization.allows(invocation):
            self.stop('classifier_admission_refused')
        remaining_ms = self.deadline_ms - int((monotonic() - self.started) * 1000)
        if remaining_ms <= 0:
            self.stop('preview_deadline_exceeded')
        invocation = invocation.model_copy(update={'timeout_ms': min(invocation.timeout_ms, remaining_ms)})
        model = d.bundle.catalog['models'][invocation.model_alias]
        upper = d.authorization.upper_cost(model, invocation.max_output_tokens)
        if (self.request.constraints.task_cost_ceiling_usd is not None
                and upper > self.request.constraints.task_cost_ceiling_usd):
            self.stop('classifier_budget_exhausted')
        identity = self.value.preview_id
        if not d.budget.reserve(identity, identity, upper):
            self.stop('classifier_budget_exhausted')
        # Persist the exact intent (no input, instructions or schema) before I/O.
        intent = ProviderEvidence(**{name: getattr(invocation, name)
            for name in ProviderEvidence.model_fields if hasattr(invocation, name)}, latency_ms=0)
        self.save(status='started', reserved_cost_usd=upper, cost_status='unknown',
            classifier_evidence=intent, classifier_timeout_ms=invocation.timeout_ms,
            classifier_max_input_tokens=d.authorization.max_input_tokens,
            classifier_max_output_tokens=invocation.max_output_tokens)
        if self.expired() or not d.authorization.ready():
            # No dispatch happened; persist zero evidence before releasing funds.
            self.save(status='accounted', actual_cost_usd=Decimal('0'), cost_status='not_incurred')
            d.budget.settle(identity, identity, '0')
            self.save(settled=True)
            self.stop('preview_readiness_changed')
        self.calls += 1
        try:
            outcome = d.classifier_provider.execute(invocation)
        except Exception:
            self.stop('classifier_outcome_unknown', uncertain=True)
        # Retain only the safe provider evidence base, never text, structured
        # output, arbitrary exception messages or diagnostic strings.
        evidence = ProviderEvidence.model_validate({
            name: getattr(outcome, name) for name in ProviderEvidence.model_fields})
        if any(getattr(evidence, name) != getattr(intent, name) for name in (
                'task_id', 'trace_id', 'invocation_id', 'model_alias', 'provider_model_id',
                'reasoning_effort', 'purpose', 'policy_version', 'catalog_version')):
            self.stop('classifier_evidence_mismatch', uncertain=True)
        tariff_matches = (evidence.returned_model_id == invocation.provider_model_id
            and evidence.returned_service_tier == 'default')
        actual = provider_cost(self.request, outcome, d.bundle, self.environment) if tariff_matches else None
        self.save(status='accounted', classifier_evidence=evidence, actual_cost_usd=actual,
            classifier_usage_status=evidence.usage.status,
            cost_status='known' if actual is not None else 'unknown')
        if actual is None:
            self.stop('classifier_tariff_unknown' if not tariff_matches else 'classifier_cost_unknown', uncertain=True)
        d.budget.settle(identity, identity, actual)
        self.save(settled=True)
        if isinstance(outcome, ProviderFailure):
            self.stop('classifier_timeout' if outcome.failure_type == 'TIMEOUT' else 'classifier_failed')
        return outcome
