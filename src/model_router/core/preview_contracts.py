"""Content-free evidence for a paid classifier-only routing preview."""
from datetime import datetime
from typing import Literal, Protocol

from model_router.core.contracts import Classification, Duration, Money, Name, Record, RouteDecision, RouteRejection
from model_router.core.provider_contracts import ProviderEvidence


class RoutingPreview(Record):
    purpose: Literal["classify_route_preview"] = "classify_route_preview"
    preview_id: Name
    application_id: Name
    task_id: Name
    trace_id: Name
    status: Literal["claimed", "started", "accounted", "completed", "blocked", "uncertain"]
    created_at: datetime
    updated_at: datetime
    release_version: Name
    release_sha256: Name
    activation_id: Name
    account_evidence_id: Name
    policy_version: Name
    catalog_version: Name
    pricing_version: Name
    classifier_version: Name
    classifier_configuration_hash: Name
    classifier_timeout_ms: Duration | None = None
    classifier_max_input_tokens: Duration | None = None
    classifier_max_output_tokens: Duration | None = None
    classification: Classification | None = None
    classifier_evidence: ProviderEvidence | None = None
    classifier_usage_status: Literal["known", "partial", "unavailable"] = "unavailable"
    route: RouteDecision | RouteRejection | None = None
    reserved_cost_usd: Money | None = None
    actual_cost_usd: Money | None = None
    cost_status: Literal["not_incurred", "unknown", "known"] = "not_incurred"
    settled: bool = False
    cause_code: Name | None = None


class PreviewCapacityExceeded(Exception):
    """Finite evidence allocation exhausted without retaining another row."""


class PreviewRepository(Protocol):
    def claim(self, preview: RoutingPreview, key_digest: str,
              request_digest: str) -> RoutingPreview | None: ...
    def save(self, previous: RoutingPreview, current: RoutingPreview) -> None: ...
    def get(self, preview_id: str, application_id: str) -> RoutingPreview | None: ...
    def pin_versions(self, *, policy_version: str, policy_snapshot: dict,
                     catalog_version: str, catalog_snapshot: dict) -> None: ...
