"""Black-box coverage for the Phase 1 eval adapter and offline runner."""

from __future__ import annotations

import ast
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from evals.grader import grade
from evals.phase1_adapter import (
    adapt_inputs,
    decision_metadata,
    observe,
    project,
    skip_reason,
)
from evals.run_local import load_cases, load_contract
from evals.run_phase1 import run
from model_router.policy.loader import load_bundle
from model_router.router import route


ROOT = Path(__file__).resolve().parents[1]
ALL_CASES = tuple(load_cases())
APPLICABLE_CASES = tuple(case for case in ALL_CASES if skip_reason(case) is None)

CLASSIFICATION_SKIP = "Phase 2: no supplied classification; requires a classifier adapter."
RECOVERY_SKIP = "Phase 3: requires execution of a scripted recovery trace."
EXPECTED_SKIPS = {
    **{
        case_id: CLASSIFICATION_SKIP
        for case_id in (
            "classify_transform",
            "classify_extract",
            "classify_conversation",
            "classify_writing",
            "classify_knowledge",
            "classify_analysis",
            "classify_math",
            "classify_engineering",
            "classify_research",
            "classify_coding",
            "classify_debugging",
            "classify_architecture",
            "classify_planning",
            "classify_data_analysis",
            "classify_tool_workflow",
            "classify_agentic",
            "classify_cross_repo_refactor",
            "classify_long_horizon_program",
            "classify_multi_system_change",
        )
    },
    **{
        case_id: RECOVERY_SKIP
        for case_id in (
            "quality_effort_success",
            "quality_tier_success",
            "quality_exhaustion",
            "quality_insufficient_budget",
            "provider_timeout",
            "provider_rate_limit",
            "provider_outage_fallback",
            "provider_no_safe_fallback",
            "tool_timeout",
            "tool_api_error",
            "alternate_tool",
            "unsafe_tool_replay",
            "malformed_diagnose",
            "validation_diagnose",
            "unknown_diagnose",
            "terminal_budget",
            "terminal_capability",
            "evaluator_infrastructure",
        )
    },
}


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(ROOT / "config")


@pytest.fixture(scope="module")
def grading_contract():
    manifest, catalog, vocabulary = load_contract()
    return manifest, catalog, vocabulary


@pytest.mark.parametrize("case", APPLICABLE_CASES, ids=lambda case: case.id)
def test_every_applicable_case_is_graded_by_the_original_oracle(case, bundle, grading_contract):
    manifest, catalog, vocabulary = grading_contract

    observation = observe(case, bundle)

    assert grade(case, observation, catalog, manifest["policy_version"], vocabulary) == []


def test_skip_set_and_each_reason_are_exact():
    actual = {
        case.id: reason
        for case in ALL_CASES
        if (reason := skip_reason(case)) is not None
    }

    assert len(actual) == 37
    assert actual == EXPECTED_SKIPS
    assert len(APPLICABLE_CASES) == 142


class _PoisonExpected:
    def __getattribute__(self, name):
        raise AssertionError(f"adapter read poisoned expected envelope attribute {name!r}")


def test_adapter_never_reads_the_expected_envelope(bundle):
    tree = ast.parse((ROOT / "evals" / "phase1_adapter.py").read_text())
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "expected"
        for node in ast.walk(tree)
    )

    case = next(case for case in APPLICABLE_CASES if case.id == "ornate_prompt")
    poisoned = case.model_copy(update={"expected": _PoisonExpected()})
    observation = observe(poisoned, bundle)

    assert observation.case_id == case.id


