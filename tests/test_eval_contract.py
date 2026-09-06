"""The grader's behavior is tested, not a nonexistent routing implementation."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from evals.grader import check_value, grade
from evals.run_local import ROOT, coverage, load_cases, load_contract, read_jsonl
from evals.schema import Case, Observation

CASES = {c.id: c for c in load_cases()}
MANIFEST, CATALOG, VOCAB = load_contract()
PASSING = read_jsonl(ROOT / "evals/fixtures/passing.jsonl", Observation)
INVALID = read_jsonl(ROOT / "evals/fixtures/invalid.jsonl", Observation)


def evaluate(result, case=None):
    return grade(case or CASES[result.case_id], result, CATALOG, MANIFEST["policy_version"], VOCAB)


@pytest.mark.parametrize("result", PASSING, ids=lambda r: r.case_id)
def test_authored_positive_fixtures(result):
    assert evaluate(result) == []


@pytest.mark.parametrize("result", INVALID, ids=lambda r: r.case_id)
def test_authored_negative_fixtures(result):
    assert evaluate(result), "An intentionally invalid observation must not pass"


@pytest.mark.parametrize("field,value,expected", [
    ("case_id", "other-case", "case_id mismatch"),
    ("policy_version", "latest", "unpinned policy_version"),
    ("model_tier", 3, "model tier spoofing"),
    ("rationale_codes", [], "empty rationale"),
    ("rationale_codes", ["QUALITY_ESCALATION"], "forbidden rationale"),
    ("rationale_codes", ["MADE_UP_CODE"], "unknown rationale code"),
    ("selected_model_alias", "nonexistent", "unknown model"),
    ("estimated_cost", None, "missing estimated_cost"),
    ("classification", None, "supplied classification changed"),
    ("facts", {}, "facts.complexity_score"),
])
def test_independent_mutations(field, value, expected):
    data = PASSING[0].model_dump()
    data[field] = value
    errors = evaluate(Observation.model_validate(data), CASES[PASSING[0].case_id])
    assert any(expected in error for error in errors)


def test_alternative_route_inside_envelope_is_accepted():
    data = PASSING[0].model_dump()
    data.update(selected_model_alias="terra", model_tier=1, reasoning_effort="low")
    data["estimated_cost"]["amount"] = "0.014"
    assert not evaluate(Observation.model_validate(data))


@pytest.mark.parametrize("case_id,model,effort,tier", [
    ("ornate_prompt", "luna", "none", 0),
    ("boundary_59", "terra", "medium", 1),
    ("reconcile_tools", "terra", "low", 1),
    ("architecture_small_scope", "luna", "low", 0),
])
def test_legitimate_lower_efforts_are_not_overconstrained(case_id, model, effort, tier):
    case = CASES[case_id]
    data = PASSING[0].model_dump()
    data.update(case_id=case_id, selected_model_alias=model, reasoning_effort=effort,
                model_tier=tier, classification=case.classification.model_dump(),
                facts={"complexity_score": sum(case.classification.components.values())})
    if case_id == "reconcile_tools":
        data["rationale_codes"] = ["TOOL_ORCHESTRATION_HIGH"]
    assert not evaluate(Observation.model_validate(data))


def test_blocked_valid_route_is_not_rejection():
    result = next(r for r in PASSING if r.case_id == "validation_high_approval")
    assert result.routing_result == "valid" and result.execution_readiness == "blocked"
    assert not evaluate(result)
    changed = result.model_dump()
    changed.update(routing_result="rejected", failure_type="VALIDATION_FAILURE")
    assert evaluate(Observation.model_validate(changed))


def test_unknown_required_cost_cannot_be_zero_or_executable():
    result = next(r for r in PASSING if r.case_id == "context_unknown_cache_write")
    data = result.model_dump()
    data["execution_readiness"] = "ready"
    assert "unknown cost cannot certify execution" in evaluate(Observation.model_validate(data))
    data["estimated_cost"]["amount"] = "0"
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


def test_catalog_facts_guard_against_overly_broad_envelopes():
    result = PASSING[0]
    data = CASES[result.case_id].model_dump()
    data["request"]["requirements"] = ["audio_input"]
    assert "hard capability violation" in evaluate(result, Case.model_validate(data))
    data["request"]["requirements"] = ["text_input"]
    data["request"]["context"]["expected_output_tokens"] = 128001
    assert "hard output limit" in evaluate(result, Case.model_validate(data))
    data["request"]["context"].update(input_tokens=1000000, expected_output_tokens=100000)
    assert "hard combined context limit" in evaluate(result, Case.model_validate(data))


@pytest.mark.parametrize("op,actual,expected,accepted", [
    ("eq", True, 1, False), ("eq", None, None, True),
    ("contains", ["a"], "a", True), ("contains", "abc", "a", False),
    ("excludes", ["task_id"], "raw_prompt", True),
    ("excludes", None, "raw_prompt", False),
    ("between", "0.0556", ["0.0556", "0.0556"], True),
    ("between", "NaN", [0, 1], False), ("between", True, [0, 1], False),
])
def test_assertions_fail_closed(op, actual, expected, accepted):
    assert check_value(actual, op, expected) is accepted


def test_schema_rejects_typo_bool_score_and_contradiction():
    original = CASES["format_titles"].model_dump()
    for change in [
        lambda d: d.update(schema_version=True),
        lambda d: d.update(unknown_field=True),
        lambda d: d["classification"]["components"].update(reasoning_depth=True),
        lambda d: d["expected"].update(minimum_tier=3, maximum_tier=0),
        lambda d: d["expected"]["forbidden_models"].append("luna"),
        lambda d: d["expected"].update(cost_status=None),
    ]:
        data = deepcopy(original)
        change(data)
        with pytest.raises(ValidationError):
            Case.model_validate(data)


@pytest.mark.parametrize("line", ['{"id":"a","id":"b"}', '{"confidence":NaN}', '{bad json}'])
def test_jsonl_rejects_ambiguous_or_malformed_records(tmp_path, line):
    path = tmp_path / "bad.jsonl"
    path.write_text(line)
    with pytest.raises(ValueError, match=r"bad.jsonl:1"):
        read_jsonl(path, Case)


def test_duplicate_and_component_range_audit(tmp_path):
    row = CASES["format_titles"].model_dump_json()
    path = tmp_path / "cases.jsonl"
    path.write_text(row + "\n" + row + "\n")
    with pytest.raises(ValueError, match="duplicate case ID"):
        load_cases(tmp_path)
    data = json.loads(row)
    data["classification"]["components"]["reasoning_depth"] = 26
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="component out of bounds"):
        load_cases(tmp_path)


def test_corpus_coverage_and_phase_boundary():
    report = coverage(list(CASES.values()))
    assert report["total"] >= 120
    assert report["must_not_use_astra"] >= 20
    assert report["boundaries"] == [19, 20, 21, 39, 40, 41, 59, 60, 61, 74, 75, 76, 87, 88, 89, 99, 100]
    assert set(report["task_family_supplied"]) == set(VOCAB["families"])
    assert all(n >= 3 for n in report["task_family_supplied"].values())
    assert len({c.classification.task_family for c in CASES.values() if c.category == "routing"}) == 16
    assert not (ROOT / "evals/cases/regressions.jsonl").read_text().strip()
    # Guard the deliberate separation from future routing and provider code.
    import ast
    for name in ("grader.py", "schema.py", "run_local.py"):
        tree = ast.parse((ROOT / "evals" / name).read_text())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        assert not any(m.startswith(("model_router", "openai", "fastapi", "sqlalchemy")) for m in modules)
    grader_source = (ROOT / "evals/grader.py").read_text()
    assert "routing-policy.yaml" not in grader_source


def test_exported_schemas_match_types():
    for name, model in [("case-v1", Case), ("observation-v1", Observation)]:
        assert json.loads((ROOT / f"evals/schema/{name}.json").read_text()) == model.model_json_schema()


@pytest.mark.parametrize("fixture,extra,code", [
    ("passing.jsonl", ["--allow-subset"], 0),
    ("invalid.jsonl", ["--allow-subset"], 1),
    ("passing.jsonl", [], 2),
])
def test_cli_status_from_another_working_directory(tmp_path, fixture, extra, code):
    run = subprocess.run([sys.executable, str(ROOT / "evals/run_local.py"), "--results",
                          str(ROOT / "evals/fixtures" / fixture), *extra],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == code, run.stdout + run.stderr


def test_cli_rejects_duplicate_unknown_and_empty_results(tmp_path):
    for rows in [[], [PASSING[0].model_dump()] * 2,
                 [PASSING[0].model_dump() | {"case_id": "missing"}]]:
        path = tmp_path / "results.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows))
        run = subprocess.run([sys.executable, str(ROOT / "evals/run_local.py"), "--results",
                              str(path), "--allow-subset"], capture_output=True, text=True)
        assert run.returncode == 2
