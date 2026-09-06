"""Phase 2 classification eval integration stays independent and offline by default."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from evals.grader import grade
from evals.phase2_adapter import adapt_request, load_mock_outputs, observe
from evals.run_local import load_cases, load_contract
from evals.run_phase2 import ROOT, run
from evals.schema import Case
from model_router.classification import MockClassifier, load_classifier_config
from model_router.policy.loader import load_bundle


def classification_cases():
    return [case for case in load_cases() if case.category == "classification"]


def mock_classifier():
    bundle = load_bundle(ROOT / "config")
    config = load_classifier_config(ROOT / "config/classifier.yaml", bundle)
    return MockClassifier(load_mock_outputs(), bundle, config), bundle


def test_all_19_authored_seeds_use_mock_classifier_and_existing_grader():
    classifier, bundle = mock_classifier()
    report, observations = run(classifier=classifier, bundle=bundle)
    assert report["classification_seeds"] == 19
    assert report["passed"] == 19 and report["failed"] == 0
    assert report["mode"] == "mock"
    assert report["recovery_scenarios_executed"] == 0
    assert len(observations) == classifier.call_count == 19
    assert all(row.routing_result == "not_applicable" for row in observations)
    assert all(row.classification is not None for row in observations)


def test_fixture_is_keyed_only_by_task_input_and_covers_every_seed():
    outputs = load_mock_outputs()
    cases = classification_cases()
    assert set(outputs) == {case.request.input for case in cases}
    fixture_text = (ROOT / "evals/phase2_data/mock-classifications-v1.json").read_text()
    assert "acceptable_task_families" not in fixture_text
    assert "component_envelopes" not in fixture_text
    assert "classify_transform" not in fixture_text


def test_poisoned_expected_envelope_cannot_change_classifier_output():
    classifier, bundle = mock_classifier()
    case = next(case for case in classification_cases() if case.id == "classify_transform")
    manifest, catalog, vocabulary = load_contract()
    original, _ = observe(case, classifier, manifest["policy_version"])

    poisoned = deepcopy(case.model_dump())
    poisoned["expected"]["acceptable_task_families"] = ["writing"]
    poisoned["expected"]["component_envelopes"] = {
        name: [0, 0] for name in poisoned["expected"]["component_envelopes"]
    }
    poisoned["expected"]["flags"]["substantive_implementation"] = True
    poisoned_case = Case.model_validate(poisoned)
    repeated, _ = observe(poisoned_case, classifier, manifest["policy_version"])

    assert repeated.classification == original.classification
    errors = grade(poisoned_case, repeated, catalog, manifest["policy_version"], vocabulary)
    assert "classification family" in errors
    assert any(error.startswith("classification component") for error in errors)
    assert "classification flag substantive_implementation" in errors


def test_report_has_family_envelope_component_flag_and_provenance_counts():
    report, observations = run()
    assert sum(report["family_counts"].values()) == len(observations) == 19
    assert report["envelope_counts"] == {"passed": 19, "failed": 0}
    assert report["family_envelope_counts"]
    assert all(sum(counts.values()) == 19 for counts in report["component_counts"].values())
    assert all(counts["true"] + counts["false"] == 19 for counts in report["flag_counts"].values())
    assert sum(report["provenance_counts"].values()) == 19
    ambiguities = report["ambiguities"]
    assert ambiguities["classification_source"] == "deterministic_mock"
    assert ambiguities["authored_multi_family_envelope_count"] > 0
    assert "not measured live uncertainty" in ambiguities["note"]
    assert all(counts == {"passed": 19, "failed": 0}
               for counts in report["dimension_passes"].values())
    assert report["classifier"]["prompt_version"] == "task-properties-v1"
    assert report["live_invocations"] == []


def test_live_cli_uses_external_settings_and_still_blocks_before_dispatch(tmp_path):
    environment = os.environ.copy()
    environment["RUN_LIVE_OPENAI_TESTS"] = "1"
    environment["OPENAI_LIVE_EVAL_CONFIG"] = str(tmp_path / "missing-reviewed-settings.yaml")
    environment.pop("OPENAI_API_KEY", None)
    completed = subprocess.run([sys.executable, str(ROOT / "evals/run_phase2.py"), "--live"],
        cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30)
    assert completed.returncode == 2
    assert "invalid live-eval settings" in completed.stderr


def test_adapter_rejects_nonclassification_and_scripted_cases():
    cases = load_cases()
    routing_case = next(case for case in cases if case.category == "routing")
    recovery_case = next(case for case in cases if case.scenario is not None)
    for case in (routing_case, recovery_case):
        try:
            adapt_request(case)
        except ValueError as error:
            assert "outside Phase 2 classification scope" in str(error)
        else:
            raise AssertionError("Phase 2 adapter accepted a routing or recovery case")


def test_live_cli_is_explicitly_gated_before_any_call(tmp_path):
    environment = os.environ.copy()
    environment.pop("RUN_LIVE_OPENAI_TESTS", None)
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    completed = subprocess.run(
        [sys.executable, "-m", "evals.run_phase2", "--live"], cwd=tmp_path,
        env=environment, text=True, capture_output=True, timeout=30,
    )
    assert completed.returncode == 2
    assert "RUN_LIVE_OPENAI_TESTS=1 is required" in completed.stderr


def test_cli_runs_from_another_working_directory(tmp_path):
    report_path = tmp_path / "report.json"
    result_path = tmp_path / "observations.jsonl"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    completed = subprocess.run(
        [sys.executable, "-m", "evals.run_phase2", "--report", str(report_path),
         "--results", str(result_path)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "19 seeds; 19 passed; 0 failed" in completed.stdout
    assert json.loads(report_path.read_text())["mode"] == "mock"
    assert len(result_path.read_text().splitlines()) == 19