def test_projection_uses_modified_runtime_decision_evidence(bundle):
    case = next(case for case in APPLICABLE_CASES if case.id == "ornate_prompt")
    result = route(*adapt_inputs(case), bundle)
    details = dict(result.rationale_details)
    details.update(
        required_capabilities=("synthetic_capability",),
        floor_waiver_rules=("synthetic_rule",),
        floor_waiver_constraints=("synthetic_constraint",),
    )
    changed = result.model_copy(
        update={
            "complexity_score": 73,
            "rationale_details": details,
            "readiness_blockers": ("synthetic_blocker",),
            "effective_limits": result.effective_limits.model_copy(
                update={"model_tier_ceiling": 0}
            ),
            "estimated_cost": result.estimated_cost.model_copy(
                update={"known_subtotal": Decimal("9.8765")}
            ),
        }
    )

    observation = project("modified-runtime-evidence", changed)

    assert observation.facts["complexity_score"] == 73
    assert observation.facts["required_capabilities"] == ["synthetic_capability"]
    assert observation.facts["floor_waiver_rules"] == ["synthetic_rule"]
    assert observation.facts["floor_waiver_constraints"] == ["synthetic_constraint"]
    assert observation.facts["blockers"] == ["synthetic_blocker"]
    assert observation.facts["effective_limits"]["model_tier_ceiling"] == 0
    assert observation.facts["known_cost_subtotal"] == "9.8765"


class _InjectedDecisionDump:
    def __init__(self, result, sentinel):
        self.result = result
        self.sentinel = sentinel

    def model_dump(self, **kwargs):
        data = self.result.model_dump(**kwargs)
        data.update(
            input=self.sentinel,
            raw_prompt=self.sentinel,
            raw_response=self.sentinel,
            api_key="sk-injected-secret",
            credentials={"token": "injected"},
            authorization="Bearer injected",
        )
        return data


def test_metadata_allowlist_excludes_injected_secrets_and_raw_content(bundle):
    sentinel = "RAW-INPUT-SENTINEL-DO-NOT-PROJECT"
    case = next(case for case in APPLICABLE_CASES if case.id == "ornate_prompt")
    request = case.request.model_copy(update={"input": sentinel})
    changed_input = case.model_copy(update={"request": request})
    runtime_result = route(*adapt_inputs(changed_input), bundle)

    metadata = decision_metadata(_InjectedDecisionDump(runtime_result, sentinel))
    observation = project(case.id, runtime_result)
    serialized = observation.model_dump_json()

    forbidden = {
        "input",
        "raw_prompt",
        "raw_response",
        "api_key",
        "credentials",
        "authorization",
    }
    assert not forbidden.intersection(metadata)
    assert sentinel not in json.dumps(metadata)
    assert sentinel not in serialized
    assert "sk-injected-secret" not in json.dumps(metadata)
    assert observation.facts["secret_redacted"] is True


def test_fixture_labels_alone_do_not_change_the_decision(bundle):
    case = next(case for case in APPLICABLE_CASES if case.id == "ornate_prompt")
    relabeled_environment = case.environment.model_copy(
        update={
            "health_scenario": "decorative-health-label",
            "budget_scenario": "decorative-budget-label",
        }
    )
    relabeled = case.model_copy(update={"environment": relabeled_environment})

    assert observe(relabeled, bundle) == observe(case, bundle)


def test_full_run_is_deterministic_and_covers_each_applicable_id_once():
    first_report, first_observations = run()
    second_report, second_observations = run()

    expected_ids = {case.id for case in APPLICABLE_CASES}
    first_ids = [observation.case_id for observation in first_observations]
    assert first_report == second_report
    assert [item.model_dump_json() for item in first_observations] == [
        item.model_dump_json() for item in second_observations
    ]
    assert first_report["applicable"] == first_report["passed"] == 142
    assert first_report["failed"] == 0
    assert first_report["skipped"] == EXPECTED_SKIPS
    assert len(first_ids) == len(set(first_ids)) == 142
    assert set(first_ids) == expected_ids


def test_cli_runs_from_an_external_directory_without_an_openai_key(tmp_path):
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))

    completed = subprocess.run(
        [sys.executable, "-m", "evals.run_phase1"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Corpus 179; applicable 142; passed 142; failed 0; skipped 37." in completed.stdout
