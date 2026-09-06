"""Project classifier outcomes into the independent classification-eval schema."""

from __future__ import annotations

import json
from pathlib import Path

from evals.schema import Observation
from model_router.core.classifier_contracts import ClassificationFailure, ClassificationResult
from model_router.core.contracts import Request


DATA = Path(__file__).resolve().parent / "phase2_data"


def load_mock_outputs(path: str | Path = DATA / "mock-classifications-v1.json") -> dict:
    """Load task-keyed outputs; fixture rows contain no cases or expected envelopes."""
    raw = json.loads(Path(path).read_text())
    if raw.get("schema_version") != 1 or not isinstance(raw.get("outputs"), dict):
        raise ValueError("invalid Phase 2 classifier fixture")
    if not raw["outputs"]:
        raise ValueError("empty Phase 2 classifier fixture")
    return raw["outputs"]


def adapt_request(case) -> Request:
    """Translate only eval request facts, never expected classification fields."""
    if case.category != "classification" or case.classification is not None or case.scenario is not None:
        raise ValueError("case is outside Phase 2 classification scope")
    return Request(**case.request.model_dump(), task_id=case.id, trace_id=f"eval:{case.id}")


def project(case_id: str, outcome, policy_version: str) -> Observation:
    common = dict(
        schema_version=1, case_id=case_id, routing_result="not_applicable",
        policy_version=policy_version, execution_readiness="not_applicable",
    )
    if isinstance(outcome, ClassificationResult):
        classification = outcome.classification
        return Observation(
            **common,
            classification=dict(
                task_family=classification.task_family,
                components=classification.components.model_dump(mode="json"),
                confidence=classification.confidence,
                flags=dict(classification.flags),
                provenance=classification.provenance,
            ),
            facts={
                "classifier_version": outcome.classifier_version,
                "prompt_version": outcome.prompt_version,
                "classifier_schema_version": outcome.schema_version,
                "configuration_hash": outcome.configuration_hash,
                "provider_accounting_present": outcome.provider_result is not None,
            },
        )
    if isinstance(outcome, ClassificationFailure):
        return Observation(
            **common, failure_type=outcome.failure_type.value,
            facts={
                "classifier_version": outcome.classifier_version,
                "cause_code": outcome.cause_code,
                "diagnostic_fields": list(outcome.diagnostic_fields),
                "provider_accounting_present": outcome.provider_result is not None,
            },
        )
    raise TypeError("classifier returned an unknown outcome")


def observe(case, classifier, policy_version: str) -> tuple[Observation, object]:
    request = adapt_request(case)
    outcome = classifier.classify(request)
    return project(case.id, outcome, policy_version), outcome
